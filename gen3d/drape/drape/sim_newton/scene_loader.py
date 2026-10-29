from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import newton
import numpy as np
import warp as wp

from .attach import Attachments
from .body import BodyCollider
from .builder import Components, Ctx, SimParams
from .integrate import integrate
from .panel_drag import PanelDrag
from .self_contact import SelfContact
from .solver import Solver


class FrameTimeout(RuntimeError):
    pass


class SimTimeout(RuntimeError):
    pass


class SceneConfig:
    def __init__(self, sim: dict) -> None:
        self.sim_fps = float(sim["fps"])
        self.sim_substeps = int(sim["substeps"])
        self.zero_gravity_steps = int(sim["zero_gravity_steps"])
        self.max_sim_steps = int(sim["max_sim_steps"])
        self.min_sim_steps = int(sim["min_sim_steps"])
        self.max_sim_time = float(sim["max_sim_time"])
        self.max_frame_time = None if sim["max_frame_time"] is None else int(sim["max_frame_time"])
        self.static_threshold = float(sim["static_threshold"])
        self.non_static_percent = float(sim["non_static_percent"])
        self.max_body_collisions = int(sim["max_body_collisions"])
        self.max_self_collisions = int(sim["max_self_collisions"])
        d = sim["damping"]
        self.global_damping_factor = float(d[0])
        self.global_damping_effective_velocity = float(d[1])
        self.global_max_velocity = float(d[2])
        self.body_thickness = float(sim["body_thickness"])
        self.body_friction = float(sim["body_mu"])
        self.soft_contact_margin = float(sim["soft_contact_margin"])
        self.cloth_reference_margin = float(sim["cloth_reference_margin"])
        self.cloth_reference_k = 1.0e7  # §6.12 stored, never read
        self.particle_mu = float(sim["particle_mu"])
        self.particle_adhesion = float(sim["particle_adhesion"])
        enable = sim["enable"]
        self.enable_cloth_reference_drag = bool(enable["cloth_reference_drag"])
        self.enable_global_collision_filter = bool(enable["global_collision_filter"])
        self.enable_triangle_particle_collisions = bool(enable["triangle_particle_collisions"])
        self.enable_edge_edge_collisions = bool(enable["edge_edge_collisions"])
        self.enable_body_collision_filters = bool(enable["body_collision_filters"])
        self.enable_body_smoothing = bool(enable["body_smoothing"])
        self.enable_particle_particle_collisions = False
        self.enable_attachment_constraint = bool(sim["attachment_enabled"])
        self.ground = False
        self.attachment_frames = int(sim["attachment_frames"])


class SceneSmoother:
    def __init__(self, frames_arr, verts_arr) -> None:
        if frames_arr is None or len(frames_arr) == 0:
            self._frames: list[int] = []
            self._by_frame: dict[int, np.ndarray] = {}
            return
        self._frames = [int(f) for f in frames_arr]
        self._by_frame = {int(f): np.ascontiguousarray(verts_arr[i], dtype=np.float32) for i, f in enumerate(frames_arr)}

    @property
    def frames(self) -> list[int]:
        return list(self._frames)

    def verts_for_frame(self, frame: int):
        return self._by_frame.get(int(frame))


@dataclass
class _ClothStub:
    faces: np.ndarray
    body_verts: np.ndarray
    body_faces: np.ndarray


class Scene:
    def __init__(self, npz_path: Path) -> None:
        npz_path = Path(npz_path)
        self.path = npz_path
        with np.load(npz_path) as data:
            self.arrays = {k: np.asarray(data[k]) for k in data.files}
        json_path = npz_path.with_suffix(".json")
        self.meta = json.loads(json_path.read_text())
        self.sim = self.meta["sim"]


def _wp_copy_np(dst, arr, dtype):
    arr = np.ascontiguousarray(arr)
    if dtype is wp.vec3:
        src = wp.array(arr.reshape(-1, 3), dtype=wp.vec3, device=dst.device)
    elif dtype is wp.mat22:
        src = wp.array(arr.reshape(-1, 2, 2), dtype=wp.mat22, device=dst.device)
    elif dtype is wp.vec2i:
        src = wp.array(arr.reshape(-1, 2), dtype=wp.vec2i, device=dst.device)
    else:
        src = wp.array(arr, dtype=dtype, device=dst.device)
    wp.copy(dst, src)


