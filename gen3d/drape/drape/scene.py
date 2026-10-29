import argparse
import hashlib
import json
import time
import traceback
from pathlib import Path

from drape._repo import bootstrap, DRAPE

bootstrap()

import numpy as np
import yaml

import pygarment.data_config as data_config
from pygarment.meshgen import boxmeshgen as boxmeshgen_mod
if not hasattr(boxmeshgen_mod.Edge, "name"):
    boxmeshgen_mod.Edge.name = "edge"
from pygarment.meshgen.boxmeshgen import BoxMesh
from pygarment.meshgen.sim_config import PathCofig, SimConfig

import warp as wp  # resolve warp after pygarment, mirrors drape.drape

from drape import drape as drape_mod
from drape._repo import GC

FORMAT = "seam-scene/1"


def _bytes_sha256(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


def _wp_to_np(array, shape=None, dtype=None):
    out = array.numpy().copy()
    if shape is not None:
        out = out.reshape(shape)
    if dtype is not None:
        out = out.astype(dtype)
    return out


def _collect_arrays(cloth, config, params, paths) -> dict[str, np.ndarray]:
    ctx = cloth.ctx
    model = ctx.model
    cdata = cloth.cloth
    V = int(model.particle_count)
    F = int(model.tri_count)
    S = int(model.spring_count)
    E = int(model.edge_count)
    BF = int(cdata.body_faces.shape[0])

    arrays: dict[str, np.ndarray] = {}
    arrays["x0"] = _wp_to_np(model.particle_q, shape=(V, 3), dtype=np.float32)
    arrays["v0"] = _wp_to_np(model.particle_qd, shape=(V, 3), dtype=np.float32)
    arrays["mass"] = _wp_to_np(model.particle_mass, dtype=np.float32)
    arrays["inv_mass"] = _wp_to_np(model.particle_inv_mass, dtype=np.float32)
    arrays["radius"] = _wp_to_np(model.particle_radius, dtype=np.float32)
    arrays["flags"] = _wp_to_np(model.particle_flags, dtype=np.int32)

    tri_indices = _wp_to_np(model.tri_indices, dtype=np.int32)
    if tri_indices.ndim == 1:
        tri_indices = tri_indices.reshape(F, 3)
    arrays["faces"] = tri_indices
    tri_mat = _wp_to_np(model.tri_materials, shape=(F, 5), dtype=np.float32)
    arrays["tri_ke"] = tri_mat[:, 0].copy()
    arrays["tri_ka"] = tri_mat[:, 1].copy()
    arrays["tri_kd"] = tri_mat[:, 2].copy()
    arrays["tri_rest_pose"] = _wp_to_np(model.tri_poses, shape=(F, 2, 2), dtype=np.float32)
    arrays["tri_rest_area"] = _wp_to_np(model.tri_areas, dtype=np.float32)

    springs_flat = _wp_to_np(model.spring_indices, dtype=np.int32).reshape(-1)
    arrays["springs"] = springs_flat.reshape(S, 2) if S else np.zeros((0, 2), dtype=np.int32)
    arrays["spring_rest"] = _wp_to_np(model.spring_rest_length, dtype=np.float32)
    arrays["spring_ke"] = _wp_to_np(model.spring_stiffness, dtype=np.float32)
    arrays["spring_kd"] = _wp_to_np(model.spring_damping, dtype=np.float32)

    bend = _wp_to_np(model.edge_indices, dtype=np.int32)
    if E:
        bend = bend.reshape(E, 4)
    else:
        bend = np.zeros((0, 4), dtype=np.int32)
    arrays["bend"] = bend
    arrays["bend_rest"] = _wp_to_np(model.edge_rest_angle, dtype=np.float32)
    bend_props = _wp_to_np(model.edge_bending_properties, shape=(E, 2) if E else (0, 2), dtype=np.float32)
    arrays["bend_ke"] = bend_props[:, 0].copy() if E else np.zeros(0, dtype=np.float32)
    arrays["bend_kd"] = bend_props[:, 1].copy() if E else np.zeros(0, dtype=np.float32)

    stitch_sorted = np.asarray(sorted(int(v) for v in cdata.stitch_set), dtype=np.int32)
    arrays["stitch"] = stitch_sorted

    panel_labels, used_parts, ref_names, ref_v, ref_f, ref_v_off, ref_f_off, panels_list, panel_id = _rebuild_panel_meta(cdata)
    arrays["panel_id"] = panel_id
    arrays["ref_v"] = ref_v
    arrays["ref_f"] = ref_f
    arrays["ref_v_off"] = ref_v_off
    arrays["ref_f_off"] = ref_f_off

    arrays["body_v"] = np.ascontiguousarray(cdata.body_verts, dtype=np.float32)
    arrays["body_f"] = np.ascontiguousarray(cdata.body_faces, dtype=np.int32).reshape(-1, 3)

    face_filters = _wp_to_np(ctx.face_filters, dtype=np.uint8)
    if face_filters.ndim == 1 and BF > 0:
        face_filters = face_filters.reshape(-1, BF)
    arrays["face_filters"] = face_filters
    arrays["particle_filter_id"] = _wp_to_np(ctx.particle_filter_id, dtype=np.int32)
    arrays["ref_label"] = _wp_to_np(ctx.ref_label, dtype=np.int32)

    pairs = _wp_to_np(ctx.allow_pairs, dtype=np.int32)
    if pairs.size:
        pairs = pairs.reshape(-1, 2)
    else:
        pairs = np.zeros((0, 2), dtype=np.int32)
    arrays["allow_pairs"] = pairs

    att_n = int(ctx.att_particle.shape[0])
    arrays["att_particle"] = _wp_to_np(ctx.att_particle, dtype=np.int32) if att_n else np.zeros(0, dtype=np.int32)
    arrays["att_point"] = _wp_to_np(ctx.att_point, shape=(att_n, 3), dtype=np.float32) if att_n else np.zeros((0, 3), dtype=np.float32)
    arrays["att_normal"] = _wp_to_np(ctx.att_normal, shape=(att_n, 3), dtype=np.float32) if att_n else np.zeros((0, 3), dtype=np.float32)
    arrays["att_ke"] = _wp_to_np(ctx.att_stiffness, dtype=np.float32) if att_n else np.zeros(0, dtype=np.float32)
    arrays["att_kd"] = _wp_to_np(ctx.att_damping, dtype=np.float32) if att_n else np.zeros(0, dtype=np.float32)

    smoother = cloth.components.smoother
    if smoother is not None and smoother.frames:
        frames = np.asarray(smoother.frames, dtype=np.int32)
        verts = np.stack([smoother.verts_for_frame(int(f)) for f in frames]).astype(np.float32)
        arrays["smooth_frames"] = frames
        arrays["smooth_verts"] = verts

    arrays["boxmesh_obj"] = np.frombuffer(Path(paths.g_box_mesh).read_bytes(), dtype=np.uint8)

    return arrays, panels_list, ref_names


def _rebuild_panel_meta(cloth_data):
    # build_scene keeps no panel labels on ctx; the assignment is deterministic, so re-run it
    from drape.sim_newton.panel_drag import PanelAssignment, extract_submesh

    assignment = PanelAssignment()
    panel_labels, used_parts = assignment.run(cloth_data, strategy="closest", merge_two_legs=True, smpl_body=False)
    # mirror register_reference_shapes: drop parts with no whole face
    flat = np.ascontiguousarray(cloth_data.body_faces, dtype=np.int32).reshape(-1)
    ref_names: list[str] = []
    sub_verts_all: list[np.ndarray] = []
    sub_faces_all: list[np.ndarray] = []
    for name, part_verts in used_parts.items():
        sv, sf = extract_submesh(cloth_data.body_verts, flat, part_verts)
        if not sf.size:
            continue
        ref_names.append(name)
        sub_verts_all.append(np.asarray(sv, dtype=np.float32))
        sub_faces_all.append(np.asarray(sf, dtype=np.int32).reshape(-1, 3))
    v_offsets = [0]
    f_offsets = [0]
    for sv, sf in zip(sub_verts_all, sub_faces_all):
        v_offsets.append(v_offsets[-1] + len(sv))
        f_offsets.append(f_offsets[-1] + len(sf))
    ref_v = np.concatenate(sub_verts_all, axis=0) if sub_verts_all else np.zeros((0, 3), dtype=np.float32)
    ref_f = np.concatenate(sub_faces_all, axis=0) if sub_faces_all else np.zeros((0, 3), dtype=np.int32)
    ref_v_off = np.asarray(v_offsets, dtype=np.int32)
    ref_f_off = np.asarray(f_offsets, dtype=np.int32)

    panels_list = sorted({str(l) for l in panel_labels if l})
    index = {name: i for i, name in enumerate(panels_list)}
    panel_id = np.array([index[l] if l else -1 for l in panel_labels], dtype=np.int32)
    return panel_labels, used_parts, ref_names, ref_v, ref_f, ref_v_off, ref_f_off, panels_list, panel_id


def _sim_dict(config: SimConfig, params, dump_every: int | None) -> dict:
    frame_dt = 1.0 / float(config.sim_fps)
    sub_dt = frame_dt / int(config.sim_substeps)
    return {
        "fps": float(config.sim_fps),
        "substeps": int(config.sim_substeps),
        "iterations": int(params.iterations),
        "frame_dt": frame_dt,
        "sub_dt": sub_dt,
        "detect_dt": sub_dt * int(config.sim_substeps),
        "gravity": list(params.gravity_on),
        "zero_gravity_steps": int(config.zero_gravity_steps),
        "max_sim_steps": int(config.max_sim_steps),
        "min_sim_steps": int(config.min_sim_steps),
        "attachment_enabled": bool(config.enable_attachment_constraint),
        "attachment_frames": int(config.attachment_frames),
        "max_frame_time": None if config.max_frame_time is None else int(config.max_frame_time),
        "max_sim_time": int(config.max_sim_time),
        "static_threshold": float(config.static_threshold),
        "non_static_percent": float(config.non_static_percent),
        "max_body_collisions": int(config.max_body_collisions),
        "max_self_collisions": int(config.max_self_collisions),
        "damping": [float(config.global_damping_factor), float(config.global_damping_effective_velocity), float(config.global_max_velocity)],
        "particle_max_velocity": float(config.global_max_velocity),
        "body_thickness": float(config.body_thickness),
        "soft_contact_margin": float(config.soft_contact_margin),
        "body_mu": float(config.body_friction),
        "particle_mu": float(config.particle_mu),
        "particle_adhesion": float(config.particle_adhesion),
        "soft_contact_relaxation": float(params.soft_contact_relaxation),
        "self_contact_relaxation": float(params.self_contact_relaxation),
        "soft_contact_max": int(params.soft_contact_max),
        "pt_per_particle": int(params.pt_per_particle),
        "ee_per_spring": int(params.ee_per_spring),
        "pt_query_radii": float(params.pt_query_radii),
        "detect_band_radii": float(params.detect_band_radii),
        "cloth_reference_margin": float(config.cloth_reference_margin),
        "ray_axes": [list(a) for a in params.ray_axes],
        "enable": {
            "cloth_reference_drag": bool(config.enable_cloth_reference_drag),
            "global_collision_filter": bool(config.enable_global_collision_filter),
            "triangle_particle_collisions": bool(config.enable_triangle_particle_collisions),
            "edge_edge_collisions": bool(config.enable_edge_edge_collisions),
            "body_collision_filters": bool(config.enable_body_collision_filters),
            "body_smoothing": bool(config.enable_body_smoothing),
        },
        "dump_every": None if not dump_every else int(dump_every),
    }


def write_scene(cloth, paths, name: str, item: str, body: str, record: dict, config: SimConfig, dump_every: int | None) -> Path:
    arrays, panels_list, ref_names = _collect_arrays(cloth, config, cloth.params, paths)
    out_el = Path(paths.out_el)
    out_el.mkdir(parents=True, exist_ok=True)
    npz_path = out_el / f"{name}_scene.npz"
    json_path = out_el / f"{name}_scene.json"
    # save with keys in a stable order so byte comparison is meaningful
    ordered = dict(sorted(arrays.items()))
    np.savez(npz_path, **ordered)
    sha = {k: _bytes_sha256(v) for k, v in ordered.items()}
    labels = {}
    if Path(paths.g_vert_labels).exists():
        labels = yaml.safe_load(Path(paths.g_vert_labels).read_text()) or {}
    meta = {
        "format": FORMAT,
        "name": name,
        "item": item,
        "body": body,
        "build_error": None,
        "sim": _sim_dict(config, cloth.params, dump_every),
        "panels": panels_list,
        "ref_names": ref_names,
        "vertex_labels": labels,
        "body_seg": {k: list(map(int, v)) for k, v in cloth.cloth.body_seg.items()},
        "record": record,
        "sha256": sha,
    }
    json_path.write_text(json.dumps(meta, indent=2))
    print(f"scene -> {npz_path}")
    print(f"scene -> {json_path}")
    return npz_path


def write_build_error(paths: PathCofig, name: str, item: str, body: str, record: dict, config: SimConfig, tag: str, dump_every: int | None) -> Path:
    out_el = Path(paths.out_el)
    out_el.mkdir(parents=True, exist_ok=True)
    json_path = out_el / f"{name}_scene.json"
    params = _dummy_params()
    meta = {
        "format": FORMAT,
        "name": name,
        "item": item,
        "body": body,
        "build_error": tag,
        "sim": _sim_dict(config, params, dump_every),
        "panels": [],
        "ref_names": [],
        "vertex_labels": {},
        "body_seg": {},
        "record": record,
        "sha256": {},
    }
    json_path.write_text(json.dumps(meta, indent=2))
    print(f"scene build_error={tag} -> {json_path}")
    return json_path


def _dummy_params():
    from drape.sim_newton import SimParams
    return SimParams()


def _record_fields(name: str, item: str, body: str, props, args) -> dict:
    rec = {
        "item": item,
        "name": name,
        "body": body,
        "resolution_scale": props["sim"]["config"]["resolution_scale"],
        "material": dict(drape_mod.MATERIAL_USED),
        "flags": drape_mod.flag_record(args)["flags"],
    }
    return rec


def _add_build_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs")
    ap.add_argument("--bodies", type=Path, default=DRAPE / "runs/bodies")
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out_newton_scene")
    ap.add_argument("--wearer", default="wearer_masc")
    ap.add_argument("--base", default="masc", choices=("masc", "fem"))
    ap.add_argument("--only")
    ap.add_argument("--size")
    ap.add_argument("--arm-pose", "--pose-deg", dest="arm_pose", type=float, default=None)
    ap.add_argument("--preset", choices=sorted(drape_mod.PRESETS))
    ap.add_argument("--neck-hold", choices=("none", "ring", "points"), default=None)
    ap.add_argument("--neck-stiff", type=float, default=None)
    ap.add_argument("--release-frame", type=int, default=None)
    ap.add_argument("--dump-every", type=int, default=None)
    ap.add_argument("--hold", choices=("auto", "on", "off"), default="auto")
    ap.add_argument("--body-friction", type=float, default=None)
    ap.add_argument("--res", type=float, default=None)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--no-attachment", action="store_true")
    ap.add_argument("--frame-timeout", type=int, default=None)
    ap.add_argument("--material")
    ap.add_argument("--spec", type=Path, help="direct mode: folder containing <name>_specification.json")
    ap.add_argument("--name", help="direct mode: spec name")
    ap.add_argument("--reuse-mesh", action="store_true",
                    help="keep a box mesh already in the sim dir (e.g. copied from a reference run) instead of re-meshing")


def _props_from_args(args, hold: bool, material: str | None):
    return drape_mod.load_props(
        res=args.res, max_steps=args.max_steps, attachment=not args.no_attachment,
        material=material, frame_timeout=args.frame_timeout, hold=hold,
        body_friction=args.body_friction, preset=args.preset, release_frame=args.release_frame,
    )


def _export_one(spec_dir: Path, name: str, wearer: str, out_dir: Path, props, args, item: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = PathCofig(
        in_element_path=str(spec_dir),
        out_path=str(out_dir),
        in_name=name,
        body_name=wearer,
        smpl_body=False,
        add_timestamp=False,
    )
    t0 = time.time()
    if args.reuse_mesh and Path(paths.g_box_mesh).exists():
        print(f"reusing box mesh {paths.g_box_mesh}")
    else:
        box = BoxMesh(paths.in_g_spec, props["sim"]["config"]["resolution_scale"])
        box.load()
        box.serialize(paths, store_panels=True, uv_config=props["render"]["config"]["uv_texture"])
    meshgen_s = round(time.time() - t0, 2)

    rec = _record_fields(name, item, wearer, props, args)
    rec["meshgen_s"] = meshgen_s
    labels = yaml.safe_load(Path(paths.g_vert_labels).read_text()) if Path(paths.g_vert_labels).exists() else {}
    labels = labels or {}
    rec["label_verts"] = {k: len(v) for k, v in labels.items()}

    config = SimConfig(props["sim"]["config"])
    drape_mod.install_newton_patches()
    from drape.gc_sim.garment import Cloth
    from drape.sim_newton import StitchGeometryError

    try:
        cloth = Cloth(name, config, paths)
    except StitchGeometryError as exc:
        print(f"{name}::ERROR::stitching geometry: {exc}")
        write_build_error(paths, name, item, wearer, rec, config, tag="gt_edges_creation", dump_every=args.dump_every)
        return
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise
    write_scene(cloth, paths, name, item, wearer, rec, config, dump_every=args.dump_every)


def _resolve_hold(args, kind: str) -> bool:
    if args.hold == "auto":
        return drape_mod.HOLD[kind]
    return args.hold == "on"


def _export_from_args(args) -> None:
    drape_mod.NECK.update(hold=args.neck_hold or "none", stiff=args.neck_stiff, dump=args.dump_every)
    drape_mod.ENGINE["name"] = "newton"
    args.out.mkdir(parents=True, exist_ok=True)
    if args.spec:
        if not args.name:
            raise SystemExit("--spec requires --name")
        props = _props_from_args(args, hold=args.hold == "on", material=args.material)
        _export_one(args.spec, args.name, args.wearer, args.out, props, args, item=args.name)
        return
    from drape import pattern as pattern_mod
    items = drape_mod.manifest_items(args.inputs)
    for it in items:
        if args.only and it["safe"] != args.only:
            continue
        kind = pattern_mod.slot_kind(it)
        pose = drape_mod.POSE[kind] if args.arm_pose is None else args.arm_pose
        hold = _resolve_hold(args, kind)
        spec_dir, name, sim_body = drape_mod.ensure_pattern(
            args.inputs, args.bodies, args.out, it["safe"], args.size,
            args.wearer, pose=pose, role=it.get("role"), base=args.base,
        )
        props = _props_from_args(args, hold=hold, material=it.get("material"))
        print(f"{it['safe']}: {kind}, body {sim_body}, neck {drape_mod.NECK['hold']}/{drape_mod.NECK['stiff'] or '-'}")
        _export_one(spec_dir, name, sim_body, args.out / it["safe"] / "sim", props, args, item=it["safe"])


def main() -> None:
    ap = argparse.ArgumentParser(description="freeze a Newton build to a portable scene file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    export_ap = sub.add_parser("export", help="run build and write <name>_scene.npz + .json")
    _add_build_args(export_ap)
    args = ap.parse_args()
    if args.cmd == "export":
        _export_from_args(args)


if __name__ == "__main__":
    main()
