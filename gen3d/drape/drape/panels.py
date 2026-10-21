"""Pattern-space panel geometry: flat outlines in cm, grain, labelled seams, flat-lay layouts and landmarks."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from drape._repo import DRAPE, bootstrap

bootstrap()

import svgpathtools as svgpath  # noqa: E402

from pygarment.meshgen.boxmeshgen import Edge  # noqa: E402
from pygarment.pattern.rotation import euler_xyz_to_R  # noqa: E402
from pygarment.pattern.utils import c_to_np  # noqa: E402

from drape.texture import load_obj  # noqa: E402

CHORD = 0.25
DEV_TOL = 0.3
MISMATCH = 0.02
FLIP_MARGIN = 0.25
SIDE_TOL = 1.0
PNG_WIDTH = 2000

LABELS = ("outseam", "inseam", "center_front", "center_back", "side_seam", "shoulder", "armhole",
          "sleeve_outer", "underarm", "hem", "waist", "cuff", "neckline", "hood_edge", "hood_seam",
          "collar", "placket", "dart", "other")
# (seam along the body's outside, seam along the inside, axis the two are told apart by)
PAIRS = {"leg": ("outseam", "inseam", "absx"), "arm": ("sleeve_outer", "underarm", "y"),
         "torso": ("shoulder", "side_seam", "y"), "band": ("side_seam", "side_seam", "y"),
         "hood": ("hood_seam", "hood_seam", "y"), "collar": ("collar", "collar", "y")}
COLORS = {"outseam": "#e6194b", "inseam": "#3cb44b", "center_front": "#4363d8", "center_back": "#911eb4",
          "side_seam": "#f58231", "shoulder": "#00b3b3", "armhole": "#f032e6", "sleeve_outer": "#7a9e00",
          "underarm": "#008080", "hem": "#9a6324", "waist": "#808000", "cuff": "#000075",
          "neckline": "#c060ff", "hood_edge": "#00a36c", "hood_seam": "#d44ea0", "collar": "#b07000",
          "placket": "#696969", "dart": "#ff0000", "other": "#999999"}
BOTTOM_MARKS = ("waist_left", "waist_right", "crotch",
                "hem_outer_left", "hem_inner_left", "hem_outer_right", "hem_inner_right")
TOP_MARKS = ("neck_left", "neck_right", "shoulder_left", "shoulder_right",
             "armpit_left", "armpit_right", "hem_left", "hem_right")


def find_spec(item_dir: Path) -> Path | None:
    """The sim's own specification, else the pre-sim pattern one. Variant sim dirs are ignored."""
    for sub in ("sim", "pattern"):
        hits = sorted((item_dir / sub).glob("*/*_specification.json")) if (item_dir / sub).is_dir() else []
        if hits:
            return hits[0]
    return None


def item_specs(out: Path, only: str | None = None) -> list[tuple[str, Path]]:
    items = []
    for d in sorted(p for p in out.iterdir() if p.is_dir()):
        if only and d.name != only:
            continue
        spec = find_spec(d)
        if spec is not None:
            items.append((d.name, spec))
    return items


def frame(pan: dict) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(euler_xyz_to_R(pan["rotation"]), float), np.asarray(pan["translation"], float)


def to_world(pts: np.ndarray, R: np.ndarray, T: np.ndarray) -> np.ndarray:
    flat = np.atleast_2d(pts)
    return np.concatenate([flat, np.zeros((len(flat), 1))], 1) @ R.T + T


def to_local(world: np.ndarray, R: np.ndarray, T: np.ndarray) -> np.ndarray:
    return (np.atleast_2d(world) - T) @ R


def edge_curve(e: dict, verts: np.ndarray) -> tuple[np.ndarray, float]:
    """Panel-local polyline for one spec edge, curves chopped into <=CHORD chords, plus its true length."""
    ed = Edge(e, verts, CHORD)
    c = ed.curve
    if isinstance(c, svgpath.Line):
        return np.asarray(ed.endpoints, float), float(c.length())
    n = max(ed.n_edge_verts, 3)
    if isinstance(c, svgpath.Arc):
        pts = [c_to_np(c.point(float(t))) for t in np.linspace(0, 1, n)]
    else:
        ts = [c.ilength(float(v)) for v in np.linspace(0, 1, n) * c.length()]
        pts = [c_to_np(p) for p in c.points(ts)]
    return np.asarray(pts, float), float(c.length())


