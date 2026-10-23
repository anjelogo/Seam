"""Read-only collar metrics for draped tops: shoulder height, neck ring vs pattern, neck drop, bind penetration."""

import argparse
import json
import re
import sys
from collections import defaultdict
from contextlib import redirect_stdout
from pathlib import Path
from typing import NoReturn

import numpy as np
import trimesh
import yaml

from drape._repo import RUNS

BODIES = RUNS / "bodies"
SEG_FILE = "ggg_body_segmentation.json"
INPUT_DIRS = (RUNS / "inputs_texture", RUNS / "inputs")
ARM_TAG = re.compile(r"_a(\d+(?:\.\d+)?)$")
BAND_CM = 2.0  # half-width of the column over the body's shoulder point the garment top is read in
SLIDE_CM = 0.5  # neck-ring centroid fall that counts as the collar sliding
NECK_SKIP = {"hem", "cuff"}  # free pattern edges that are not the neck opening
SIDES = ("left", "right")  # the mannequin's own left is +x


def die(msg: str) -> NoReturn:
    raise SystemExit(f"collar: {msg}")


def to_cm(verts: np.ndarray, what: str) -> np.ndarray:
    """Sim objs are cm, body objs and glbs metres; tell them apart by how tall the thing is."""
    span = float(verts[:, 1].max() - verts[:, 1].min())
    if span < 10.0:
        return verts * 100.0
    if span < 400.0:
        return verts
    die(f"{what}: vertical span {span:g} is neither metres nor cm")


def body_shoulders(obj: Path) -> dict[str, np.ndarray]:
    """The topmost vertex of each arm, as drape.body.measure() takes its shoulder point."""
    if not obj.exists():
        die(f"{obj} missing")
    seg = json.loads((BODIES / SEG_FILE).read_text())
    verts = to_cm(np.asarray(trimesh.load(obj, process=False, maintain_order=True).vertices), obj.name)
    out = {}
    for side in SIDES:
        idx = np.asarray(seg[f"{side}_arm"], int)
        out[side] = verts[idx][verts[idx][:, 1].argmax()]
    return out


def weld(verts: np.ndarray, faces: np.ndarray) -> trimesh.Trimesh:
    """Fuse the uv-seam duplicates (1 um), or they read as open boundaries and shred the neck ring."""
    _, first, inverse = np.unique(np.round(verts, 4), axis=0, return_index=True, return_inverse=True)
    return trimesh.Trimesh(verts[first], inverse.reshape(-1)[faces], process=False)


