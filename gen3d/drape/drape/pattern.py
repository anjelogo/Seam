import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from drape._repo import bootstrap, DRAPE

bootstrap()

TOP_SLOTS = {"top", "outer", "onepiece"}
# a real rib neckband is cut shorter than the neck hole and stretched on; GarmentCode drafts it 1:1
NECKBAND_RATIO = 0.85


def _stretch_on_neckband() -> None:
    from assets.garment_programs import collars
    from assets.garment_programs.bands import StraightBandPanel

    turtle_init, band_init = collars.Turtle.__init__, StraightBandPanel.__init__

    def short_band(self, name, width, depth, match_int_proportion=None):
        band_init(self, name, width * NECKBAND_RATIO, depth, match_int_proportion)

    def turtle(self, tag, body, design):
        StraightBandPanel.__init__ = short_band
        try:
            turtle_init(self, tag, body, design)
        finally:
            StraightBandPanel.__init__ = band_init

    collars.Turtle.__init__ = turtle


_stretch_on_neckband()


def _ring_neckband(spec: dict) -> list[str]:
    """Turtle band halves are rectangles whose chords meet at CF as a notch; recut each as an arc of its neckline."""
    import numpy as np

    from drape.panels import edge_curve

    panels, notes = spec["pattern"]["panels"], []
    for stitch in spec["pattern"]["stitches"]:
        sides = [s for s in stitch if isinstance(s, dict)]
        names = [s["panel"] for s in sides]
        if not (any("collar" in n for n in names) and any("torso" in n for n in names)):
            continue
        torso = next(s for s in sides if "torso" in s["panel"])
        band = next(s for s in sides if "collar" in s["panel"])
        bp, tp = panels[band["panel"]], panels[torso["panel"]]
        if len(bp["edges"]) != 4 or any(e.get("curvature") for e in bp["edges"]):
            continue
        neck = tp["edges"][torso["edge"]].get("curvature") or {}
        if neck.get("type") != "circle":
            continue
        rad = float(neck["params"][0])
        arc = edge_curve(bp["edges"][band["edge"]], np.asarray(bp["vertices"], float))[1]
        verts = np.asarray(bp["vertices"], float)
        seam = bp["edges"][band["edge"]]["endpoints"]
        free = next(e["endpoints"] for i, e in enumerate(bp["edges"])
                    if not set(e["endpoints"]) & set(seam))
        depth = float(np.linalg.norm(verts[free[0]] - verts[seam[0]]))
        depth = min(depth, rad * 0.9)
        sweep = arc / rad
        if sweep >= np.pi or sweep <= 0:
            continue
        chord = 2 * rad * np.sin(sweep / 2)
        centre = np.array([chord / 2, np.sqrt(max(rad**2 - (chord / 2) ** 2, 0.0))])
        a, b = np.array([0.0, 0.0]), np.array([chord, 0.0])
        scale = (rad - depth) / rad
        sides = [set(e["endpoints"]) for e in bp["edges"]]
        verts[seam[0]], verts[seam[1]] = a, b
        for fv in free:
            sv = next(s for s in seam if {s, fv} in sides)
            verts[fv] = centre + (verts[sv] - centre) * scale
        bp["vertices"] = verts.tolist()
        bp["edges"][band["edge"]]["curvature"] = {"type": "circle", "params": [rad, 0, 1]}
        fi = next(i for i, e in enumerate(bp["edges"]) if e["endpoints"] == list(free))
        bp["edges"][fi]["curvature"] = {"type": "circle", "params": [rad - depth, 0, 0]}
        notes.append(f"{band['panel']} R{rad:.2f} sweep {np.degrees(sweep):.1f}deg")
    return notes


def band_vs_neckline(spec: dict) -> tuple[float, float]:
    """True arc lengths of the neckband edges and of the bodice neckline they are stitched to."""
    import numpy as np

    from drape.panels import edge_curve

    panels, band, neck = spec["pattern"]["panels"], 0.0, 0.0
    for stitch in spec["pattern"]["stitches"]:
        sides = [s for s in stitch if isinstance(s, dict)]
        names = [s["panel"] for s in sides]
        if not (any("collar" in n for n in names) and any("torso" in n for n in names)):
            continue
        for side in sides:
            p = panels[side["panel"]]
            length = edge_curve(p["edges"][side["edge"]], np.asarray(p["vertices"], float))[1]
            if "collar" in side["panel"]:
                band += length
            else:
                neck += length
    return band, neck
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
    band, neck = band_vs_neckline(pattern.spec if hasattr(pattern, "spec") else pattern())
    if band:
        print(f"neckband {name}: {band:.2f} cm on a {neck:.2f} cm neckline (band/neck {band / neck:.3f})")
    if garment.is_self_intersecting():
        print(f"WARNING: {name} pattern is self-intersecting")
    out_dir.mkdir(parents=True, exist_ok=True)
    folder = Path(
        pattern.serialize(out_dir, tag="", to_subfolder=True, with_3d=False, with_text=False, view_ids=False)
    )
    spec_path = folder / f"{name}_specification.json"
    if spec_path.exists():
        spec = json.loads(spec_path.read_text())
        notes = _ring_neckband(spec)
        if notes:
            spec_path.write_text(json.dumps(spec, indent=2))
            print(f"ring neckband {name}: " + ", ".join(notes))
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
