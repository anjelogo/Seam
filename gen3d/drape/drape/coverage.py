"""Shoulder-coverage gates for draped tops: is the shoulder cap actually covered, does the armhole sit on the arm root, do the sleeves and neckline land where the pattern cut them."""

import argparse
import json
from pathlib import Path
from typing import NoReturn

import numpy as np
import trimesh
import yaml
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from drape._repo import RUNS
from drape.bind import nearest_surface, signed_distance
from drape.collar import ARM_TAG, BODIES, SEG_FILE, SIDES, boundary_rings, item_meta, obj_mesh, pattern_neck, ring_metrics, to_cm
from drape.params import NECK_CM, SCOOP_SHAPES, VNECK_SHAPES, size_factor

GATES = json.loads((Path(__file__).parent / "gates.json").read_text())
V3_RUNS = (RUNS / "out_texture_v3", RUNS / "out_v3")
INPUT_DIRS = (RUNS / "inputs_texture", RUNS / "inputs")
PARTS = ("body", "left_arm", "right_arm")  # the shells that reach the shoulder; the legs never do
CAP_CM = 6.0  # cap radius around the acromion
ROOT_CM = 5.0  # how far down the arm root the cap reaches
SUNK_CM = 0.1  # how deep inside a neighbouring shell a vertex must sit to count as skin that is not there
PATCH_CM = 2.0  # a bare patch at least this wide is a hole, not tessellation noise
NECK_SLAB_CM = 1.0
BACK_NECK_CM = (1.5, 3.0)


def die(msg: str) -> NoReturn:
    raise SystemExit(f"coverage: {msg}")


def unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def body_parts(obj: Path) -> tuple[np.ndarray, dict[str, tuple[trimesh.Trimesh, np.ndarray]]]:
    """The mannequin ships trunk, arms and legs as separate closed shells, so each part is its own mesh."""
    if not obj.exists():
        die(f"{obj} missing")
    mesh = trimesh.load(obj, process=False, maintain_order=True)
    verts = to_cm(np.asarray(mesh.vertices), obj.name)
    faces = np.asarray(mesh.faces)
    seg = json.loads((BODIES / SEG_FILE).read_text())
    parts = {}
    for name in PARTS:
        keep = np.zeros(len(verts), bool)
        keep[np.asarray(seg[name], int)] = True
        idx = np.flatnonzero(keep)
        remap = np.full(len(verts), -1, int)
        remap[idx] = np.arange(len(idx))
        parts[name] = (trimesh.Trimesh(verts[idx], remap[faces[keep[faces].all(1)]], process=False), idx)
    return verts, parts


def arm_root(trunk: trimesh.Trimesh, arm: trimesh.Trimesh, what: str) -> np.ndarray:
    """The socket loop: arm verts outside the trunk that share an arm edge with one buried inside it."""
    inside = signed_distance(trunk.vertices, trunk.faces, arm.vertices) < 0
    ring = sorted({int(a if not inside[a] else b) for a, b in arm.edges_unique if inside[a] != inside[b]})
    if len(ring) < 12:
        die(f"{what}: arm root ring is {len(ring)} verts, not a ring")
    spread = arm.vertices[ring].max(0) - arm.vertices[ring].min(0)
    if min(spread[1], spread[2]) < 4.0:
        die(f"{what}: arm root ring spread {np.round(spread, 2)} is not a loop around the socket")
    return np.asarray(ring, int)


def neck_base(trunk: trimesh.Trimesh, acromion_y: float) -> tuple[float, np.ndarray]:
    """Walk slabs up from the shoulders; the neck starts where the trunk stops narrowing (shoulder slope ~3cm/cm, neck ~0.3)."""
    v = trunk.vertices
    ys = np.arange(acromion_y, acromion_y + 15.0, NECK_SLAB_CM)
    rad = np.array([np.hypot(s[:, 0], s[:, 2]).max() if len(s) else np.nan
                    for s in (v[(v[:, 1] >= y) & (v[:, 1] < y + NECK_SLAB_CM)] for y in ys)])
    drop = -np.diff(rad)
    hit = next((i for i, d in enumerate(drop) if np.isfinite(d) and d < 1.0), None)
    if hit is None:
        die("no neck base: the trunk never stops narrowing above the shoulders")
    base = float(ys[hit + 1])
    ring = np.flatnonzero((v[:, 1] >= base - 0.75) & (v[:, 1] < base + 0.75))
    if len(ring) < 12:
        die(f"neck base ring at y={base:.1f} is {len(ring)} verts, not a ring")
    return base, ring