def obj_mesh(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(path, process=False, maintain_order=True)
    return weld(to_cm(np.asarray(mesh.vertices), path.name), np.asarray(mesh.faces))


def boundary_rings(mesh: trimesh.Trimesh) -> list[tuple[np.ndarray, float]]:
    """Each open-edge component with its length: a top is cut open at the neck, the hem and the cuffs."""
    count: dict[tuple[int, int], int] = defaultdict(int)
    for edge in mesh.edges_sorted:
        count[(int(edge[0]), int(edge[1]))] += 1
    edges = [e for e, n in count.items() if n == 1]
    adj: dict[int, list[int]] = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    group: dict[int, int] = {}
    for start in adj:
        if start in group:
            continue
        stack, gid = [start], len(set(group.values()))
        group[start] = gid
        while stack:
            cur = stack.pop()
            for nxt in adj[cur]:
                if nxt not in group:
                    group[nxt] = gid
                    stack.append(nxt)
    verts = np.asarray(mesh.vertices)
    members: dict[int, list[int]] = defaultdict(list)
    for v, gid in group.items():
        members[gid].append(v)
    lengths: dict[int, float] = defaultdict(float)
    for a, b in edges:
        lengths[group[a]] += float(np.linalg.norm(verts[a] - verts[b]))
    return [(np.asarray(sorted(m), int), lengths[gid]) for gid, m in members.items() if len(m) > 3]


def neck_ring(mesh: trimesh.Trimesh, what: str) -> tuple[np.ndarray, float]:
    rings = boundary_rings(mesh)
    if not rings:
        die(f"{what}: no open boundary, cannot find the neck ring")
    verts = np.asarray(mesh.vertices)
    idx, length = max(rings, key=lambda r: verts[r[0], 1].mean())
    return verts[idx], length


def ring_metrics(ring: np.ndarray, length: float) -> dict:
    top = float(ring[:, 1].max())
    front = ring[:, 2] > ring[:, 2].mean()
    return {
        "circumference_cm": round(length, 2),
        "top_cm": round(top, 2),
        "front_drop_cm": round(top - float(ring[front, 1].min()), 2) if front.any() else None,
        "back_drop_cm": round(top - float(ring[~front, 1].min()), 2) if (~front).any() else None,
        "n_verts": len(ring),
    }


def shoulder_heights(mesh: trimesh.Trimesh, shoulders: dict[str, np.ndarray], what: str) -> dict:
    """The garment's top in a 2*BAND_CM wide column standing over each of the body's shoulder points."""
    verts = np.asarray(mesh.vertices)
    out = {}
    for side in SIDES:
        point = shoulders[side]
        sign = 1.0 if side == "left" else -1.0
        band = (verts[:, 0] * sign > 0) & (np.abs(np.abs(verts[:, 0]) - abs(point[0])) < BAND_CM)
        if not band.any():
            die(f"{what}: no garment within {BAND_CM:g} cm of the {side} shoulder at x={point[0]:.2f}")
        height = float(verts[band, 1].max())
        out[side] = {"garment_cm": round(height, 2), "body_cm": round(float(point[1]), 2),
                     "error_cm": round(height - float(point[1]), 2)}
    return out


def pattern_neck(panels: dict) -> dict:
    """The neck opening the pattern cuts: the free (unstitched) edges that are not a hem or a cuff."""
    lengths: dict[str, float] = defaultdict(float)
    for panel in panels["panels"].values():
        for edge in panel["edges"]:
            if edge["stitch"] is None and edge["label"] not in NECK_SKIP:
                lengths[edge["label"]] += edge["length_cm"]
    if not lengths:
        die("no free neckline edges in panels.json")
    return {"cm": round(sum(lengths.values()), 2),
            "edges": {k: round(v, 3) for k, v in sorted(lengths.items())}}


def slide_frame(sim_dir: Path) -> int | None:
    """The first per-frame dump whose neck ring has fallen SLIDE_CM; None when the sim kept no frames."""
    where = next((d for d in (sim_dir, sim_dir.parent) if (d / "dump_faces.npy").exists()), None)
    if where is None:
        return None
    faces_file = where / "dump_faces.npy"
    dumps = sorted((p for p in where.glob("dump_f*.npy") if p != faces_file),
                   key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    if not dumps:
        return None
    faces = np.load(faces_file)
    first = None
    for dump in dumps:
        ring = neck_ring(weld(to_cm(np.load(dump), dump.name), faces), dump.name)[0]
        if first is None:
            first = ring[:, 1].mean()
        if first - ring[:, 1].mean() > SLIDE_CM:
            return int(re.sub(r"\D", "", dump.stem) or 0)
    return None


def material_preset(tag: str | None) -> str | None:
    """drape.drape's own lookup, so a preset rename there shows up here (its import prints a warp banner)."""
    with redirect_stdout(sys.stderr):
        from drape.drape import MATERIAL_PRESET
    return MATERIAL_PRESET.get((tag or "").lower().strip().replace("_", " "))


def item_meta(safe: str, inputs: Path | None) -> dict:
    for base in (inputs,) if inputs else INPUT_DIRS:
        path = base / safe / "item.json"
        if path.exists():
            tags = json.loads(path.read_text()).get("tags") or {}
            return {"inputs": str(base), "category": tags.get("category"),
                    "size": tags.get("size_normalized"), "material": tags.get("material")}
    die(f"{safe}: no item.json under {', '.join(str(b) for b in ((inputs,) if inputs else INPUT_DIRS))}")


def measure(out: Path, safe: str, inputs: Path | None) -> dict:
    panels_file = out / safe / "panels.json"
    if not panels_file.exists():
        die(f"{safe}: {panels_file} missing")
    panels = json.loads(panels_file.read_text())
    report_file = out / safe / "glb" / "bind_report.json"
    if not report_file.exists():
        die(f"{safe}: {report_file} missing")
    report = json.loads(report_file.read_text())

    sim_dirs = sorted((out / safe / "sim").glob("*/*_specification.json"))
    if not sim_dirs:
        die(f"{safe}: no sim spec under {out / safe / 'sim'}")
    sim_dir = sim_dirs[0].parent
    sim_obj = sim_dir / f"{sim_dir.name}_sim.obj"
    if not sim_obj.exists():
        die(f"{safe}: {sim_obj} missing")
    posed_rel = ((report.get("posed") or {}).get("obj") or "")
    bound = out / posed_rel  # bind's own web-pose mesh; the bound glb holds it as morph targets
    if not posed_rel or not bound.exists():
        die(f"{safe}: bind_report.json posed.obj {posed_rel or '(absent)'} missing")

    base = report.get("base") or "masc"
    tag = ARM_TAG.search(sim_dir.name)
    deg = float(tag.group(1)) if tag else 0.0
    meta = item_meta(safe, inputs)
    row = {"safe": safe, "spec": sim_dir.name, "arm_pose_deg": deg, "base": base, **meta,
           "pattern_neck": pattern_neck(panels),
           "material_preset": material_preset(meta["material"]),
           "penetration": {k: v for k, v in (report.get("posed") or {}).items() if "penetration" in k},
           "glb_vs_web_cm": (report.get("identity") or {}).get("blend_vs_original"),
           "labels": {k: len(v) for k, v in sorted(
               yaml.safe_load((sim_dir / f"{sim_dir.name}_vertex_labels.yaml").read_text()).items())}}
    if not row["penetration"]:
        die(f"{safe}: bind_report.json has no penetration fields")

    poses = {"sim": (sim_obj, BODIES / (f"wearer_{base}_a{deg:g}.obj" if deg else f"wearer_{base}.obj")),
             "web": (bound, BODIES / f"wearer_{base}.obj")}
    for name, (path, body) in poses.items():
        mesh = obj_mesh(path)
        ring, length = neck_ring(mesh, f"{safe} {name}")
        row[name] = {"mesh": str(path.relative_to(out)),
                     "body": body.name,
                     "shoulder": shoulder_heights(mesh, body_shoulders(body), f"{safe} {name}"),
                     "neck_ring": ring_metrics(ring, length)}
        row[name]["neck_ring"]["vs_pattern_cm"] = round(
            row[name]["neck_ring"]["circumference_cm"] - row["pattern_neck"]["cm"], 2)
    row["slide_frame"] = slide_frame(sim_dir)
    return row


def line(row: dict) -> str:
    def sh(pose):
        s = row[pose]["shoulder"]
        return (f"{s['left']['garment_cm']:6.1f}/{s['right']['garment_cm']:6.1f} "
                f"({s['left']['error_cm']:+5.1f}/{s['right']['error_cm']:+5.1f})")

    ring, pen = row["web"]["neck_ring"], row["penetration"].get("penetration") or {}
    return (f"{row['safe']:18s} {str(row['category']):11s} {str(row['size']):4s}"
            f" web {sh('web')}  sim {sh('sim')}"
            f"  neck {ring['circumference_cm']:6.1f} vs {row['pattern_neck']['cm']:6.1f}"
            f" ({ring['vs_pattern_cm']:+6.1f})"
            f"  drop f/b {ring['front_drop_cm']:5.1f}/{ring['back_drop_cm']:4.1f}"
            f"  slide {str(row['slide_frame'] if row['slide_frame'] is not None else 'n/a'):>4s}"
            f"  pen {pen.get('count', 0):4d} {pen.get('deepest_cm', 0.0):5.2f}cm"
            f"  {str(row['material']):26s} -> {str(row['material_preset']):8s}"
            f"  {' '.join(f'{k}={v}' for k, v in row['labels'].items())}")


def main() -> None:
    ap = argparse.ArgumentParser(description="collar and shoulder metrics for the tops in a drape run")
    ap.add_argument("--out", type=Path, required=True, help="a drape run directory, e.g. runs/out_texture_v3")
    ap.add_argument("--only", default=None, help="measure this safe id only")
    ap.add_argument("--inputs", type=Path, default=None,
                    help=f"item.json directory (default: the first of {', '.join(d.name for d in INPUT_DIRS)} that has it)")
    ap.add_argument("--json", type=Path, default=None, help="sidecar path (default: <out>/collar_metrics.json)")
    args = ap.parse_args()

    if not args.out.is_dir():
        die(f"{args.out} is not a directory")
    safes = [p.parent.name for p in sorted(args.out.glob("*/panels.json"))
             if json.loads(p.read_text()).get("garment") == "upper"]
    if args.only:
        if args.only not in safes:
            die(f"{args.only} is not a top in {args.out} (tops: {', '.join(safes) or 'none'})")
        safes = [args.only]
    if not safes:
        die(f"no tops in {args.out}")

    rows = [measure(args.out, safe, args.inputs) for safe in safes]
    for row in rows:
        print(line(row))
    sidecar = args.json or args.out / "collar_metrics.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({"out": str(args.out), "band_cm": BAND_CM, "items": rows}, indent=2) + "\n")
    print(f"\n{len(rows)} top{'s' if len(rows) != 1 else ''} -> {sidecar}")


if __name__ == "__main__":
    main()