def ring(edges: list[dict]) -> list[int]:
    """Edge ids in boundary-loop order, following shared endpoints."""
    n = len(edges)
    order, used, cur = [0], {0}, edges[0]["endpoints"][1]
    while len(order) < n:
        nxt = next((i for i in range(n) if i not in used and edges[i]["endpoints"][0] == cur), None)
        if nxt is None:
            return list(range(n))
        order.append(nxt)
        used.add(nxt)
        cur = edges[nxt]["endpoints"][1]
    return order


def up_axis(R: np.ndarray) -> np.ndarray:
    """In-plane direction that points most towards world up; for an unrotated panel that is local +y."""
    d = np.array([R[1, 0], R[1, 1]], float)
    n = np.linalg.norm(d)
    return d / n if n > 1e-9 else np.array([0.0, 1.0])


def limb_up(p: dict) -> np.ndarray:
    """Sleeves are cut along the arm whatever pose they were placed in: square to the hem, toward the sewn end."""
    hems = [p["polys"][e] for e, lab in enumerate(p["labels"]) if lab == "hem"]
    hems = hems or [p["polys"][e] for e, lab in enumerate(p["labels"]) if lab == "cuff" and p["kind"] == "sleeve"]
    if not hems:
        return p["up"]
    hem = max(hems, key=lambda q: float(np.linalg.norm(q[-1] - q[0])))
    chord = hem[-1] - hem[0]
    n = np.array([-chord[1], chord[0]]) / max(float(np.linalg.norm(chord)), 1e-9)
    return n if float((p["outline"].mean(0) - hem.mean(0)) @ n) > 0 else -n


def classify(name: str, pan: dict, world: np.ndarray) -> dict:
    parts = set(name.lower().split("_"))
    low = name.lower()
    if "cuff" in parts:
        kind = "cuff"
    elif "wb" in parts or "waistband" in low:
        kind = "waistband"
    elif "hood" in low:
        kind = "hood"
    elif "collar" in low:
        kind = "collar"
    elif "sleeve" in low:
        kind = "sleeve"
    elif parts & {"f", "front", "ftorso"}:
        kind = "front"
    elif parts & {"b", "back", "btorso"}:
        kind = "back"
    else:
        kind = "other"

    if parts & {"l", "left"}:
        side = "left"
    elif parts & {"r", "right"}:
        side = "right"
    else:
        mx = float(world[:, 0].mean())
        side = "left" if mx > SIDE_TOL else "right" if mx < -SIDE_TOL else "center"

    label = (pan.get("label") or "").lower()
    region = label if label in ("leg", "arm", "body") else (
        "leg" if "pant" in parts else "arm" if "sleeve" in low else "body")
    fam = {"sleeve": "arm", "waistband": "band", "hood": "hood", "collar": "collar"}.get(kind)
    if kind in ("front", "back"):
        fam = "leg" if region == "leg" else "torso"
    rib = kind in ("cuff", "waistband") or bool(parts & {"rib", "hem"})
    # the body faces +z, so a panel's z side is which way it is worn
    face = "f" if float(world[:, 2].mean()) > 0 else "b"
    return {"kind": kind, "side": side, "region": region, "family": fam, "rib": rib, "face": face}


def pair_side(st: list) -> bool:
    """Spec convention: edges run against each other unless the stitch is tagged right_wrong."""
    return not (len(st) == 3 and st[-1] == "right_wrong")


def oriented(st: list, wa: np.ndarray, wb: np.ndarray) -> bool:
    """Endpoint pairing with the shorter total gap, falling back to the spec flag when it is a near tie."""
    fwd = np.linalg.norm(wa[0] - wb[0]) + np.linalg.norm(wa[-1] - wb[-1])
    rev = np.linalg.norm(wa[0] - wb[-1]) + np.linalg.norm(wa[-1] - wb[0])
    hi = max(fwd, rev, 1e-9)
    return rev < fwd if abs(fwd - rev) > FLIP_MARGIN * hi else pair_side(st)


def direct_label(a: dict, b: dict) -> str | None:
    """Label a stitch from the two panels' roles alone; None means it needs the geometric pair rule."""
    ka, kb = a["kind"], b["kind"]
    both = {ka, kb}
    if ka == "hood" and kb == "hood":
        return "hood_seam"
    if ka == "collar" and kb == "collar":
        return "collar"
    if both & {"hood", "collar"} and both & {"front", "back"}:
        return "neckline"
    if "waistband" in both and not (ka == kb):
        return "waist"
    if "placket" in both:
        return "placket"
    if "sleeve" in both and both & {"front", "back"}:
        return "armhole"
    if "cuff" in both and ka != kb:
        return "cuff"
    if a["side"] != b["side"] and "center" not in (a["side"], b["side"]) and a["face"] == b["face"]:
        return "center_front" if a["face"] == "f" else "center_back"
    if a["side"] == b["side"] and a["face"] != b["face"] and (ka == kb or both <= {"front", "back"}):
        return None
    return "other"