def landmarks(obj: Path) -> dict:
    """Every landmark recomputed from this body mesh, so a reshaped mannequin moves the gates with it."""
    verts, parts = body_parts(obj)
    trunk, trunk_idx = parts["body"]
    owner = np.full(len(verts), -1, int)
    for i, (_, idx) in enumerate(parts.values()):
        owner[idx] = i
    out = {"body": obj.name, "verts": verts, "sides": {}}
    for side in SIDES:
        arm, arm_idx = parts[f"{side}_arm"]
        acro_local = int(arm.vertices[:, 1].argmax())
        acro = arm.vertices[acro_local]
        ring = arm_root(trunk, arm, f"{obj.name} {side}")
        ring_pts = arm.vertices[ring]
        axis = unit(ring_pts.mean(0) - acro)
        along = (verts[arm_idx] - acro) @ axis
        cand = np.union1d(np.flatnonzero(np.linalg.norm(verts - acro, axis=1) <= CAP_CM),
                          arm_idx[(along >= 0) & (along <= ROOT_CM)])
        cand = cand[owner[cand] >= 0]
        buried = np.zeros(len(cand), bool)
        for i, (mesh, _) in enumerate(parts.values()):
            sel = owner[cand] != i
            if sel.any():
                buried[sel] |= signed_distance(mesh.vertices, mesh.faces, verts[cand[sel]]) < -SUNK_CM
        cap = cand[~buried]
        if len(cap) < 50:
            die(f"{obj.name} {side}: cap region is {len(cap)} verts, too small to measure")
        out["sides"][side] = {"acromion": acro, "arm_axis": axis, "arm_root": ring_pts, "cap": cap,
                              "buried": int(buried.sum())}
    base_y, base_ring = neck_base(trunk, float(max(out["sides"][s]["acromion"][1] for s in SIDES)))
    out["neck_base_y"] = base_y
    out["neck_base_n"] = len(base_ring)
    out["neck_base_centroid"] = trunk.vertices[base_ring].mean(0)
    return out


def patches(pts: np.ndarray, mask: np.ndarray) -> list[np.ndarray]:
    """Contiguous groups by proximity, not mesh edges: the cap straddles the trunk and arm shells, which share none."""
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    pair = cKDTree(pts[idx]).query_pairs(PATCH_CM, output_type="ndarray")
    n, lab = connected_components(coo_matrix((np.ones(len(pair)), (pair[:, 0], pair[:, 1])),
                                             shape=(len(idx), len(idx))), directed=False)
    return sorted((pts[idx[lab == k]] for k in range(n)), key=len, reverse=True)


def spread(pts: np.ndarray) -> float:
    return float(np.linalg.norm(pts.max(0) - pts.min(0))) if len(pts) > 1 else 0.0


def cap_metrics(mark: dict, side: str, gverts: np.ndarray, gfaces: np.ndarray) -> dict:
    """Covered means garment surface within cover_dist_cm of that patch of skin.

    Cloth that close cannot be buried any deeper than cover_dist_cm, and sub-cm cloth-skin overlap is
    covered cloth, not cloth gone inside the body; gross penetration has its own gate.
    """
    cap = mark["sides"][side]["cap"]
    pts = mark["verts"][cap]
    close, _ = nearest_surface(gverts, gfaces, pts)
    dist = np.linalg.norm(close - pts, axis=1)
    covered = dist <= GATES["cover_dist_cm"]
    bare = patches(pts, ~covered)
    worn = patches(pts, covered)
    # a strap: cloth crosses the cap in a band no wider than strap_width_cm front to back while a >=2cm patch of skin stays bare beside it
    band = float(worn[0][:, 2].max() - worn[0][:, 2].min()) if worn else 0.0
    hole = spread(bare[0]) if bare else 0.0
    return {"cap_verts": len(cap), "coverage": round(float(covered.mean()), 4),
            "mean_gap_cm": round(float(dist.mean()), 2), "bare_patch_cm": round(hole, 2),
            "band_z_cm": round(band, 2), "covered": covered.tolist(),
            "strap": bool(covered.mean() >= 0.05 and hole >= PATCH_CM and band <= GATES["strap_width_cm"])}


