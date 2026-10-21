import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from drape._repo import bootstrap, GC, DRAPE

bootstrap()

TOP_SLOTS = {"top", "outer", "onepiece"}
# stress bottoms: narrow leg + taper, by manifest role
STRESS = {
    "legging": {"pants.width": 1.0, "pants.flare": 0.5},
    "pinstripe": {"pants.width": 1.05, "pants.flare": 0.65},
}


def slot_kind(tags: dict) -> str:
    """top or bottom. The category wins: taggers put joggers in slot 'outer'."""
    from drape.params import CATEGORY_SLOT

    cat = (tags.get("category") or "").lower()
    if cat in CATEGORY_SLOT:
        return "top" if CATEGORY_SLOT[cat] == "upper" else "bottom"
    return "top" if (tags.get("slot") or "top").lower() in TOP_SLOTS else "bottom"


def apply_stress(design: dict, role: str | None) -> str:
    """Narrow-leg overrides for the stress bottoms; returns the pattern-name suffix."""
    over = STRESS.get((role or "").lower())
    if not over:
        return ""
    for path, val in over.items():
        node = design
        *parents, last = path.split(".")
        for key in parents:
            node = node[key]
        node[last]["v"] = val
    print(f"stress {role}: " + ", ".join(f"{k}={v}" for k, v in over.items()))
    return "_stress"


def load_items(inputs: Path, only: str | None) -> list[dict]:
    items = []
    for d in sorted(inputs.iterdir()):
        if not (d / "item.json").exists():
            continue
        if only and d.name != only:
            continue
        item = json.loads((d / "item.json").read_text())
        items.append({"safe": d.name, "dir": d, "item": item})
    return items


def body_tag_for(item: dict, size: str | None, bodies: Path, wearer: str, pose: str = "") -> str:
    tags = item.get("tags") or {}
    size = size or tags.get("size_normalized")
    suffix = f"_{pose}" if pose else ""
    if not size:
        return wearer + suffix
    kind = slot_kind(tags)
    name = f"size_{kind}_{size}{suffix}"
    if not (bodies / f"{name}.yaml").exists():
        try:
            from drape.size_body import build as build_size_body

            build_size_body(wearer=wearer + suffix, slot=kind, size=size, name=name)
        except Exception as e:
            print(f"size body {name} unavailable ({e}); falling back to wearer body")
            return wearer + suffix
    return name


def build_pattern(safe: str, design: dict, body_yaml: Path, out_dir: Path, name: str) -> Path:
    from assets.bodies.body_params import BodyParameters
    from assets.garment_programs.meta_garment import MetaGarment

    body = BodyParameters(str(body_yaml))
    garment = MetaGarment(name, body, design)
    pattern = garment.assembly()
    if garment.is_self_intersecting():
        print(f"WARNING: {name} pattern is self-intersecting")
    out_dir.mkdir(parents=True, exist_ok=True)
    folder = Path(
        pattern.serialize(out_dir, tag="", to_subfolder=True, with_3d=False, with_text=False, view_ids=False)
    )
    shutil.copy(body_yaml, folder / f"{name}_body_measurements.yaml")
    return folder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs")
    ap.add_argument("--bodies", type=Path, default=DRAPE / "runs/bodies")
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out")
    ap.add_argument("--only")
    ap.add_argument("--size", help="override size (e.g. XS/M/XL for tops, W32 for bottoms)")
    ap.add_argument("--wearer", default="wearer_masc")
    args = ap.parse_args()

    items = load_items(args.inputs, args.only)
    if not items:
        sys.exit(f"no items with item.json under {args.inputs}")
    mf = args.inputs / "manifest.json"
    roles = {i["safe"]: i.get("role") for i in json.loads(mf.read_text()).get("items", [])} if mf.exists() else {}
    results = []
    for entry in items:
        safe, d, item = entry["safe"], entry["dir"], entry["item"]
        params_path = d / "params.json"
        if not params_path.exists():
            print(f"{safe}: no params.json yet, skipping")
            continue
        design = json.loads(params_path.read_text())
        if "design" in design:
            design = design["design"]
        stress = apply_stress(design, roles.get(safe))
        body_tag = body_tag_for(item, args.size, args.bodies, args.wearer)
        body_yaml = args.bodies / f"{body_tag}.yaml"
        if not body_yaml.exists():
            print(f"{safe}: body yaml {body_yaml} missing, skipping")
            continue
        name = f"{safe}__{body_tag}{stress}"
        t0 = time.time()
        folder = build_pattern(safe, design, body_yaml, args.out / safe / "pattern", name)
        secs = round(time.time() - t0, 2)
        spec = folder / f"{name}_specification.json"
        ok = spec.exists()
        print(f"{safe}: pattern on {body_tag} -> {folder} ({secs}s, spec={'ok' if ok else 'MISSING'})")
        results.append({"safe": safe, "name": name, "body": body_tag, "folder": str(folder), "seconds": secs, "spec_ok": ok})
    (args.out / "pattern_runs.json").parent.mkdir(parents=True, exist_ok=True)
    (args.out / "pattern_runs.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