def chains(ids: list[int], pos: dict[int, int], n: int) -> list[list[int]]:
    """Split edge ids into runs that are neighbours on the panel's boundary loop."""
    ranked = sorted(ids, key=lambda i: pos[i])
    out: list[list[int]] = []
    for i in ranked:
        if out and (pos[out[-1][-1]] + 1) % n == pos[i]:
            out[-1].append(i)
        else:
            out.append([i])
    if len(out) > 1 and (pos[out[-1][-1]] + 1) % n == pos[out[0][0]]:
        out[0] = out[-1] + out[0]
        out.pop()
    return out


def build_panels(spec_path: Path) -> dict:
    spec = json.loads(Path(spec_path).read_text())["pattern"]
    raw = spec["panels"]
    named = [n for n in spec.get("panel_order", []) if n in raw]
    order = named + sorted(set(raw) - set(named))

    P: dict[str, dict] = {}
    for name in order:
        pan = raw[name]
        verts = np.asarray(pan["vertices"], float)
        R, T = frame(pan)
        polys, lens = [], []
        for e in pan["edges"]:
            poly, length = edge_curve(e, verts)
            polys.append(poly)
            lens.append(length)
        rorder = ring(pan["edges"])
        outline = np.concatenate([polys[i][:-1] for i in rorder])
        world = to_world(outline, R, T)
        p = classify(name, pan, world) | {
            "spec": pan, "verts": verts, "polys": polys, "lens": lens, "R": R, "T": T,
            "outline": outline, "world": world, "up": up_axis(R), "ring": rorder,
            "pos": {e: k for k, e in enumerate(rorder)},
            "edge_world": [to_world(q, R, T) for q in polys],
            "labels": [None] * len(pan["edges"]), "stitch": [None] * len(pan["edges"]),
            "mate": [None] * len(pan["edges"]),
        }
        P[name] = p

    stitches = spec["stitches"]
    for k, st in enumerate(stitches):
        for side in (0, 1):
            s, o = st[side], st[1 - side]
            P[s["panel"]]["stitch"][s["edge"]] = k
            P[s["panel"]]["mate"][s["edge"]] = (o["panel"], o["edge"])

    # a cuff belongs to whatever limb it is sewn onto
    for name, p in P.items():
        if p["kind"] != "cuff":
            continue
        for e, mate in enumerate(p["mate"]):
            if mate and P[mate[0]]["kind"] != "cuff" and P[mate[0]]["family"]:
                p["family"] = P[mate[0]]["family"]
                break
        if not p["family"]:
            p["family"] = "arm" if p["region"] == "arm" else "leg"

    rev = [oriented(st, P[st[0]["panel"]]["edge_world"][st[0]["edge"]],
                    P[st[1]["panel"]]["edge_world"][st[1]["edge"]]) for st in stitches]
    labels: list[str | None] = [None] * len(stitches)
    pending: dict[tuple[str, str], list[int]] = {}
    for k, st in enumerate(stitches):
        a, b = st[0]["panel"], st[1]["panel"]
        if a == b:
            labels[k] = "dart"
            continue
        lab = direct_label(P[a], P[b])
        if lab is None:
            pending.setdefault(tuple(sorted((a, b))), []).append(k)
        else:
            labels[k] = lab

    notes = []
    for (a, b), ks in pending.items():
        p = P[a]
        outer, inner, axis = PAIRS.get(p["family"] or "other", ("other", "other", "y"))
        groups = chains([next(s["edge"] for s in stitches[k][:2] if s["panel"] == a) for k in ks],
                        p["pos"], len(p["polys"]))
        by_edge = {next(s["edge"] for s in stitches[k][:2] if s["panel"] == a): k for k in ks}

        def score(grp: list[int]) -> float:
            pts = np.concatenate([p["edge_world"][e] for e in grp])
            return float(np.abs(pts[:, 0]).mean() if axis == "absx" else pts[:, 1].mean())

        vals = [score(g) for g in groups]
        if outer == inner:
            pick = [outer] * len(groups)
        elif len(groups) == 1:
            ref = float(np.abs(p["world"][:, 0]).mean() if axis == "absx" else p["world"][:, 1].mean())
            pick = [outer if vals[0] >= ref else inner]
        else:
            hi, lo = max(vals), min(vals)
            pick = [outer if abs(v - hi) <= abs(v - lo) else inner for v in vals]
            if len(groups) > 2:
                notes.append(f"{a}<->{b}: {len(groups)} seam chains")
        for grp, lab in zip(groups, pick):
            for e in grp:
                labels[by_edge[e]] = lab

    for k, st in enumerate(stitches):
        for s in st[:2]:
            P[s["panel"]]["labels"][s["edge"]] = labels[k]

    for name, p in P.items():
        extent = np.array([q @ p["up"] for q in p["outline"]])
        mid = (extent.min() + extent.max()) / 2
        for e, lab in enumerate(p["labels"]):
            if lab is not None:
                continue
            spec_lab = (p["spec"]["edges"][e].get("label") or "").lower()
            high = float((p["polys"][e] @ p["up"]).mean()) > mid
            if "collar" in spec_lab:
                p["labels"][e] = "neckline"
            elif "armhole" in spec_lab:
                p["labels"][e] = "armhole"
            elif spec_lab == "lower_interface" or p["kind"] == "waistband":
                p["labels"][e] = "waist"
            elif p["kind"] == "hood":
                p["labels"][e] = "hood_edge"
            elif p["kind"] == "collar":
                p["labels"][e] = "collar"
            elif p["kind"] in ("front", "back", "sleeve", "cuff"):
                p["labels"][e] = ("waist" if p["region"] == "leg" else "neckline") if (
                    high and p["kind"] in ("front", "back")) else "hem"
            else:
                p["labels"][e] = "other"
    for p in P.values():
        if p["family"] == "arm":
            p["up"] = limb_up(p)

    garment = "bottom" if any(p["family"] == "leg" for p in P.values()) else "upper"
    out = {"safe": Path(spec_path).parents[2].name,
           "spec": str(Path(spec_path).relative_to(Path(spec_path).parents[2])),
           "garment": garment, "panels": {}, "stitches": [], "landmarks": {}}

    for name in order:
        p = P[name]
        grain = p["up"] if (p["up"][1] > 0 or (p["up"][1] == 0 and p["up"][0] > 0)) else -p["up"]
        view, affine = None, None
        if p["kind"] not in ("hood", "collar"):
            view = "front" if p["face"] == "f" else "back"
            sx = 1.0 if view == "front" else -1.0
            affine = [[sx * p["R"][0, 0], sx * p["R"][0, 1], sx * p["T"][0]],
                      [p["R"][1, 0], p["R"][1, 1], p["T"][1]]]
        rec = {"kind": p["kind"], "side": p["side"], "rib": p["rib"],
               "outline_cm": np.round(p["outline"], 3).tolist(),
               "bbox_cm": [round(float(v), 3) for v in (*p["outline"].min(0), *p["outline"].max(0))],
               "translation": [round(float(v), 4) for v in p["T"]],
               "rotation": [round(float(v), 4) for v in p["spec"]["rotation"]],
               "grain_axis": [round(float(v), 6) for v in grain],
               "up": [round(float(v), 6) for v in p["up"]],
               "extent_split_cm": extent_split(p),
               "layout": {"view": view, "affine": affine}, "edges": []}
        for e, spec_e in enumerate(p["spec"]["edges"]):
            k = p["stitch"][e]
            mate = p["mate"][e]
            la, lb = (p["lens"][e], P[mate[0]]["lens"][mate[1]]) if mate else (p["lens"][e], p["lens"][e])
            rec["edges"].append({
                "id": e, "endpoints": list(spec_e["endpoints"]), "label": p["labels"][e],
                "polyline_cm": np.round(p["polys"][e], 3).tolist(),
                "length_cm": round(p["lens"][e], 4), "stitch": k,
                "mate": None if mate is None else {"panel": mate[0], "edge": mate[1],
                                                   "reversed": bool(rev[k])},
                "length_mismatch": bool(abs(la - lb) > MISMATCH * max(la, lb, 1e-9)),
            })
        out["panels"][name] = rec

    for k, st in enumerate(stitches):
        a, b = st[0], st[1]
        la, lb = P[a["panel"]]["lens"][a["edge"]], P[b["panel"]]["lens"][b["edge"]]
        out["stitches"].append({
            "id": k, "a": {"panel": a["panel"], "edge": a["edge"]},
            "b": {"panel": b["panel"], "edge": b["edge"]}, "label": labels[k],
            "reversed": bool(rev[k]), "length_a": round(la, 4), "length_b": round(lb, 4),
        })
    out["landmarks"] = {v: marks(P, out, garment, v) for v in ("front", "back")}
    if notes:
        out["notes"] = notes
    return out