def build_from_scene(scene: Scene, device: str | None = None) -> tuple[newton.Model, Ctx, Components, SceneConfig]:
    data = scene.arrays
    sim = scene.sim
    config = SceneConfig(sim)
    params = SimParams()

    x0 = data["x0"].astype(np.float32).reshape(-1, 3)
    v0 = data["v0"].astype(np.float32).reshape(-1, 3)
    mass = data["mass"].astype(np.float32)
    inv_mass = data["inv_mass"].astype(np.float32)
    radius = data["radius"].astype(np.float32)
    flags = data["flags"].astype(np.int32)
    faces = data["faces"].astype(np.int32).reshape(-1, 3)
    tri_ke = data["tri_ke"].astype(np.float32)
    tri_ka = data["tri_ka"].astype(np.float32)
    tri_kd = data["tri_kd"].astype(np.float32)
    tri_pose = data["tri_rest_pose"].astype(np.float32).reshape(-1, 2, 2)
    tri_area = data["tri_rest_area"].astype(np.float32)
    springs = data["springs"].astype(np.int32).reshape(-1, 2) if data["springs"].size else np.zeros((0, 2), dtype=np.int32)
    spring_rest = data["spring_rest"].astype(np.float32)
    spring_ke = data["spring_ke"].astype(np.float32)
    spring_kd = data["spring_kd"].astype(np.float32)
    bend = data["bend"].astype(np.int32).reshape(-1, 4) if data["bend"].size else np.zeros((0, 4), dtype=np.int32)
    bend_rest = data["bend_rest"].astype(np.float32)
    bend_ke = data["bend_ke"].astype(np.float32)
    bend_kd = data["bend_kd"].astype(np.float32)
    body_v = np.ascontiguousarray(data["body_v"], dtype=np.float32).reshape(-1, 3)
    body_f = np.ascontiguousarray(data["body_f"], dtype=np.int32).reshape(-1, 3)

    V, F = len(x0), len(faces)
    S, E = len(springs), len(bend)

    builder = newton.ModelBuilder(up_axis=newton.Axis.Y, gravity=(0.0, 0.0, 0.0))
    for i in range(V):
        builder.add_particle(
            pos=(float(x0[i, 0]), float(x0[i, 1]), float(x0[i, 2])),
            vel=(0.0, 0.0, 0.0),
            mass=float(mass[i]),
            radius=float(radius[i]),
        )

    builder.add_triangles(
        faces[:, 0].tolist(), faces[:, 1].tolist(), faces[:, 2].tolist(),
        tri_ke=tri_ke.tolist(), tri_ka=tri_ka.tolist(), tri_kd=tri_kd.tolist(),
        tri_drag=[0.0] * F, tri_lift=[0.0] * F,
    )
    for i in range(F):
        builder.tri_poses[i] = tri_pose[i].tolist()
        builder.tri_areas[i] = float(tri_area[i])

    if E:
        builder.add_edges(
            bend[:, 0].tolist(), bend[:, 1].tolist(), bend[:, 2].tolist(), bend[:, 3].tolist(),
            rest=bend_rest.tolist(),
            edge_ke=bend_ke.tolist(), edge_kd=bend_kd.tolist(),
        )

    for i in range(S):
        builder.add_spring(
            int(springs[i, 0]), int(springs[i, 1]),
            float(spring_ke[i]), float(spring_kd[i]), float(spring_rest[i]),
        )

    body_mesh = newton.Mesh(body_v, body_f.reshape(-1), compute_inertia=False, is_solid=False)
    shape_cfg = newton.ModelBuilder.ShapeConfig(mu=config.body_friction, margin=config.body_thickness)
    shape_index = builder.add_shape_mesh(
        -1, xform=wp.transform_identity(), mesh=body_mesh, scale=(1.0, 1.0, 1.0), cfg=shape_cfg,
    )
    if shape_index != params.whole_body_shape_index:
        raise RuntimeError(f"body collider landed at shape {shape_index}")

    model = builder.finalize(device)
    model.particle_max_velocity = float(config.global_max_velocity)
    model.particle_mu = float(config.particle_mu)
    model.particle_adhesion = float(config.particle_adhesion)

    tri_mat = np.zeros((F, 5), dtype=np.float32)
    tri_mat[:, 0] = tri_ke
    tri_mat[:, 1] = tri_ka
    tri_mat[:, 2] = tri_kd
    bend_props = np.stack([bend_ke, bend_kd], axis=1) if E else np.zeros((0, 2), dtype=np.float32)

    _wp_copy_np(model.particle_q, x0, wp.vec3)
    _wp_copy_np(model.particle_qd, v0, wp.vec3)
    _wp_copy_np(model.particle_mass, mass, wp.float32)
    _wp_copy_np(model.particle_inv_mass, inv_mass, wp.float32)
    _wp_copy_np(model.particle_radius, radius, wp.float32)
    _wp_copy_np(model.particle_flags, flags, wp.int32)
    if S:
        _wp_copy_np(model.spring_indices, springs.reshape(-1), wp.int32)
        _wp_copy_np(model.spring_rest_length, spring_rest, wp.float32)
        _wp_copy_np(model.spring_stiffness, spring_ke, wp.float32)
        _wp_copy_np(model.spring_damping, spring_kd, wp.float32)
    if E:
        _wp_copy_np(model.edge_indices, bend, wp.int32)
        _wp_copy_np(model.edge_rest_angle, bend_rest, wp.float32)
        _wp_copy_np(model.edge_bending_properties, bend_props, wp.float32)
    _wp_copy_np(model.tri_materials, tri_mat, wp.float32)
    _wp_copy_np(model.tri_poses, tri_pose, wp.mat22)
    _wp_copy_np(model.tri_areas, tri_area, wp.float32)

    cloth = _ClothStub(faces=faces, body_verts=body_v, body_faces=body_f)
    ctx = Ctx(model, cloth, config, params)
    ctx.body_mesh = body_mesh.mesh
    wp.copy(ctx.state_in.particle_q, model.particle_q)
    wp.copy(ctx.state_in.particle_qd, model.particle_qd)

    face_filters = np.ascontiguousarray(data["face_filters"], dtype=np.uint8)
    if face_filters.size:
        ctx.face_filters = wp.array(face_filters, dtype=wp.uint8, device=model.device)
    ctx.particle_filter_id = wp.array(np.ascontiguousarray(data["particle_filter_id"], dtype=np.int32), dtype=wp.int32, device=model.device)
    ctx.ref_label = wp.array(np.ascontiguousarray(data["ref_label"], dtype=np.int32), dtype=wp.int32, device=model.device)
    pairs = np.ascontiguousarray(data["allow_pairs"], dtype=np.int32).reshape(-1, 2) if data["allow_pairs"].size else np.zeros((0, 2), dtype=np.int32)
    if len(pairs):
        ctx.allow_pairs = wp.array(pairs, dtype=wp.vec2i, device=model.device)
        ctx.n_pairs = len(pairs)
    else:
        ctx.allow_pairs = wp.zeros(0, dtype=wp.vec2i, device=model.device)
        ctx.n_pairs = 0

    ref_v_off = data["ref_v_off"].astype(np.int32)
    ref_f_off = data["ref_f_off"].astype(np.int32)
    ref_v_all = np.ascontiguousarray(data["ref_v"], dtype=np.float32).reshape(-1, 3)
    ref_f_all = np.ascontiguousarray(data["ref_f"], dtype=np.int32).reshape(-1, 3)
    ids: list[int] = []
    ctx.ref_meshes = []
    for r in range(len(ref_v_off) - 1):
        sub_v = ref_v_all[int(ref_v_off[r]): int(ref_v_off[r + 1])]
        sub_f = ref_f_all[int(ref_f_off[r]): int(ref_f_off[r + 1])]
        mesh = wp.Mesh(
            points=wp.array(np.ascontiguousarray(sub_v, dtype=np.float32), dtype=wp.vec3, device=model.device),
            indices=wp.array(np.ascontiguousarray(sub_f.reshape(-1), dtype=np.int32), dtype=wp.int32, device=model.device),
        )
        ctx.ref_meshes.append(mesh)
        ids.append(mesh.id)
    if ids:
        ctx.ref_mesh_ids = wp.array(np.asarray(ids, dtype=np.uint64), dtype=wp.uint64, device=model.device)
    else:
        ctx.ref_mesh_ids = wp.zeros(0, dtype=wp.uint64, device=model.device)

    attach = Attachments()
    attach._ctx = ctx  # the kernel reads uploads via attach.solve; sidestep the Python staging
    att_particle = np.ascontiguousarray(data["att_particle"], dtype=np.int32)
    att_point = np.ascontiguousarray(data["att_point"], dtype=np.float32).reshape(-1, 3)
    att_normal = np.ascontiguousarray(data["att_normal"], dtype=np.float32).reshape(-1, 3)
    att_ke = np.ascontiguousarray(data["att_ke"], dtype=np.float32)
    att_kd = np.ascontiguousarray(data["att_kd"], dtype=np.float32)
    n_att = len(att_particle)
    attach._particles = att_particle.tolist()
    attach._points = [tuple(p) for p in att_point.tolist()]
    attach._normals = [tuple(n) for n in att_normal.tolist()]
    attach._stiffness = att_ke.tolist()
    attach._damping = att_kd.tolist()
    if n_att:
        ctx.att_particle = wp.array(att_particle, dtype=wp.int32, device=model.device)
        ctx.att_point = wp.array(att_point, dtype=wp.vec3, device=model.device)
        ctx.att_normal = wp.array(att_normal, dtype=wp.vec3, device=model.device)
        ctx.att_stiffness = wp.array(att_ke, dtype=wp.float32, device=model.device)
        ctx.att_damping = wp.array(att_kd, dtype=wp.float32, device=model.device)
        ctx.att_lambda = wp.array(np.zeros(n_att, dtype=np.float32), dtype=wp.float32, device=model.device)

    smoother = None
    if "smooth_frames" in data and len(data["smooth_frames"]):
        smoother = SceneSmoother(data["smooth_frames"], data["smooth_verts"])

    body_collider = BodyCollider(ctx, body_mesh, config.body_thickness, config.soft_contact_margin)
    self_contact = SelfContact(ctx, params)
    drag = PanelDrag(ctx, params, config.cloth_reference_margin, k=config.cloth_reference_k)
    components = Components(
        body=body_collider, self_contact=self_contact, attach=attach, drag=drag,
        integrate=integrate, smoother=smoother,
    )
    return model, ctx, components, config


