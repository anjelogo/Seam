import argparse
import json
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

from drape._repo import bootstrap, GC, DRAPE

bootstrap()

import pygarment.data_config as data_config
import pygarment.meshgen.simulation as sim_mod
from pygarment.meshgen.boxmeshgen import BoxMesh
from pygarment.meshgen.sim_config import PathCofig

sim_mod.render_images = lambda *a, **k: None

from pygarment.meshgen import boxmeshgen as boxmeshgen_mod

# upstream warning at boxmeshgen.py:458 crashes on missing Edge.name
if not hasattr(boxmeshgen_mod.Edge, "name"):
    boxmeshgen_mod.Edge.name = "edge"

PRESET_FILES = {
    "soft_flexy": "soft_flexy_ochra 30s.json",
    "soft": "soft_ochra.json",
    "stiff": "stiff_ochra.json",
}
MATERIAL_PRESET = {
    "denim": "stiff", "canvas": "stiff", "leather": "stiff", "corduroy": "stiff",
    "fleece": "soft_flexy", "jersey": "soft_flexy", "cotton jersey": "soft_flexy", "knit": "soft_flexy",
    "cotton": "soft", "polyester": "soft", "wool": "soft", "nylon": "soft",
}


class VramSampler:
    def __init__(self):
        self.peak = None
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        if shutil.which("nvidia-smi"):
            self._thread = threading.Thread(target=self._poll, daemon=True)
            self._thread.start()
        return self

    def _poll(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip().splitlines()
                used = max(int(x) for x in out if x.strip())
                self.peak = used if self.peak is None else max(self.peak, used)
            except Exception:
                pass
            self._stop.wait(0.5)

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def load_props(res: float | None, max_steps: int | None, attachment: bool, material: str | None,
               frame_timeout: int | None):
    props = data_config.Properties(str(GC / "assets/Sim_props/default_sim_props.yaml"))
    props.set_section_stats("sim", fails={}, sim_time={}, spf={}, fin_frame={}, body_collisions={}, self_collisions={})
    props.set_section_stats("render", render_time={})
    cfg = props["sim"]["config"]
    if res is not None:
        cfg["resolution_scale"] = res
    if max_steps is not None:
        cfg["max_sim_steps"] = max_steps
    if not attachment:
        cfg["options"]["enable_attachment_constraint"] = False
    # upstream frame timeout no-ops on Darwin (platform name mismatch skips the frame entirely)
    cfg["max_frame_time"] = None if platform.system() == "Darwin" else frame_timeout or cfg.get("max_frame_time")
    preset = MATERIAL_PRESET.get((material or "").lower())
    if preset:
        try:
            raw = json.loads((GC / "assets/Sim_props" / PRESET_FILES[preset]).read_text())
            mat = raw.get("sim", {}).get("config", {}).get("material", raw.get("material", {}))
            cfg["material"].update(mat or {})
            print(f"material preset: {preset} ({material})")
        except Exception as e:
            print(f"material preset {preset} failed ({e}); using defaults")
    props["render"]["config"]["uv_texture"]["fabric_grain_texture_path"] = str(GC / "assets/img/fabric_texture.png")
    return props


def warp_device() -> str:
    import warp as wp

    return str(wp.get_device())


def drape_one(spec_dir: Path, name: str, wearer: str, out_dir: Path, props, timings: list, item: str = "",
              boxmesh_only: bool = False) -> Path:
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
    box = BoxMesh(paths.in_g_spec, props["sim"]["config"]["resolution_scale"])
    box.load()
    box.serialize(paths, store_panels=True, uv_config=props["render"]["config"]["uv_texture"])
    meshgen_s = round(time.time() - t0, 2)
    if boxmesh_only:
        print(f"BOXMESH {name}: {paths.g_box_mesh} ({meshgen_s}s, sim skipped)")
        timings.append({"item": item, "name": name, "body": wearer, "meshgen_s": meshgen_s, "sim_s": None,
                        "resolution_scale": props["sim"]["config"]["resolution_scale"], "boxmesh_only": True})
        return paths.g_box_mesh
    t1 = time.time()
    with VramSampler() as vram:
        sim_mod.run_sim(box.name, props, paths, save_v_norms=False, store_usd=False, optimize_storage=False, verbose=False)
    sim_s = round(time.time() - t1, 2)
    stats = props["sim"]["stats"]
    rec = {
        "item": item, "name": name, "body": wearer,
        "resolution_scale": props["sim"]["config"]["resolution_scale"],
        "meshgen_s": meshgen_s, "sim_s": sim_s,
        "spf": round(stats["spf"].get(box.name, 0), 3),
        "frames": stats["fin_frame"].get(box.name),
        "body_collisions": stats["body_collisions"].get(box.name),
        "self_collisions": stats["self_collisions"].get(box.name),
        "fails": {k: v for k, v in stats["fails"].items() if box.name in (v if isinstance(v, list) else [])},
        "vram_mb": vram.peak, "device": warp_device(),
    }
    timings.append(rec)
    print(f"DRAPE {name} on {wearer}: sim {sim_s}s, frames {rec['frames']}, fails {rec['fails'] or 'none'}")
    sim_obj = paths.g_sim
    if not sim_obj.exists():
        print(f"WARNING: {sim_obj} missing (sim failed)")
    return sim_obj


def pattern_dirs(out: Path, safe: str) -> list[Path]:
    base = out / safe / "pattern"
    if not base.exists():
        return []
    return sorted(p.parent for p in base.glob("*/*_specification.json"))


def manifest_items(inputs: Path) -> list[dict]:
    mf = inputs / "manifest.json"
    if mf.exists():
        return json.loads(mf.read_text()).get("items", [])
    out = []
    for d in sorted(inputs.iterdir()):
        if (d / "item.json").exists():
            item = json.loads((d / "item.json").read_text())
            tags = item.get("tags") or {}
            out.append({"safe": d.name, "role": tags.get("category"), "category": tags.get("category"),
                        "material": tags.get("material"), "size": tags.get("size_normalized")})
    return out


def find_by_role(items: list[dict], *roles: str) -> dict | None:
    for it in items:
        if (it.get("role") or "").lower() in roles or (it.get("category") or "").lower() in roles:
            return it
    return None


def save_timings(out: Path, timings: list):
    path = out / "timings.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    existing.extend(timings)
    path.write_text(json.dumps(existing, indent=2))
    print(f"timings -> {path}")


def ensure_pattern(inputs: Path, bodies: Path, out: Path, safe: str, size: str | None, wearer: str) -> tuple[Path, str]:
    from drape import pattern as pattern_mod

    items = pattern_mod.load_items(inputs, safe)
    if not items:
        raise SystemExit(f"item {safe} not found under {inputs}")
    entry = items[0]
    design = json.loads((entry["dir"] / "params.json").read_text())
    if "design" in design:
        design = design["design"]
    body_tag = pattern_mod.body_tag_for(entry["item"], size, bodies, wearer)
    name = f"{safe}__{body_tag}"
    spec = out / safe / "pattern" / name / f"{name}_specification.json"
    if not spec.exists():
        pattern_mod.build_pattern(safe, design, bodies / f"{body_tag}.yaml", out / safe / "pattern", name)
    return spec.parent, name


def experiment_sizes(args, props_kw: dict, timings: list):
    items = manifest_items(args.inputs)
    hoodie = find_by_role(items, "hoodie", "sweatshirt")
    if not hoodie:
        raise SystemExit("no hoodie/sweatshirt item in inputs")
    for size in ("XS", "M", "XL"):
        spec_dir, name = ensure_pattern(args.inputs, args.bodies, args.out, hoodie["safe"], size, args.wearer)
        props = load_props(**props_kw, material=hoodie.get("material"))
        drape_one(spec_dir, name, args.wearer, args.out / hoodie["safe"] / f"sim_size_{size}", props, timings,
                  hoodie["safe"], boxmesh_only=args.boxmesh_only)


def experiment_layers(args, props_kw: dict, timings: list):
    items = manifest_items(args.inputs)
    tee = find_by_role(items, "tee")
    hoodie = find_by_role(items, "hoodie", "sweatshirt")
    if not (tee and hoodie):
        raise SystemExit("layer test needs a tee and a hoodie in inputs")
    spec_dir, name = ensure_pattern(args.inputs, args.bodies, args.out, tee["safe"], None, args.wearer)
    props = load_props(**props_kw, material=tee.get("material"))
    tee_obj = drape_one(spec_dir, name, args.wearer, args.out / tee["safe"] / "sim_layer_base", props, timings, tee["safe"])
    if not tee_obj.exists():
        raise SystemExit("tee drape failed; cannot layer")

    import numpy as np
    import trimesh

    body = trimesh.load(args.bodies / f"{args.wearer}.obj", process=False)
    tee_m = trimesh.load(tee_obj, process=False)
    merged = trimesh.Trimesh(
        vertices=np.vstack([body.vertices, tee_m.vertices / 100.0]),
        faces=np.vstack([body.faces, tee_m.faces + len(body.vertices)]),
        process=False,
    )
    merged_name = f"{args.wearer}_plus_tee"
    merged.export(args.bodies / f"{merged_name}.obj")
    shutil.copy(args.bodies / f"{args.wearer}.yaml", args.bodies / f"{merged_name}.yaml")

    seg_path = args.bodies / "ggg_body_segmentation.json"
    backup = seg_path.read_text()
    seg = json.loads(backup)
    seg["body"] = list(seg["body"]) + list(range(len(body.vertices), len(merged.vertices)))
    try:
        seg_path.write_text(json.dumps(seg))
        spec_dir, name = ensure_pattern(args.inputs, args.bodies, args.out, hoodie["safe"], None, args.wearer)
        props = load_props(**props_kw, material=hoodie.get("material"))
        drape_one(spec_dir, name + "_layered", merged_name, args.out / hoodie["safe"] / "sim_layered", props, timings, hoodie["safe"])
    finally:
        seg_path.write_text(backup)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs")
    ap.add_argument("--bodies", type=Path, default=DRAPE / "runs/bodies")
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out")
    ap.add_argument("--wearer", default="wearer_masc")
    ap.add_argument("--only")
    ap.add_argument("--size")
    ap.add_argument("--res", type=float, default=None)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--no-attachment", action="store_true")
    ap.add_argument("--boxmesh-only", action="store_true")
    ap.add_argument("--frame-timeout", type=int, default=None)
    ap.add_argument("--material")
    ap.add_argument("--spec", type=Path, help="direct mode: folder containing <name>_specification.json")
    ap.add_argument("--name", help="direct mode: spec name")
    ap.add_argument("--experiment", choices=["sizes", "layers"])
    args = ap.parse_args()

    props_kw = dict(res=args.res, max_steps=args.max_steps, attachment=not args.no_attachment,
                    frame_timeout=args.frame_timeout)
    timings: list = []
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        if args.experiment == "sizes":
            experiment_sizes(args, props_kw, timings)
        elif args.experiment == "layers":
            experiment_layers(args, props_kw, timings)
        elif args.spec:
            if not args.name:
                raise SystemExit("--spec requires --name")
            props = load_props(**props_kw, material=args.material)
            drape_one(args.spec, args.name, args.wearer, args.out, props, timings, args.name, boxmesh_only=args.boxmesh_only)
        else:
            items = manifest_items(args.inputs)
            for it in items:
                if args.only and it["safe"] != args.only:
                    continue
                spec_dir, name = ensure_pattern(args.inputs, args.bodies, args.out, it["safe"], args.size, args.wearer)
                props = load_props(**props_kw, material=it.get("material"))
                drape_one(spec_dir, name, args.wearer, args.out / it["safe"] / "sim", props, timings, it["safe"],
                          boxmesh_only=args.boxmesh_only)
    finally:
        if timings:
            save_timings(args.out, timings)


if __name__ == "__main__":
    main()