def extent_split(p: dict) -> float | None:
    """Knee for a leg panel, elbow for a sleeve: the coordinate along `up` where the panel halves."""
    ext = p["outline"] @ p["up"]
    if p["family"] == "arm" and p["kind"] == "sleeve":
        return round(float((ext.min() + ext.max()) / 2), 3)
    if p["family"] == "leg" and p["kind"] in ("front", "back"):
        inseam = [p["polys"][e] for e, lab in enumerate(p["labels"]) if lab == "inseam"]
        if not inseam:
            return None
        crotch = float(max((q @ p["up"]).max() for q in inseam))
        return round(float((ext.min() + crotch) / 2), 3)
    return None


def lay(p: dict, pts: np.ndarray, view: str) -> np.ndarray:
    w = to_world(pts, p["R"], p["T"])
    return np.stack([w[:, 0] * (1 if view == "front" else -1), w[:, 1]], 1)


def pick(P: dict, view: str, **want) -> list[str]:
    face = "f" if view == "front" else "b"
    return [n for n, p in P.items() if p["face"] == face
            and all(p.get(k) == v for k, v in want.items())]


def edges_with(p: dict, label: str) -> list[int]:
    return [e for e, lab in enumerate(p["labels"]) if lab == label]


def junction(p: dict, la: str, lb: str) -> np.ndarray | None:
    for ea in edges_with(p, la):
        for eb in edges_with(p, lb):
            common = set(p["spec"]["edges"][ea]["endpoints"]) & set(p["spec"]["edges"][eb]["endpoints"])
            if common:
                return p["verts"][sorted(common)[0]]
    return None