def _dump_frame(out_el: Path, frame: int, verts: np.ndarray, faces: np.ndarray) -> None:
    out_el.mkdir(parents=True, exist_ok=True)
    if not (out_el / "dump_faces.npy").exists():
        np.save(out_el / "dump_faces.npy", np.ascontiguousarray(faces, dtype=np.int32))
    np.save(out_el / f"dump_f{frame:05d}.npy", np.ascontiguousarray(verts, dtype=np.float32))


def _is_static(last: np.ndarray | None, current: np.ndarray, threshold: float, non_static_percent: float) -> tuple[bool, int]:
    if last is None:
        return False, len(current)
    diff = np.sum(np.abs(current - last), axis=1)
    non_static = int((diff > threshold).sum())
    if non_static == 0 or non_static < len(current) * 0.01 * non_static_percent:
        return True, non_static
    return False, non_static


def _record_fail(fails: dict, tag: str, name: str) -> None:
    names = fails.setdefault(tag, [])
    if name not in names:
        names.append(name)


def _write_sim_obj(boxmesh_bytes: np.ndarray, verts: np.ndarray, out_path: Path) -> None:
    text = boxmesh_bytes.tobytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    v_idx = 0
    for line in lines:
        if line.startswith("v "):
            p = verts[v_idx]
            out.append(f"v {p[0]} {p[1]} {p[2]}\n")
            v_idx += 1
        else:
            out.append(line)
    out_path.write_text("".join(out))