def garment_rings(mesh: trimesh.Trimesh, acromion_x: float, what: str) -> tuple[tuple, dict]:
    """A top is cut open at the neck, the hem and the cuffs; the cuffs are the rings out past half the shoulder width."""
    rings = sorted(boundary_rings(mesh), key=lambda r: -float(np.asarray(mesh.vertices)[r[0], 1].mean()))
    if not rings:
        die(f"{what}: no open boundary, cannot find the neck ring")
    v = np.asarray(mesh.vertices)
    cuffs: dict[str, tuple] = {}
    for idx, length in rings[1:]:
        x = float(v[idx].mean(0)[0])
        if abs(x) < acromion_x / 2:
            continue
        side = "left" if x > 0 else "right"
        if side not in cuffs or abs(x) > abs(float(v[cuffs[side][0]].mean(0)[0])):
            cuffs[side] = (idx, length)
    return rings[0], cuffs


def grain_extent(panel: dict) -> float:
    bb, g = panel["bbox_cm"], panel["grain_axis"]
    return abs(g[0]) * (bb[2] - bb[0]) + abs(g[1]) * (bb[3] - bb[1])


def pattern_sleeve(panels: dict) -> dict[str, float | None]:
    """Sleeve length along the grain, plus the rib cuff band when the pattern stitches one on."""
    out: dict[str, float | None] = {}
    for side in SIDES:
        total = 0.0
        for kind in ("sleeve", "cuff"):
            ext = [grain_extent(p) for p in panels["panels"].values() if p["kind"] == kind and p["side"] == side]
            if ext:
                total += max(ext)
        out[side] = round(total, 2) if total else None
    return out


def neckline_kind(panels: dict, params: dict, category: str | None) -> str:
    """drape.params' own prior keys, read off the pattern instead of the model's schema."""
    if any(p["kind"] == "hood" for p in panels["panels"].values()) or (category or "").lower() == "hoodie":
        return "hoodie"
    shape = ((params.get("collar") or {}).get("f_collar") or {}).get("v")
    return "vneck" if shape in VNECK_SHAPES else "scoop" if shape in SCOOP_SHAPES else "crew"


def v3_sim_s(safe: str) -> tuple[float, str]:
    best, where = None, ""
    for run in V3_RUNS:
        path = run / "timings.json"
        if not path.exists():
            continue
        rows = json.loads(path.read_text())
        for r in rows:
            if r["item"] == safe and "_top_" in r["name"] and r.get("sim_s"):
                return float(r["sim_s"]), f"{run.name}:{safe}"
        tops = [float(r["sim_s"]) for r in rows if "_top_" in r["name"] and r.get("sim_s")]
        if tops and (best is None or max(tops) > best):
            best, where = max(tops), f"{run.name}:slowest top"
    if best is None:
        die(f"{safe}: no v3 top sim time to compare against")
    return best, where


def inputs_params(safe: str, inputs: Path | None) -> dict:
    for base in (inputs,) if inputs else INPUT_DIRS:
        path = base / safe / "params.json"
        if path.exists():
            return json.loads(path.read_text())
    return {}