def hem_panel(P: dict, view: str, side: str, family: str) -> str | None:
    cands = [n for n in pick(P, view, side=side, family=family) if edges_with(P[n], "hem")]
    if not cands:
        return None
    return min(cands, key=lambda n: min((P[n]["polys"][e] @ P[n]["up"]).min()
                                        for e in edges_with(P[n], "hem")))


def marks(P: dict, out: dict, garment: str, view: str) -> dict:
    m: dict[str, list[float]] = {}

    def put(key: str, p: dict, pt) -> None:
        if pt is not None:
            m[key] = [round(float(v), 3) for v in lay(p, np.asarray(pt, float)[None], view)[0]]

    if garment == "bottom":
        cf = "center_front" if view == "front" else "center_back"
        allcf = []
        for side in ("left", "right"):
            legs = [n for n in pick(P, view, side=side, family="leg") if P[n]["kind"] in ("front", "back")]
            if not legs:
                continue
            p = P[legs[0]]
            outs = edges_with(p, "outseam")
            if outs:
                pts = np.concatenate([p["polys"][e] for e in outs])
                put(f"waist_{side}", p, pts[np.argmax(pts @ p["up"])])
            allcf += [lay(p, p["polys"][e], view) for e in edges_with(p, cf)]
            hp = hem_panel(P, view, side, "leg")
            if hp:
                q = P[hp]
                for e in edges_with(q, "hem"):
                    ends = q["spec"]["edges"][e]["endpoints"]
                    for tag, seam in (("outer", "outseam"), ("inner", "inseam")):
                        hit = [v for v in ends if any(v in q["spec"]["edges"][o]["endpoints"]
                                                      for o in edges_with(q, seam))]
                        if hit:
                            put(f"hem_{tag}_{side}", q, q["verts"][hit[0]])
        if allcf:
            pts = np.concatenate(allcf)
            m["crotch"] = [round(float(v), 3) for v in pts[np.argmin(pts[:, 1])]]
    else:
        for side in ("left", "right"):
            torso = pick(P, view, side=side, family="torso")
            if torso:
                p = P[torso[0]]
                put(f"neck_{side}", p, junction(p, "neckline", "shoulder"))
                put(f"shoulder_{side}", p, junction(p, "shoulder", "armhole"))
                put(f"armpit_{side}", p, junction(p, "armhole", "side_seam"))
                put(f"hem_{side}", p, junction(p, "side_seam", "hem"))
            hp = hem_panel(P, view, side, "arm")
            if hp:
                q = P[hp]
                e = edges_with(q, "hem")[0]
                put(f"cuff_{side}", q, q["polys"][e].mean(0))
    return m


