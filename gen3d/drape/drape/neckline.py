"""Measures the crew neckline: pattern-space CF tangents and band rest curvature, sim-space CF kink."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from drape._repo import DRAPE, bootstrap

bootstrap()

from drape.panels import edge_curve, find_spec, item_specs  # noqa: E402


def _neck_stitches(spec: dict) -> list[tuple[str, int, str, int]]:
    """(torso panel, torso edge, band panel, band edge) for every band-to-bodice seam."""
    out = []
    for stitch in spec["pattern"]["stitches"]:
        sides = [s for s in stitch if isinstance(s, dict)]
        names = [s["panel"] for s in sides]
        if not (any("collar" in n for n in names) and any("torso" in n for n in names)):
            continue
        torso = next(s for s in sides if "torso" in s["panel"])
        band = next(s for s in sides if "collar" in s["panel"])
        out.append((torso["panel"], torso["edge"], band["panel"], band["edge"]))
    return out


def _arc(edge: dict, verts: np.ndarray) -> dict:
    """Polyline, length, chord, sweep angle and radius of one spec edge."""
    pts, length = edge_curve(edge, verts)
    chord = float(np.linalg.norm(pts[-1] - pts[0]))
    curv = edge.get("curvature") or {}
    rad = float(curv["params"][0]) if curv.get("type") == "circle" else float("inf")
    sweep = float(np.degrees(length / rad)) if np.isfinite(rad) and rad > 0 else 0.0
    return {"pts": pts, "length": length, "chord": chord, "radius": rad, "sweep": sweep}


def _cf_first(pts: np.ndarray) -> np.ndarray:
    """The polyline oriented so index 0 is the centre-front/back end (the one nearest the CF line x=0)."""
    return pts if abs(pts[0][0]) <= abs(pts[-1][0]) else pts[::-1]


def _tangent_deg(pts: np.ndarray) -> float:
    """Degrees off horizontal of the polyline tangent at index 0; horizontal is perpendicular to CF."""
    step = pts[min(3, len(pts) - 1)] - pts[0]
    ang = np.degrees(np.arctan2(abs(step[1]), abs(step[0])))
    return float(ang)


def pattern_metrics(spec_path: Path) -> list[dict]:
    """Per bodice-to-band seam: neckline CF tangent, sweep and radius against the band's rest shape."""
    spec = json.loads(spec_path.read_text())
    panels = spec["pattern"]["panels"]
    rows = []
    for tname, tedge, bname, bedge in _neck_stitches(spec):
        tp, bp = panels[tname], panels[bname]
        neck = _arc(tp["edges"][tedge], np.asarray(tp["vertices"], float))
        band = _arc(bp["edges"][bedge], np.asarray(bp["vertices"], float))
        pts = _cf_first(neck["pts"])
        rows.append({
            "torso": tname, "band": bname,
            "side": "front" if "ftorso" in tname else "back",
            "cf_tangent_deg": _tangent_deg(pts),
            "neck_len": neck["length"], "neck_radius": neck["radius"], "neck_sweep": neck["sweep"],
            "band_len": band["length"], "band_radius": band["radius"], "band_sweep": band["sweep"],
            "ratio": band["length"] / neck["length"] if neck["length"] else 0.0,
            # half the sweep the stretched-on band fails to carry: its CF tangent's miss from round
            "band_cf_miss_deg": abs(neck["sweep"] - np.degrees(neck["length"] / band["radius"])) / 2.0,
        })
    return rows