def measure(out: Path, safe: str, inputs: Path | None, marks: dict) -> dict:
    panels = json.loads((out / safe / "panels.json").read_text())
    report_file = out / safe / "glb" / "bind_report.json"
    if not report_file.exists():
        die(f"{safe}: {report_file} missing")
    report = json.loads(report_file.read_text())
    sim_specs = sorted((out / safe / "sim").glob("*/*_specification.json"))
    if not sim_specs:
        die(f"{safe}: no sim spec under {out / safe / 'sim'}")
    sim_dir = sim_specs[0].parent
    sim_obj = sim_dir / f"{sim_dir.name}_sim.obj"
    posed_rel = (report.get("posed") or {}).get("obj") or ""
    posed = out / posed_rel
    if not sim_obj.exists() or not posed_rel or not posed.exists():
        die(f"{safe}: sim obj or posed obj missing")

    base = report.get("base") or "masc"
    tag = ARM_TAG.search(sim_dir.name)
    deg = float(tag.group(1)) if tag else 0.0
    meta = item_meta(safe, inputs)
    labels = yaml.safe_load((sim_dir / f"{sim_dir.name}_vertex_labels.yaml").read_text())
    pen = ((report.get("posed") or {}).get("penetration") or {}).get("pct")
    if pen is None:
        die(f"{safe}: bind_report.json has no penetration pct")
    sim_s = next((float(r["sim_s"]) for r in json.loads((out / "timings.json").read_text())
                  if r["item"] == safe and r.get("sim_s")), None)
    ref_s, ref_where = v3_sim_s(safe)
    kind = neckline_kind(panels, inputs_params(safe, inputs), meta["category"])
    scale = size_factor(meta["size"])
    neck = pattern_neck(panels)
    row = {"safe": safe, "spec": sim_dir.name, "arm_pose_deg": deg, **meta, "neckline": kind,
           "pattern_neck_cm": neck["cm"], "neck_edges": sorted(neck["edges"]),
           "pattern_sleeve_cm": pattern_sleeve(panels),
           "front_drop_band_cm": [round(NECK_CM[kind][0] * scale, 2), round(NECK_CM[kind][1] * scale, 2)],
           "back_drop_band_cm": list(BACK_NECK_CM),
           "penetration_pct": pen, "sim_s": sim_s, "v3_sim_s": ref_s, "v3_sim_ref": ref_where,
           "gates": {}, "poses": {}}

    for pose, (path, body) in {
        "sim": (sim_obj, BODIES / (f"wearer_{base}_a{deg:g}.obj" if deg else f"wearer_{base}.obj")),
        "web": (posed, BODIES / f"wearer_{base}.obj"),
    }.items():
        if body.name not in marks:
            marks[body.name] = landmarks(body)
        mark = marks[body.name]
        mesh = obj_mesh(path)
        gv, gf = np.asarray(mesh.vertices), np.asarray(mesh.faces)
        raw = to_cm(np.asarray(trimesh.load(path, process=False, maintain_order=True).vertices), path.name)
        neck, cuffs = garment_rings(mesh, float(abs(mark["sides"]["left"]["acromion"][0])), f"{safe} {pose}")
        ring = ring_metrics(gv[neck[0]], neck[1])
        ring["vs_pattern_pct"] = round(100.0 * (ring["circumference_cm"] - row["pattern_neck_cm"]) / row["pattern_neck_cm"], 2)
        sides = {}
        for side in SIDES:
            lm = mark["sides"][side]
            cap = cap_metrics(mark, side, gv, gf)
            label = labels.get(f"{side}_armhole") or []
            if not label:
                die(f"{safe}: no {side}_armhole vertex label")
            if max(label) >= len(raw):
                die(f"{safe} {pose}: {side}_armhole label index {max(label)} past {len(raw)} verts")
            gap = cKDTree(lm["arm_root"]).query(raw[np.asarray(label, int)])[0]
            want = row["pattern_sleeve_cm"][side]
            drop = None
            if side in cuffs:
                drop = round(float(np.linalg.norm(gv[cuffs[side][0]].mean(0) - lm["acromion"])), 2)
            sides[side] = {**cap, "armhole_max_cm": round(float(gap.max()), 2),
                           "armhole_mean_cm": round(float(gap.mean()), 2),
                           "sleeve_drop_cm": drop, "sleeve_err_cm": None if drop is None or want is None else round(drop - want, 2)}
        row["poses"][pose] = {
            "mesh": str(path.relative_to(out)), "body": body.name,
            "landmarks": {"acromion": {s: [round(float(c), 2) for c in mark["sides"][s]["acromion"]] for s in SIDES},
                          "arm_root_centroid": {s: [round(float(c), 2) for c in mark["sides"][s]["arm_root"].mean(0)] for s in SIDES},
                          "arm_root_verts": {s: len(mark["sides"][s]["arm_root"]) for s in SIDES},
                          "cap_verts": {s: len(mark["sides"][s]["cap"]) for s in SIDES},
                          "neck_base_y_cm": round(mark["neck_base_y"], 2),
                          "neck_base_verts": mark["neck_base_n"],
                          "neck_base_centroid": [round(float(c), 2) for c in mark["neck_base_centroid"]]},
            "neck_ring": ring, "sides": sides}
    row["gates"] = verdict(row)
    return row