def inside(poly: np.ndarray, pts: np.ndarray) -> np.ndarray:
    a, b = poly, np.roll(poly, -1, 0)
    hit = np.zeros(len(pts), bool)
    for (x1, y1), (x2, y2) in zip(a, b):
        if y1 == y2:
            continue
        span = (y1 > pts[:, 1]) != (y2 > pts[:, 1])
        hit ^= span & (pts[:, 0] < (x2 - x1) * (pts[:, 1] - y1) / (y2 - y1) + x1)
    return hit


def deviation(poly: np.ndarray, pts: np.ndarray) -> float:
    """How far outside the outline the boxmesh's own panel vertices sit, in cm."""
    a, b = poly, np.roll(poly, -1, 0)
    ab = b - a
    worst = 0.0
    for lo in range(0, len(pts), 512):
        chunk = pts[lo:lo + 512]
        t = np.clip(((chunk[:, None, :] - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-12), 0, 1)
        d = np.linalg.norm(chunk[:, None, :] - (a + t[..., None] * ab), axis=-1).min(1)
        d[inside(poly, chunk)] = 0.0
        worst = max(worst, float(d.max()) if len(d) else 0.0)
    return worst


def verify(data: dict, spec_path: Path) -> dict:
    bad: list[str] = list(data.get("notes", []))
    labelled = Counter(s["label"] for s in data["stitches"])
    for s in data["stitches"]:
        if s["label"] == "other" or s["label"] not in LABELS:
            bad.append(f"stitch {s['id']} {s['a']['panel']}.e{s['a']['edge']}"
                       f"<->{s['b']['panel']}.e{s['b']['edge']} label {s['label']}")
        off = abs(s["length_a"] - s["length_b"]) > MISMATCH * max(s["length_a"], s["length_b"], 1e-9)
        edge = data["panels"][s["a"]["panel"]]["edges"][s["a"]["edge"]]
        if off != edge["length_mismatch"]:
            bad.append(f"stitch {s['id']} mismatch not flagged")
    if data["garment"] == "bottom":
        for key in ("center_front", "center_back"):
            if not labelled[key]:
                bad.append(f"no {key} stitch")
    elif not labelled["center_front"] or not labelled["center_back"]:
        bad.append("missing center_front/center_back stitch")

    for name, p in data["panels"].items():
        for key in ("grain_axis", "up"):
            if abs(float(np.linalg.norm(p[key])) - 1) > 1e-5:
                bad.append(f"{name}: {key} not unit")
        leg_or_torso = p["kind"] in ("front", "back")
        if leg_or_torso and float(np.dot(p["up"], [0, 1])) < 0.99:
            bad.append(f"{name}: up {p['up']} not along +y")
        if leg_or_torso and data["garment"] == "bottom":
            n = len(p["edges"])
            pos = {e["id"]: k for k, e in enumerate(p["edges"])}
            for label in ("outseam", "inseam"):
                ids = [e["id"] for e in p["edges"] if e["label"] == label]
                runs = chains(ids, pos, n) if ids else []
                if len(runs) != 1:
                    bad.append(f"{name}: {len(runs)} {label} chains")

    need = BOTTOM_MARKS if data["garment"] == "bottom" else TOP_MARKS
    for view in ("front", "back"):
        got = data["landmarks"][view]
        for key in need:
            if key not in got:
                bad.append(f"{view}: no {key} landmark")
        if data["garment"] == "upper" and any(p["kind"] == "sleeve" for p in data["panels"].values()):
            for key in ("cuff_left", "cuff_right"):
                if key not in got:
                    bad.append(f"{view}: no {key} landmark")

    dev = 0.0
    stem = Path(spec_path).name[: -len("_specification.json")]
    box = Path(spec_path).parent / f"{stem}_boxmesh.obj"
    seg = Path(spec_path).parent / f"{stem}_sim_segmentation.txt"
    if box.is_file() and seg.is_file():
        verts = load_obj(box)[0]
        tags = seg.read_text().split()
        for name, p in data["panels"].items():
            sel = [i for i, t in enumerate(tags) if t == name]
            if not sel:
                continue
            R, T = np.asarray(euler_xyz_to_R(p["rotation"]), float), np.asarray(p["translation"], float)
            d = deviation(np.asarray(p["outline_cm"], float), to_local(verts[sel], R, T)[:, :2])
            dev = max(dev, d)
            if d > DEV_TOL:
                bad.append(f"{name}: boxmesh {d:.2f} cm outside outline")
    else:
        dev = float("nan")
    return {"max_dev_cm": dev, "issues": bad, "labels": dict(sorted(labelled.items()))}


def apply(A: np.ndarray, pts: np.ndarray) -> np.ndarray:
    q = np.atleast_2d(np.asarray(pts, float))
    return np.concatenate([q, np.ones((len(q), 1))], 1) @ A.T


def sheets(data: dict) -> tuple[list[dict], dict[str, float], tuple[float, float, float, float]]:
    """Place each panel into its view's flat lay, panels with no layout into a third strip."""
    placed: list[dict] = []
    for view in ("front", "back"):
        for name, p in data["panels"].items():
            if p["layout"]["view"] == view:
                placed.append({"name": name, "panel": p, "view": view,
                               "A": np.asarray(p["layout"]["affine"], float)})
    spans = {}
    for view in ("front", "back"):
        mine = [i for i in placed if i["view"] == view]
        pts = np.concatenate([apply(i["A"], i["panel"]["outline_cm"]) for i in mine]) if mine \
            else np.zeros((1, 2))
        spans[view] = (float(pts[:, 0].min()), float(pts[:, 0].max()))

    gap = 12.0
    shift = {"front": 0.0, "back": spans["front"][1] - spans["back"][0] + gap}
    for item in placed:
        item["A"] = item["A"] + np.array([[0, 0, shift[item["view"]]], [0, 0, 0]], float)
    cursor = spans["back"][1] + shift["back"] + gap
    top = max((apply(i["A"], i["panel"]["outline_cm"])[:, 1].max() for i in placed), default=0.0)
    for name, p in data["panels"].items():
        if p["layout"]["view"] is not None:
            continue
        out = np.asarray(p["outline_cm"], float)
        placed.append({"name": name, "panel": p, "view": None,
                       "A": np.array([[1, 0, cursor - out[:, 0].min()],
                                      [0, 1, top - out[:, 1].max()]], float)})
        cursor += float(out[:, 0].max() - out[:, 0].min()) + gap
    for item in placed:
        item["outline"] = apply(item["A"], item["panel"]["outline_cm"])
        item["pts"] = {e["id"]: apply(item["A"], e["polyline_cm"]) for e in item["panel"]["edges"]}
    allpts = np.concatenate([i["outline"] for i in placed])
    return placed, shift, (float(allpts[:, 0].min()), float(allpts[:, 0].max()),
                           float(allpts[:, 1].min()), float(allpts[:, 1].max()))


def midpoint(line: np.ndarray) -> np.ndarray:
    step = np.linalg.norm(np.diff(line, axis=0), axis=1)
    run = np.concatenate([[0.0], np.cumsum(step)])
    return np.array([np.interp(run[-1] / 2, run, line[:, 0]), np.interp(run[-1] / 2, run, line[:, 1])])


def render(data: dict, svg_path: Path, png_path: Path) -> None:
    placed, shift, (x0, x1, y0, y1) = sheets(data)
    pad = 6.0
    w_cm, h_cm = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    s = PNG_WIDTH / w_cm
    W, H = int(round(w_cm * s)), int(round(h_cm * s))

    def px(pts: np.ndarray) -> np.ndarray:
        q = np.atleast_2d(pts)
        return np.stack([(q[:, 0] - x0 + pad) * s, (y1 + pad - q[:, 1]) * s], 1)

    body: list[str] = []
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    for item in placed:
        poly = px(item["outline"])
        pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in poly)
        body.append(f'<polygon points="{pts}" fill="#f6f6f6" stroke="#333" stroke-width="1.2"/>')
        d.polygon([tuple(v) for v in poly], fill=(246, 246, 246), outline=(60, 60, 60))
    for item in placed:
        p = item["panel"]
        for e in p["edges"]:
            col = COLORS.get(e["label"], "#999999")
            line = px(item["pts"][e["id"]])
            body.append('<polyline points="' + " ".join(f"{a:.1f},{b:.1f}" for a, b in line)
                        + f'" fill="none" stroke="{col}" stroke-width="3"/>')
            d.line([tuple(v) for v in line], fill=col, width=3)
            mid = midpoint(line)
            tag = e["label"] + ("!" if e["length_mismatch"] else "")
            body.append(f'<text x="{mid[0]:.1f}" y="{mid[1]:.1f}" font-size="11" fill="{col}">{tag}</text>')
            d.text((mid[0] + 2, mid[1] - 6), tag, fill=col)
        c = item["outline"].mean(0)
        reach = min(8.0, 0.35 * min(p["bbox_cm"][2] - p["bbox_cm"][0], p["bbox_cm"][3] - p["bbox_cm"][1]))
        g = np.asarray(p["grain_axis"], float) * reach
        arrow = px(np.stack([c - g, c + g]))
        body.append(f'<line x1="{arrow[0][0]:.1f}" y1="{arrow[0][1]:.1f}" x2="{arrow[1][0]:.1f}"'
                    f' y2="{arrow[1][1]:.1f}" stroke="#0a0" stroke-width="2.5"/>')
        d.line([tuple(arrow[0]), tuple(arrow[1])], fill=(0, 150, 0), width=3)
        u = px(np.stack([c, c + np.asarray(p["up"], float) * reach * 0.75]))
        body.append(f'<line x1="{u[0][0]:.1f}" y1="{u[0][1]:.1f}" x2="{u[1][0]:.1f}" y2="{u[1][1]:.1f}"'
                    ' stroke="#00c" stroke-width="2.5"/>')
        d.line([tuple(u[0]), tuple(u[1])], fill=(0, 0, 200), width=3)
        lab = f"{item['name']} [{p['kind']}/{p['side']}{'/rib' if p['rib'] else ''}]"
        at = px(c)[0]
        body.append(f'<text x="{at[0]:.1f}" y="{at[1]:.1f}" font-size="14" text-anchor="middle"'
                    f' fill="#000">{lab}</text>')
        d.text((at[0] - 3 * len(lab), at[1] + 6), lab, fill=(0, 0, 0))

    for view in ("front", "back"):
        for key, pt in data["landmarks"][view].items():
            at = px(np.array([[pt[0] + shift[view], pt[1]]]))[0]
            body.append(f'<circle cx="{at[0]:.1f}" cy="{at[1]:.1f}" r="5" fill="none" stroke="#000"'
                        ' stroke-width="2" stroke-dasharray="3,2"/>')
            body.append(f'<text x="{at[0] + 7:.1f}" y="{at[1]:.1f}" font-size="12" fill="#000">{key}</text>')
            d.ellipse([at[0] - 5, at[1] - 5, at[0] + 5, at[1] + 5], outline=(0, 0, 0), width=2)
            d.text((at[0] + 7, at[1] - 5), key, fill=(0, 0, 0))

    title = f"{data['safe']} {data['garment']} - front | back" + (" | unplaced" if any(
        i["view"] is None for i in placed) else "")
    body.insert(0, f'<text x="10" y="22" font-size="20" fill="#000">{title}</text>')
    d.text((10, 10), title, fill=(0, 0, 0))
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
        '<rect width="100%" height="100%" fill="white"/>' + "".join(body) + "</svg>")
    img.save(png_path)