def _collar_rim(obj_path: Path) -> np.ndarray | None:
    """Top-down (x, z) of the draped collar band's free rim, ordered around the neck."""
    from collections import defaultdict

    from drape.texture import load_obj

    seg = obj_path.parent / f"{obj_path.stem.replace('_sim', '')}_sim_segmentation.txt"
    if not seg.exists():
        return None
    labels = seg.read_text().splitlines()
    verts, _, fv, _ = load_obj(obj_path)
    verts = np.asarray(verts, float)
    if len(labels) < len(verts):
        return None
    collar = {i for i, lab in enumerate(labels[:len(verts)]) if "collar" in lab}
    count: dict[tuple[int, int], int] = defaultdict(int)
    for f in fv:
        f = [int(x) for x in f]
        for a, b in zip(f, f[1:] + f[:1]):
            count[(min(a, b), max(a, b))] += 1
    rim = sorted({v for (a, b), c in count.items() if c == 1 for v in (a, b)} & collar)
    if len(rim) < 24:
        return None
    pts = verts[rim][:, [0, 2]]
    # a rim around the neck is star-shaped about its centroid, so an angular sort orders it safely
    ang = np.arctan2(pts[:, 1] - pts[:, 1].mean(), pts[:, 0] - pts[:, 0].mean())
    return pts[np.argsort(ang)]