def verdict(row: dict) -> dict:
    """Every gate as a pass/fail with the value that decided it."""
    g: dict[str, dict] = {}
    worst_cov = min(row["poses"][p]["sides"][s]["coverage"] for p in row["poses"] for s in SIDES)
    g["cap_coverage"] = {"value": round(worst_cov, 4), "limit": GATES["cap_coverage_min"],
                         "pass": worst_cov >= GATES["cap_coverage_min"]}
    strap = [f"{p}/{s}" for p in row["poses"] for s in SIDES if row["poses"][p]["sides"][s]["strap"]]
    g["strap"] = {"value": strap, "limit": GATES["strap_width_cm"], "pass": not strap}
    worst_arm = max(row["poses"][p]["sides"][s]["armhole_max_cm"] for p in row["poses"] for s in SIDES)
    g["armhole"] = {"value": worst_arm, "limit": GATES["armhole_dist_cm"], "pass": worst_arm <= GATES["armhole_dist_cm"]}

    errs = [row["poses"][p]["sides"][s]["sleeve_err_cm"] for p in row["poses"] for s in SIDES]
    if any(e is None for e in errs):
        g["sleeve_hem"] = {"value": None, "limit": GATES["sleeve_hem_tol_cm"], "pass": True,
                           "note": "no sleeve hem ring (sleeveless or a stitched-shut cuff)"}
        g["sleeve_lr"] = {"value": None, "limit": GATES["sleeve_dlr_cm"], "pass": True, "note": g["sleeve_hem"]["note"]}
    else:
        worst = max(abs(e) for e in errs)
        g["sleeve_hem"] = {"value": round(worst, 2), "limit": GATES["sleeve_hem_tol_cm"],
                           "pass": worst <= GATES["sleeve_hem_tol_cm"]}
        dlr = max(abs(row["poses"][p]["sides"]["left"]["sleeve_drop_cm"] - row["poses"][p]["sides"]["right"]["sleeve_drop_cm"])
                  for p in row["poses"])
        g["sleeve_lr"] = {"value": round(dlr, 2), "limit": GATES["sleeve_dlr_cm"], "pass": dlr < GATES["sleeve_dlr_cm"]}

    worst_ring = max(abs(row["poses"][p]["neck_ring"]["vs_pattern_pct"]) for p in row["poses"])
    g["neck_ring"] = {"value": round(worst_ring, 2), "limit": GATES["neck_ring_pct"],
                      "pass": worst_ring <= GATES["neck_ring_pct"]}
    lo, hi = row["front_drop_band_cm"]
    drops = [row["poses"][p]["neck_ring"]["front_drop_cm"] for p in row["poses"]]
    # a hood's face opening and a button-front's lapel edge are not what the neckline-depth prior describes
    skip = "hood_edge" in row["neck_edges"] or (row["category"] or "").lower() == "button_up"
    g["neck_drop"] = {"value": drops, "limit": [lo, hi],
                      "pass": skip or all(d is not None and lo <= d <= hi for d in drops)}
    if skip:
        g["neck_drop"]["note"] = "hood opening or shirt collar, not a crew neckline"
    g["penetration"] = {"value": row["penetration_pct"], "limit": GATES["pen_pct"],
                        "pass": row["penetration_pct"] <= GATES["pen_pct"]}
    budget = row["v3_sim_s"] * GATES["sim_time_x"]
    g["sim_time"] = {"value": row["sim_s"], "limit": round(budget, 2), "ref": row["v3_sim_ref"],
                     "pass": row["sim_s"] is None or row["sim_s"] <= budget}
    return g