def run_scene(
    scene_path: Path,
    out_dir: Path,
    max_steps: int | None = None,
    dump_every: int | None = None,
    verbose: bool = False,
    device: str | None = None,
) -> dict:
    scene = Scene(Path(scene_path))
    name = scene.meta["name"]
    out_dir = Path(out_dir)
    out_el = out_dir / name
    out_el.mkdir(parents=True, exist_ok=True)

    if scene.meta.get("build_error"):
        tag = scene.meta["build_error"]
        print(f"{name}::ERROR::build error in scene: {tag}")
        rec = {
            "sim_s": 0.0, "spf": 0.0, "frames": -1,
            "body_collisions": None, "self_collisions": None,
            "fails": {tag: [name]}, "vram_mb": None, "device": "cpu",
            "overflow": {"soft_contact": 0, "point_triangle": 0, "edge_edge": 0}, "nans": 0,
            **scene.meta.get("record", {}),
        }
        (out_el / "sim_record.json").write_text(json.dumps(rec, indent=2))
        return rec

    model, ctx, components, config = build_from_scene(scene, device=device)
    if max_steps is not None:
        config.max_sim_steps = int(max_steps)
    if dump_every is not None:
        scene.sim["dump_every"] = int(dump_every)
    params = SimParams()
    solver = Solver(ctx, components, config, params)

    faces_for_dump = scene.arrays["faces"].reshape(-1, 3)
    boxmesh_bytes = scene.arrays["boxmesh_obj"]

    current = solver.positions()
    last = None
    frame = -1
    start = time.time()
    success = False
    fails: dict = {}
    body_coll = 0
    self_coll = 0

    try:
        for frame in range(config.max_sim_steps):
            frame_start = time.time()
            solver.step_frame(frame)
            dropped = solver.read_overflow()
            if dropped:
                print(f"frame {frame}: contact buffer overflow, elements dropped {dropped}")
            last = current
            current = solver.positions()
            if dump_every and frame >= 0 and frame % int(dump_every) == 0:
                _dump_frame(out_dir, frame, current, faces_for_dump)
            if config.max_frame_time is not None:
                budget = config.max_frame_time * 2 if frame == 0 else config.max_frame_time
                if time.time() - frame_start > budget:
                    raise FrameTimeout(f"frame {frame} took longer than {budget}s")
            if time.time() - start > config.max_sim_time:
                raise SimTimeout(f"sim exceeded {config.max_sim_time}s at frame {frame}")
            if frame >= config.zero_gravity_steps and frame >= config.min_sim_steps:
                static, non_static = _is_static(last, current, config.static_threshold, config.non_static_percent)
                if verbose:
                    print(f"frame {frame}: {non_static} non-static")
                if static:
                    print(f"\nStatic with {non_static} non-static vertices out of {len(current)}")
                    break
        success = True
    except KeyboardInterrupt:
        raise
    except FrameTimeout as exc:
        print(f"{name}::ERROR::{exc}")
        _record_fail(fails, "frame_timeout", name)
    except SimTimeout as exc:
        print(f"{name}::ERROR::{exc}")
        _record_fail(fails, "simulation_timeout", name)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        _record_fail(fails, "crashes", name)

    sim_s = round(time.time() - start, 3)
    spf = round(sim_s / frame, 3) if frame else sim_s

    if success:
        body_coll = solver.count_body_intersections()
        self_coll = solver.count_self_intersections()
        print(f"{name}: {body_coll} body intersections")
        if frame == config.max_sim_steps - 1:
            _record_fail(fails, "static_equilibrium", name)
            print(f"{name}: ran the full frame budget")
        if sim_s < 0.5:
            _record_fail(fails, "fast_finish", name)
        if body_coll > config.max_body_collisions:
            _record_fail(fails, "cloth_body_intersection", name)
        if self_coll > config.max_self_collisions:
            _record_fail(fails, "cloth_self_intersection", name)

    _write_sim_obj(boxmesh_bytes, current, out_el / f"{name}_sim.obj")

    nans = int(np.isnan(current).any(axis=1).sum())
    overflow = dict(solver._overflow)
    rec = {
        "sim_s": sim_s, "spf": spf, "frames": frame,
        "body_collisions": int(body_coll), "self_collisions": int(self_coll),
        "fails": fails, "vram_mb": None, "device": str(model.device),
        "overflow": overflow, "nans": nans,
        **scene.meta.get("record", {}),
    }
    (out_el / "sim_record.json").write_text(json.dumps(rec, indent=2))
    print(f"SCENE {name}: sim {sim_s}s, frames {frame}, fails {fails or 'none'}")
    return rec