def sim_metrics(obj_path: Path) -> dict:
    """Turning angle at the draped collar rim's centre front, against the rest of the rim."""
    ring = _collar_rim(obj_path)
    if ring is None:
        return {}
    n = 72
    seg = np.linalg.norm(np.diff(np.vstack([ring, ring[:1]]), axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    even = np.stack([np.interp(np.linspace(0, arc[-1], n, endpoint=False), arc,
                               np.concatenate([ring[:, k], ring[:1, k]])) for k in (0, 1)], axis=1)
    turn = np.zeros(n)
    for i in range(n):
        u = even[i] - even[(i - 1) % n]
        v = even[(i + 1) % n] - even[i]
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        if nu > 1e-9 and nv > 1e-9:
            turn[i] = np.degrees(np.arccos(np.clip(float(np.dot(u, v) / (nu * nv)), -1, 1)))
    cf = int(np.argmax(even[:, 1]))
    win = [(cf + k) % n for k in (-2, -1, 0, 1, 2)]
    sharp = int(np.argmax(turn))
    return {
        "cf_turn_deg": float(np.max(turn[win])),
        "max_turn_deg": float(np.max(turn)),
        "median_turn_deg": float(np.median(turn)),
        "cf_is_sharpest": bool(min(abs(sharp - cf), n - abs(sharp - cf)) <= 2),
        "rim_points": int(len(ring)),
    }


def plot(spec_path: Path, rows: list[dict], png: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    spec = json.loads(spec_path.read_text())
    panels = spec["pattern"]["panels"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for ax, side in zip(axes, ("front", "back")):
        ax.set_title(f"{side} half-neckline + band ({png.stem})", fontsize=9)
        ax.axvline(0, color="#bbb", lw=1, ls="--")
        for row in [r for r in rows if r["side"] == side and "right" in r["torso"]]:
            tp, bp = panels[row["torso"]], panels[row["band"]]
            tedge, bedge = next((te, be) for t, te, b, be in _neck_stitches(spec)
                                if t == row["torso"] and b == row["band"])
            npts = _cf_first(edge_curve(tp["edges"][tedge], np.asarray(tp["vertices"], float))[0])
            ax.plot(npts[:, 0], npts[:, 1], color="#c060ff", lw=2.5, label="torso neckline")
            ax.plot(npts[0, 0], npts[0, 1], "o", color="#4363d8", ms=6)
            tan = npts[min(3, len(npts) - 1)] - npts[0]
            tan = tan / (np.linalg.norm(tan) or 1) * 6
            ax.annotate("", xy=npts[0] + tan, xytext=npts[0],
                        arrowprops=dict(arrowstyle="->", color="#4363d8", lw=2))
            ax.text(npts[0, 0], npts[0, 1] - 2.0, f"CF tangent {row['cf_tangent_deg']:.1f}\u00b0 off horiz",
                    fontsize=8, color="#4363d8", ha="center")
            bpts = edge_curve(bp["edges"][bedge], np.asarray(bp["vertices"], float))[0]
            shift = npts[0] - _cf_first(bpts)[0]
            bp_s = bpts + shift
            ax.plot(bp_s[:, 0], bp_s[:, 1], color="#b07000", lw=2.5, label="band seam edge")
            ax.text(float(np.mean(bp_s[:, 0])), float(np.mean(bp_s[:, 1])) - 4.0,
                    f"band R={row['band_radius']:.1f} sweep {row['band_sweep']:.0f}\u00b0\n"
                    f"neck R={row['neck_radius']:.1f} sweep {row['neck_sweep']:.0f}\u00b0\n"
                    f"CF miss {row['band_cf_miss_deg']:.1f}\u00b0  ratio {row['ratio']:.3f}",
                    fontsize=8, color="#b07000", ha="center")
        ax.set_aspect("equal")
        ax.legend(fontsize=7, loc="lower left")
        ax.grid(alpha=0.2)
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(png, dpi=110)
    plt.close(fig)


def _selfcheck() -> None:
    """A straight band on a 120 deg neckline must miss the CF tangent by 60 deg; a matched one by 0."""
    verts = np.asarray([[0.0, 0.0], [10.0, 0.0]])
    straight = _arc({"endpoints": [0, 1]}, verts)
    assert straight["sweep"] == 0.0 and not np.isfinite(straight["radius"])
    neck = {"length": 20.0, "sweep": 120.0}
    assert abs(abs(neck["sweep"] - straight["sweep"]) / 2 - 60.0) < 1e-9
    assert _tangent_deg(np.asarray([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]])) == 0.0
    assert abs(_tangent_deg(np.asarray([[0.0, 0.0], [0.0, 1.0], [0.0, 2.0], [0.0, 3.0]])) - 90.0) < 1e-9


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out")
    ap.add_argument("--only", help="comma-separated safe ids")
    ap.add_argument("--plots", type=Path, default=DRAPE / "runs/out/shots/tee_neck/neckline")
    ap.add_argument("--tag", default="", help="suffix for plot filenames, e.g. a size")
    ap.add_argument("--sim", action="store_true", help="also measure the draped neck ring")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()
    _selfcheck()

    wanted = {s.strip() for s in args.only.split(",")} if args.only else None
    rows_all = []
    for safe, spec_path in item_specs(args.out):
        if wanted and safe not in wanted:
            continue
        pattern_spec = find_spec(args.out / safe)
        hits = sorted((args.out / safe / "pattern").glob("*/*_specification.json"))
        spec_path = hits[0] if hits else pattern_spec
        rows = pattern_metrics(spec_path)
        if not rows:
            print(f"{safe}: no band-to-bodice seam (not a Turtle crew), skipping")
            continue
        for r in [x for x in rows if "right" in x["torso"]]:
            print(f"{safe:22s} {r['side']:5s} CF_tangent={r['cf_tangent_deg']:5.1f}deg  "
                  f"neck R={r['neck_radius']:6.2f} sweep={r['neck_sweep']:6.1f}  "
                  f"band R={r['band_radius']:6.2f} sweep={r['band_sweep']:6.1f}  "
                  f"CF_miss={r['band_cf_miss_deg']:5.1f}deg  ratio={r['ratio']:.3f}")
            rows_all.append({"safe": safe, **{k: v for k, v in r.items()}})
        if args.sim:
            objs = sorted((args.out / safe / "sim").glob("*/*_sim.obj"))
            if objs:
                m = sim_metrics(objs[0])
                if m:
                    print(f"{safe:22s} SIM  cf_turn={m['cf_turn_deg']:5.1f}deg  "
                          f"max={m['max_turn_deg']:5.1f}  median={m['median_turn_deg']:5.1f}  "
                          f"cf_is_sharpest={m['cf_is_sharpest']}")
                    rows_all.append({"safe": safe, "side": "sim", **m})
        if not args.no_plot:
            name = f"{safe}_{args.tag}" if args.tag else safe
            plot(spec_path, rows, args.plots / f"{name}.png")
    out = args.plots / "neckline_metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([{k: v for k, v in r.items() if k != "pts"} for r in rows_all], indent=2))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