def table(rows: list[dict]) -> None:
    head = ("safe", "cat", "size", "cov L/R sim", "cov L/R web", "bare cm", "band", "armhole", "sleeve err", "neck%", "drop", "pen%", "sim s")
    print(f"{head[0]:18s} {head[1]:9s} {head[2]:4s} {head[3]:>13s} {head[4]:>13s} {head[5]:>9s} {head[6]:>9s} "
          f"{head[7]:>8s} {head[8]:>12s} {head[9]:>7s} {head[10]:>11s} {head[11]:>6s} {head[12]:>11s}")
    for r in rows:
        def cov(p):
            s = r["poses"][p]["sides"]
            return f"{100 * s['left']['coverage']:5.1f}/{100 * s['right']['coverage']:5.1f}"

        def two(p, key, fmt="{:4.1f}"):
            s = r["poses"][p]["sides"]
            a, b = s["left"][key], s["right"][key]
            return "/".join("  n/a" if v is None else fmt.format(v) for v in (a, b))

        g = r["gates"]
        bad = [k for k, v in g.items() if not v["pass"]]
        print(f"{r['safe']:18s} {str(r['category']):9s} {str(r['size']):4s} {cov('sim'):>13s} {cov('web'):>13s} "
              f"{two('sim', 'bare_patch_cm'):>9s} {two('sim', 'band_z_cm'):>9s} {g['armhole']['value']:8.2f} "
              f"{two('sim', 'sleeve_err_cm', '{:+5.1f}'):>12s} {g['neck_ring']['value']:+7.1f} "
              f"{'/'.join('n/a' if d is None else f'{d:.1f}' for d in g['neck_drop']['value']):>11s} "
              f"{r['penetration_pct']:6.3f} {str(r['sim_s']):>5s}/{g['sim_time']['limit']:5.1f}"
              f"  {'PASS' if not bad else 'FAIL ' + ','.join(bad)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="shoulder-coverage gates for the tops in a drape run")
    ap.add_argument("--out", type=Path, required=True, help="a drape run directory, e.g. runs/out_tee_collar")
    ap.add_argument("--inputs", type=Path, default=None,
                    help=f"item.json directory (default: the first of {', '.join(d.name for d in INPUT_DIRS)} that has it)")
    ap.add_argument("--only", default=None, help="measure this safe id only")
    ap.add_argument("--json", type=Path, default=None, help="sidecar path (default: <out>/coverage_metrics.json)")
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

    marks: dict[str, dict] = {}
    rows = [measure(args.out, safe, args.inputs, marks) for safe in safes]
    table(rows)
    failed = {r["safe"]: [k for k, v in r["gates"].items() if not v["pass"]] for r in rows}
    failed = {k: v for k, v in failed.items() if v}
    sidecar = args.json or args.out / "coverage_metrics.json"
    sidecar.write_text(json.dumps({"out": str(args.out), "gates": GATES, "cap_cm": CAP_CM, "root_cm": ROOT_CM,
                                   "failed": failed, "items": rows}, indent=2, default=float) + "\n")
    print(f"\n{len(rows)} top{'s' if len(rows) != 1 else ''} -> {sidecar}")
    if failed:
        for safe, bad in failed.items():
            print(f"  FAIL {safe}: {', '.join(bad)}")
        raise SystemExit(f"coverage: {len(failed)} of {len(rows)} tops fail the shoulder gates")
    print("all gates pass")


if __name__ == "__main__":
    main()