def write_item(out: Path, safe: str, spec_path: Path) -> dict:
    data = build_panels(spec_path)
    base = out / safe
    base.mkdir(parents=True, exist_ok=True)
    (base / "panels.json").write_text(json.dumps(data, indent=1))
    render(data, base / "panels.svg", base / "panels.png")
    return data


def load_panels(out: Path, safe: str) -> dict:
    path = out / safe / "panels.json"
    if path.is_file():
        return json.loads(path.read_text())
    spec = find_spec(out / safe)
    if spec is None:
        raise SystemExit(f"{out / safe}: no *_specification.json under sim/ or pattern/")
    return write_item(out, safe, spec)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out")
    ap.add_argument("--only")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    items = item_specs(a.out, a.only)
    if not items:
        raise SystemExit(f"no items with a *_specification.json under {a.out}")
    bad = []
    for safe, spec in items:
        data = write_item(a.out, safe, spec)
        v = verify(data, spec)
        print(f"{safe} | {len(data['panels'])} panels | {len(data['stitches'])} stitches | "
              f"labels {v['labels']} | max boxmesh dev {v['max_dev_cm']:.2f} cm"
              + (f" | ISSUES {len(v['issues'])}: {'; '.join(v['issues'][:4])}" if v["issues"] else ""))
        if v["issues"]:
            bad.append(safe)
    if a.verify and bad:
        raise SystemExit(f"verify failed: {', '.join(bad)}")
    print(f"ok: {len(items)} items -> {a.out}/<safe>/panels.{{json,svg,png}}")


if __name__ == "__main__":
    main()
