"""Flat cloth raster per pattern panel in panel-local cm: ground, grain repeats, seam trims, photo prints."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.interpolate import RBFInterpolator

from drape._repo import DRAPE, bootstrap

bootstrap()

from drape.patternspec import PatternSpec, StripeDirection, TrimKind, TrimPlacement  # noqa: E402

MARGIN_CM = 2.0
PPC = 20.0
SEAM_STEP_CM = 0.5
DE_LIMIT = 20.0
GROUND_FRAC = 0.05
TINT_SIGMA = 0.08
TINT_LO, TINT_HI = 0.9, 1.1
TORSO_MARKS = ("neck_left", "neck_right", "shoulder_left", "shoulder_right", "armpit_left",
               "armpit_right", "hem_left", "hem_right")
PAIRED = (("neck_left", "neck_right"), ("shoulder_left", "shoulder_right"),
          ("armpit_left", "armpit_right"), ("hem_left", "hem_right"), ("waist_left", "waist_right"),
          ("hem_outer_left", "hem_outer_right"), ("hem_inner_left", "hem_inner_right"))
TOL_FRAC, KEEP_FRAC, SPAN_FRAC = 0.07, 0.12, 0.45
ROT_LIMIT, ROT_GATE, RATIO_MAX, MIN_SPREAD_CM, COVER_MIN, CHEST_FRAC = 2.5, 3.0, 2.2, 5.0, 0.5, 0.45
CHEST_SLACK = 0.3
TPS_MIN, TPS_RMS_CM = 6, 1.5
SCALE_GATE, SLEEVE_SCALE = (0.35, 2.8), (0.5, 1.8)
PATCH, OVERLAP, CANDS, POOL = 48, 16, 40, 160
PREVIEW_PPC = 4.0
THUMB = 384
SEED = 20261020
SEAM_PLACEMENTS = ("outseam", "inseam", "center_front", "center_back", "shoulder", "sleeve_outer")
PRIORITY = {"outseam": 11, "side_seam": 11, "center_front": 10, "shoulder": 9, "armhole": 8,
            "sleeve_outer": 7, "inseam": 6, "underarm": 6, "center_back": 5, "hood_seam": 4,
            "cuff": 3, "waist": 2}
XYZ = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
D65 = np.array([0.95047, 1.0, 1.08883])
LABEL_COLORS = {"outseam": (230, 25, 75), "inseam": (60, 180, 75), "center_front": (67, 99, 216),
                "center_back": (145, 30, 180), "side_seam": (245, 130, 49), "shoulder": (0, 179, 179),
                "armhole": (240, 50, 230), "sleeve_outer": (122, 158, 0), "underarm": (0, 128, 128),
                "hem": (154, 99, 36), "waist": (128, 128, 0), "cuff": (0, 0, 117),
                "neckline": (192, 96, 255), "hood_edge": (0, 163, 108), "hood_seam": (212, 78, 160),
                "collar": (176, 112, 0), "placket": (105, 105, 105), "dart": (255, 0, 0)}


def hex_rgb(value: str) -> np.ndarray:
    h = value.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)


def srgb_to_linear(u8: np.ndarray) -> np.ndarray:
    x = np.asarray(u8, float) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def to_lab(rgb: np.ndarray) -> np.ndarray:
    t = (srgb_to_linear(rgb) @ XYZ.T) / D65
    f = np.where(t > 0.008856, np.cbrt(np.maximum(t, 1e-12)), t / 0.1284 + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], -1)


def apply_affine(a: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return pts @ a[:, :2].T + a[:, 2]


def resample(poly: np.ndarray, step: float) -> np.ndarray:
    d = np.linalg.norm(np.diff(poly, axis=0), axis=1)
    run = np.concatenate([[0.0], np.cumsum(d)])
    if run[-1] < 1e-9:
        return poly[:1]
    n = max(int(math.ceil(run[-1] / step)) + 1, 2)
    t = np.linspace(0, run[-1], n)
    return np.stack([np.interp(t, run, poly[:, 0]), np.interp(t, run, poly[:, 1])], 1)


def along(poly: np.ndarray, frac: np.ndarray) -> np.ndarray:
    d = np.linalg.norm(np.diff(poly, axis=0), axis=1)
    run = np.concatenate([[0.0], np.cumsum(d)])
    t = np.asarray(frac) * run[-1]
    return np.stack([np.interp(t, run, poly[:, 0]), np.interp(t, run, poly[:, 1])], 1)


def sample_rgb(img: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Bilinear lookup of an HxWxC image at float pixel coordinates (x, y), clamped at the border."""
    h, w = img.shape[:2]
    x = np.clip(xy[:, 0] - 0.5, 0, w - 1)
    y = np.clip(xy[:, 1] - 0.5, 0, h - 1)
    j0 = np.minimum(np.floor(x).astype(np.int64), w - 2) if w > 1 else np.zeros(len(x), np.int64)
    i0 = np.minimum(np.floor(y).astype(np.int64), h - 2) if h > 1 else np.zeros(len(y), np.int64)
    fx, fy = (x - j0)[:, None], (y - i0)[:, None]
    j1, i1 = np.minimum(j0 + 1, w - 1), np.minimum(i0 + 1, h - 1)
    top = img[i0, j0] * (1 - fx) + img[i0, j1] * fx
    bot = img[i1, j0] * (1 - fx) + img[i1, j1] * fx
    return top * (1 - fy) + bot * fy


def frame_of(bbox: list[float], ppc: float) -> dict:
    x0, y0, x1, y1 = bbox
    x0, y1 = x0 - MARGIN_CM, y1 + MARGIN_CM
    w = int(math.ceil((x1 + MARGIN_CM - x0) * ppc))
    h = int(math.ceil((y1 - (y0 - MARGIN_CM)) * ppc))
    return {"x0": x0, "y1": y1, "w": max(w, 2), "h": max(h, 2), "ppc": ppc}


def frame_xy(f: dict) -> tuple[np.ndarray, np.ndarray]:
    x = f["x0"] + (np.arange(f["w"]) + 0.5) / f["ppc"]
    y = f["y1"] - (np.arange(f["h"]) + 0.5) / f["ppc"]
    return x[None, :] + np.zeros((f["h"], 1)), y[:, None] + np.zeros((1, f["w"]))


def frame_mask(f: dict, poly: np.ndarray) -> np.ndarray:
    img = Image.new("L", (f["w"], f["h"]), 0)
    px = [((px_ - f["x0"]) * f["ppc"], (f["y1"] - py) * f["ppc"]) for px_, py in poly]
    ImageDraw.Draw(img).polygon(px, fill=255, outline=255)
    return np.asarray(img) > 127


def poly_distance(polys: list[np.ndarray], f: dict, maxd: float) -> tuple[np.ndarray, np.ndarray]:
    """Cm distance to the polylines within maxd, plus which side of the nearest segment each pixel is on."""
    d = np.full((f["h"], f["w"]), np.inf, np.float64)
    side = np.zeros((f["h"], f["w"]), np.float64)
    ppc, x0, y1 = f["ppc"], f["x0"], f["y1"]
    for poly in polys:
        q = resample(poly, 0.4)
        for (ax, ay), (bx, by) in zip(q[:-1], q[1:]):
            c0 = max(int(math.floor((min(ax, bx) - maxd - x0) * ppc)), 0)
            c1 = min(int(math.ceil((max(ax, bx) + maxd - x0) * ppc)) + 1, f["w"])
            r0 = max(int(math.floor((y1 - max(ay, by) - maxd) * ppc)), 0)
            r1 = min(int(math.ceil((y1 - min(ay, by) + maxd) * ppc)) + 1, f["h"])
            if c1 <= c0 or r1 <= r0:
                continue
            px = (x0 + (np.arange(c0, c1) + 0.5) / ppc - ax)[None, :]
            py = (y1 - (np.arange(r0, r1) + 0.5) / ppc - ay)[:, None]
            ex, ey = bx - ax, by - ay
            t = np.clip((px * ex + py * ey) / max(ex * ex + ey * ey, 1e-12), 0, 1)
            near = np.hypot(px - t * ex, py - t * ey)
            win = near < d[r0:r1, c0:c1]
            d[r0:r1, c0:c1] = np.where(win, near, d[r0:r1, c0:c1])
            side[r0:r1, c0:c1] = np.where(win, np.sign(px * ey - py * ex), side[r0:r1, c0:c1])
    return d, side


def signed_distance(polys: list[np.ndarray], f: dict, maxd: float, inside: np.ndarray) -> np.ndarray:
    """Distance to the seam, positive inside the panel, resolved to sub-pixel by the segment side."""
    d, side = poly_distance(polys, f, maxd)
    far = np.isfinite(d) & (d > 3.0 / f["ppc"])
    flip = -1.0 if far.any() and ((side[far] > 0) == inside[far]).mean() < 0.5 else 1.0
    return np.where(np.isfinite(d), flip * np.where(side == 0, np.where(inside, 1.0, -1.0), side) * d,
                    np.where(inside, np.inf, -np.inf))


def calibrate(albedo: np.ndarray, mask: np.ndarray, base: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Ground colour: the photo's median where it is near the spec colour, else the spec colour."""
    rgb = albedo[..., :3]
    de = np.linalg.norm(to_lab(rgb) - to_lab(base), axis=-1)
    like = mask & (de <= DE_LIMIT)
    frac = float(like.sum()) / max(int(mask.sum()), 1)
    if frac < GROUND_FRAC:
        return base, like, frac
    return np.median(rgb[like].astype(float), axis=0), like, frac


def tint_field(albedo: np.ndarray, mask: np.ndarray, like: np.ndarray) -> np.ndarray:
    """Low-frequency luma of the ground-like pixels only, normalised to its own median."""
    ys, xs = np.nonzero(mask)
    sigma = max(TINT_SIGMA * float(xs.max() - xs.min() + 1), 2.0)
    y = srgb_to_linear(albedo[..., :3]) @ [0.2126, 0.7152, 0.0722]
    m = like.astype(float)
    num = ndimage.gaussian_filter(y * m, sigma, mode="nearest")
    den = ndimage.gaussian_filter(m, sigma, mode="nearest")
    low = num / np.maximum(den, 1e-6)
    med = float(np.median(low[like])) if like.any() else 1.0
    return np.clip(low / max(med, 1e-6), TINT_LO, TINT_HI).astype(np.float32)


def runs_of(row: np.ndarray) -> np.ndarray:
    edges = np.flatnonzero(np.diff(np.concatenate([[0], row.astype(np.int8), [0]])))
    return edges.reshape(-1, 2)


def hull_gap(v: np.ndarray, upper: bool) -> int:
    """Index of the deepest dent in a 1-D profile relative to its own convex envelope."""
    s = v if upper else -v
    keep: list[int] = []
    for i in range(len(s)):
        while len(keep) >= 2 and (s[keep[-1]] - s[keep[-2]]) * (i - keep[-1]) <= \
                (s[i] - s[keep[-1]]) * (keep[-1] - keep[-2]):
            keep.pop()
        keep.append(i)
    env = np.interp(np.arange(len(s)), keep, s[keep])
    return int(np.argmax(env - s))


def chord_peak(cols: np.ndarray, prof: np.ndarray) -> int:
    base = prof[0] + (prof[-1] - prof[0]) * (cols - cols[0]) / max(cols[-1] - cols[0], 1)
    return int(np.argmax(base - prof))


def torso_band(mask: np.ndarray, r0: int, r1: int) -> tuple[int, int] | None:
    """The columns that reach the hem: the torso slab, found without reference to where the sleeves lie."""
    lo = r0 + int(0.75 * (r1 - r0))
    runs = runs_of(mask[lo:r1 + 1].mean(0) > 0.5)
    if not len(runs):
        return None
    a, b = runs[np.argmax(runs[:, 1] - runs[:, 0])]
    return int(a), int(b) - 1


def detect_marks(mask: np.ndarray, garment: str) -> tuple[dict, list[str], tuple[int, int, int, int]]:
    """Garment landmarks on the cutout alpha, in image pixels; wearer's left is the larger column."""
    ys, xs = np.nonzero(mask)
    r0, r1, c0, c1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    span = c1 - c0 + 1
    m: dict[str, list[float]] = {}
    notes: list[str] = []
    if garment == "bottom":
        band = range(r0, min(r0 + max(4, int(0.03 * (r1 - r0))), r1))
        best = max(((rr[:, 1] - rr[:, 0]).max(), r) for r in band if len(rr := runs_of(mask[r])))
        row = best[1]
        rr = runs_of(mask[row])
        wide = rr[np.argmax(rr[:, 1] - rr[:, 0])]
        m["waist_right"], m["waist_left"] = [float(wide[0]), float(row)], [float(wide[1] - 1), float(row)]
        cx = (wide[0] + wide[1]) / 2
        for r in range(row, r1):
            rr = runs_of(mask[r])
            rr = rr[(rr[:, 1] - rr[:, 0]) >= 0.08 * span]
            if len(rr) >= 2:
                m["crotch"] = [float((rr[0][1] + rr[1][0]) / 2), float(r)]
                cx = (rr[0][1] + rr[1][0]) / 2
                break
        if "crotch" not in m:
            notes.append("no crotch")
        for side in ("left", "right"):
            leg = mask.copy()
            cut = slice(None, int(cx)) if side == "left" else slice(int(cx), None)
            leg[:, cut] = False
            rows = [r for r in range(row, r1 + 1) if leg[r].any()]
            if not rows:
                continue
            width = {r: int((rr := runs_of(leg[r]))[:, 1].max() - rr[:, 0].min()) for r in rows}
            tail = rows[int(0.75 * len(rows)):]
            wmax = max(width[r] for r in tail)
            rb = max(r for r in rows if width[r] >= 0.5 * wmax)
            rr = runs_of(leg[rb])
            lo, hi = float(rr[:, 0].min()), float(rr[:, 1].max() - 1)
            outer, inner = (hi, lo) if side == "left" else (lo, hi)
            m[f"hem_outer_{side}"] = [outer, float(rb)]
            m[f"hem_inner_{side}"] = [inner, float(rb)]
        return m, notes, (c0, c1, r0, r1)

    tb = torso_box(mask)
    if tb is None:
        return m, ["no torso band"], (c0, c1, r0, r1)
    ba, bb, shoulder, hem_row = tb
    run = runs_of(mask[hem_row])
    hit = run[np.argmax(np.minimum(run[:, 1], bb) - np.maximum(run[:, 0], ba))]
    m["hem_right"], m["hem_left"] = [float(hit[0]), float(hem_row)], [float(hit[1] - 1), float(hem_row)]
    for side, col in (("right", c0), ("left", c1)):
        edge = max(2, int(0.01 * span))
        lo, hi = (col, col + edge) if side == "right" else (col - edge + 1, col + 1)
        m[f"cuff_{side}"] = [float(col), float(np.nonzero(mask[:, lo:hi])[0].mean())]

    slack = max(int(0.02 * span), 3)
    for side in ("right", "left"):
        out = [r for r in range(r0, hem_row + 1)
               if (mask[r, :max(ba - slack, 0)].any() if side == "right" else mask[r, bb + slack:].any())]
        if not out:
            notes.append(f"no {side} armpit")
            continue
        torso_only = [r for r in range(max(out) + 1, hem_row + 1)]
        row = min(torso_only) if torso_only else hem_row
        m[f"armpit_{side}"] = [float(ba if side == "right" else bb), float(row)]

    cols = np.arange(ba, bb + 1)
    top = np.array([np.nonzero(mask[:, c])[0].min() if mask[:, c].any() else r1 for c in cols], float)
    mid = slice(int(0.3 * len(cols)), int(0.7 * len(cols)))
    dip = mid.start + int(np.argmax(top[mid]))
    depth = top[dip] - top.min()
    if depth > 0.04 * (r1 - r0):
        thr = top.min() + 0.25 * depth
        rgt = dip - int(np.argmax(top[dip::-1] <= thr))
        lft = dip + int(np.argmax(top[dip:] <= thr))
        m["neck_right"], m["neck_left"] = [float(cols[rgt]), top[rgt]], [float(cols[lft]), top[lft]]
    else:
        notes.append("neckline hidden")
    for side, outer in (("right", ba), ("left", bb)):
        near = m.get(f"neck_{side}")
        if near is None:
            continue
        lo2, hi2 = (outer, int(near[0])) if side == "right" else (int(near[0]), outer)
        cc = np.arange(lo2, hi2 + 1)
        if len(cc) < 4:
            continue
        prof = top[cc - ba]
        m[f"shoulder_{side}"] = [float(cc[k := chord_peak(cc, prof)]), float(prof[k])]
    return m, notes, (ba, bb, shoulder, hem_row)


def torso_box(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Torso columns that reach the hem, the hem row, and the torso's own top row."""
    ys = np.nonzero(mask.any(1))[0]
    r0, r1 = int(ys.min()), int(ys.max())
    band = torso_band(mask, r0, r1)
    if band is None:
        return None
    ba, bb = band
    full = 0.8 * (bb - ba + 1)
    wide = [r for r in range(r0, r1 + 1)
            if len(rr := runs_of(mask[r, ba:bb + 1])) and (rr[:, 1] - rr[:, 0]).max() > full]
    hem_row = max(wide) if wide else r1
    # the first row the band is mostly covered, so a hood or collar never sets it
    cover = mask[:, ba:bb + 1].mean(1)
    shoulder = next((r for r in range(r0, hem_row + 1) if cover[r] > 0.5), r0)
    return ba, bb, shoulder, hem_row


def layout_box(data: dict, res: float = 0.25) -> tuple[float, float, float, float]:
    """torso_box on the front-lay silhouette, in layout cm, so the photo's box and the pattern's mean the same."""
    polys = [apply_affine(np.asarray(p["layout"]["affine"], float), np.asarray(p["outline_cm"], float))
             for p in data["panels"].values() if p["layout"]["view"] == "front" and p["kind"] == "front"]
    pts = np.concatenate(polys)
    (x0, y0), (x1, y1) = pts.min(0), pts.max(0)
    img = Image.new("L", (int(np.ceil((x1 - x0) / res)) + 1, int(np.ceil((y1 - y0) / res)) + 1), 0)
    draw = ImageDraw.Draw(img)
    for q in polys:
        draw.polygon([((x - x0) / res, (y1 - y) / res) for x, y in q], fill=1)
    tb = torso_box(np.asarray(img, bool))
    if tb is None:
        return float(x0), float(x1), float(y1), float(y0)
    ba, bb, top, hem = tb
    return float(x0 + ba * res), float(x0 + bb * res), float(y1 - top * res), float(y1 - hem * res)


def torso_pts(data: dict) -> np.ndarray:
    """Front-lay extent of the torso (or leg) panels alone, so no sleeve angle enters the registration."""
    return np.concatenate([apply_affine(np.asarray(p["layout"]["affine"], float),
                                        np.asarray(p["outline_cm"], float))
                           for p in data["panels"].values()
                           if p["layout"]["view"] == "front" and p["kind"] == "front"])


def bbox_prior(lay: tuple[float, float, float, float], box: tuple[int, int, int, int]) -> np.ndarray:
    lx0, lx1, ltop, lhem = lay
    c0, c1, r0, r1 = box
    sx = (c1 - c0) / max(lx1 - lx0, 1e-6)
    sy = (r1 - r0) / max(ltop - lhem, 1e-6)
    return np.array([[sx, 0.0], [0.0, -sy], [c0 - sx * lx0, r1 + sy * lhem]])


def band_prior(lay: tuple[float, float, float, float], box: tuple[int, int, int, int]) -> np.ndarray:
    """Upright uniform seed from the torso band width and the hem row: no top row, so no sleeve enters it."""
    lx0, lx1, _ltop, lhem = lay
    ba, bb, _top, hem = box
    s = (bb - ba) / max(lx1 - lx0, 1e-6)
    return np.array([[s, 0.0], [0.0, -s], [0.5 * (ba + bb - s * (lx0 + lx1)), hem + s * lhem]])


def apply_lin(f: np.ndarray, p: np.ndarray) -> np.ndarray:
    return np.concatenate([p, np.ones((len(p), 1))], 1) @ f


def sim_fit(src: np.ndarray, dst: np.ndarray) -> np.ndarray | None:
    """Least-squares reflected similarity layout cm -> px: one scale, one rotation, the image y flip."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows += [[x, y, 1, 0], [-y, x, 0, 1]]
        rhs += [u, v]
    try:
        a, b, tx, ty = np.linalg.lstsq(np.array(rows, float), np.array(rhs, float), rcond=None)[0]
    except (np.linalg.LinAlgError, ValueError):
        return None
    return np.array([[a, b], [b, -a], [tx, ty]])


def sim_held(src: np.ndarray, dst: np.ndarray, deg: float) -> np.ndarray | None:
    """The same fit with the rotation held, so a tilted landmark set cannot tip the whole garment."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    rows, rhs = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows += [[c * x + s * y, 1, 0], [s * x - c * y, 0, 1]]
        rhs += [u, v]
    try:
        k, tx, ty = np.linalg.lstsq(np.array(rows, float), np.array(rhs, float), rcond=None)[0]
    except (np.linalg.LinAlgError, ValueError):
        return None
    return np.array([[k * c, k * s], [k * s, -k * c], [tx, ty]])


def sim_pose(f: np.ndarray) -> tuple[float, float]:
    return math.degrees(math.atan2(f[0, 1], f[0, 0])), float(math.hypot(f[0, 0], f[0, 1]))


def sim_upright(src: np.ndarray, dst: np.ndarray) -> np.ndarray | None:
    """A flat lay is upright, so a fit that wants more than ROT_LIMIT is refitted at the limit instead."""
    f = sim_fit(src, dst)
    if f is None:
        return None
    rot = sim_pose(f)[0]
    if abs(rot) <= ROT_LIMIT:
        return f
    held = sim_held(src, dst, math.copysign(ROT_LIMIT, rot))
    return f if held is None else held


def drop_lonely(keep: set[str]) -> set[str]:
    """One side's landmarks alone tip and shift the print, so a partnerless pair member is no evidence."""
    for a, b in PAIRED:
        if (a in keep) != (b in keep):
            keep -= {a, b}
    return keep


def robust_sim(keys: list[str], src: np.ndarray, dst: np.ndarray, tol: float, prior: np.ndarray,
               span: float) -> tuple[np.ndarray, set[str]]:
    """The upright uniform map most landmark pairs agree with: two-point seeds scored by inliers, then trimmed."""
    if not keys:
        return prior, set()

    def off(f: np.ndarray) -> np.ndarray:
        return np.linalg.norm(apply_lin(f, src) - dst, axis=1)

    cands = [prior]
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if float(np.linalg.norm(src[i] - src[j])) < span:
                continue
            f = sim_fit(src[[i, j]], dst[[i, j]])
            if f is not None and abs(sim_pose(f)[0]) <= 4 * ROT_LIMIT:
                cands.append(f)
    fit = max(cands, key=lambda f: (int((off(f) < tol).sum()), -float(np.median(off(f)))))
    for _ in range(4):
        sel = off(fit) < tol
        if sel.sum() < 2:
            break
        f = sim_upright(src[sel], dst[sel])
        if f is None:
            break
        fit = f
    idx = [i for i, k in enumerate(keys) if k in (keep := drop_lonely({k for k, g in zip(keys, off(fit) < tol)
                                                                       if g}))]
    wide = len(idx) > 1 and float(np.linalg.norm(src[idx][:, None] - src[idx], axis=-1).max()) >= span
    fit = sim_upright(src[idx], dst[idx]) if wide else None
    return (fit, keep) if fit is not None else (prior, set())


def axis_fit(src: np.ndarray, dst: np.ndarray, scale: float) -> np.ndarray:
    """Upright axis-aligned map: free x and y scale, no rotation, no shear, the uniform scale where blind."""
    s, t = [scale, -scale], [0.0, 0.0]
    for k in (0, 1):
        if float(np.ptp(src[:, k])) > MIN_SPREAD_CM:
            s[k] = float(np.linalg.lstsq(np.stack([src[:, k], np.ones(len(src))], 1),
                                         dst[:, k], rcond=None)[0][0])
        t[k] = float(dst[:, k].mean() - s[k] * src[:, k].mean())
    return np.array([[s[0], 0.0], [0.0, s[1]], [t[0], t[1]]])


def torso_anchors(mask: np.ndarray, box: tuple[int, int, int, int], data: dict,
                  lay: tuple[float, float, float, float]) -> tuple:
    """Torso hem and top read the same way in both spaces: the central band carries no sleeve."""
    ba, bb, _top, hem = box
    lo, hi = ba + int(0.3 * (bb - ba)), ba + int(0.7 * (bb - ba))
    rows = np.nonzero(mask[:, lo:hi + 1].any(1))[0]
    pts = torso_pts(data)
    x0, x1 = float(pts[:, 0].min()), float(pts[:, 0].max())
    mid = pts[np.abs(pts[:, 0] - 0.5 * (x0 + x1)) <= 0.2 * (x1 - x0)]
    out = [([0.5 * (x0 + x1), lay[3]], [0.5 * (ba + bb), float(hem)])]
    if len(rows) and len(mid):
        out.append(([0.5 * (x0 + x1), float(mid[:, 1].max())], [0.5 * (lo + hi), float(rows.min())]))
    return tuple(out)


def fit_warp(layout: dict, found: dict, prior: np.ndarray, diag: float, allow: tuple[str, ...],
             uniform: bool, anchors: tuple = ()) -> tuple[object, str, list[str], float, np.ndarray]:
    """Layout cm -> cutout px: an upright similarity for tops, the trimmed affine for bottoms, then TPS."""
    keys = [k for k in layout if k in found and k in allow]
    src = np.array([layout[k] for k in keys], float).reshape(-1, 2)
    dst = np.array([found[k] for k in keys], float).reshape(-1, 2)
    span = SPAN_FRAC * float(np.ptp(src[:, 0])) if len(src) else 0.0
    if uniform:
        lin, keep = robust_sim(keys, src, dst, TOL_FRAC * diag, prior, span)
        mode = "similarity"
        hold = [i for i, k in enumerate(keys) if k in keep]
        # the uniform fit rejects its own outliers, then the torso top carries the height it cannot see
        if anchors:
            ax = axis_fit(np.concatenate([src[hold], [a[0] for a in anchors]]),
                          np.concatenate([dst[hold], [a[1] for a in anchors]]), sim_pose(lin)[1])
            ratio = abs(ax[0, 0] / ax[1, 1]) if ax[1, 1] else 0.0
            if 1 / RATIO_MAX <= ratio <= RATIO_MAX:
                lin, mode = ax, "upright"
    else:
        lin, mode = prior, "affine"
        for _ in range(4):
            off = np.linalg.norm(apply_lin(lin, src) - dst, axis=1)
            sel = off < min(max(0.08 * diag, 1.5 * float(np.median(off))), 0.25 * diag)
            if sel.sum() < 3:
                break
            lin = np.linalg.lstsq(np.concatenate([src[sel], np.ones((int(sel.sum()), 1))], 1),
                                  dst[sel], rcond=None)[0]
        keep = drop_lonely({k for k, e in zip(keys, np.linalg.norm(apply_lin(lin, src) - dst, axis=1))
                            if e < KEEP_FRAC * diag})
        idx = [i for i, k in enumerate(keys) if k in keep]
        if len(idx) >= 3:
            lin = np.linalg.lstsq(np.concatenate([src[idx], np.ones((len(idx), 1))], 1), dst[idx],
                                  rcond=None)[0]
        else:
            lin, keep = prior, set()
    used = [k for k in keys if k in keep]
    idx = [i for i, k in enumerate(keys) if k in keep]
    cm = math.sqrt(max(abs(np.linalg.det(lin[:2])), 1e-9))
    rms = float(np.sqrt((np.linalg.norm(apply_lin(lin, src[idx]) - dst[idx], axis=1) ** 2).mean())) / cm \
        if idx else float("nan")
    if len(idx) < TPS_MIN:
        return (lambda p: apply_lin(lin, p)), (mode if idx or mode == "upright" else "prior"), used, rms, lin
    s, d = src[idx], dst[idx]
    lo, hi = s.min(0), s.max(0)
    pad = 0.4 * np.maximum(hi - lo, 1.0)
    box = np.array([[lo[0] - pad[0], lo[1] - pad[1]], [hi[0] + pad[0], lo[1] - pad[1]],
                    [lo[0] - pad[0], hi[1] + pad[1]], [hi[0] + pad[0], hi[1] + pad[1]]])
    # a spline chases bad landmarks, so it is smoothed at the scale of the residuals it was fitted on
    rbf = RBFInterpolator(np.concatenate([s, box]), np.concatenate([d, apply_lin(lin, box)]),
                          kernel="thin_plate_spline", degree=1,
                          smoothing=1.0 if rms <= TPS_RMS_CM else (rms * cm) ** 2)

    def warp(p: np.ndarray) -> np.ndarray:
        return np.concatenate([rbf(p[i:i + 400000]) for i in range(0, len(p), 400000)]) if len(p) else p

    return warp, "tps", used, rms, lin


def sleeve_axis(data: dict, name: str, cuff: list | None) -> np.ndarray | None:
    """The panel's own armhole centre and cuff centre in layout cm: its grain axis, whatever the arm pose."""
    p = data["panels"][name]
    a = np.asarray(p["layout"]["affine"], float)
    ends = {}
    for lab in ("armhole", "hem"):
        polys = [np.asarray(e["polyline_cm"], float) for e in p["edges"] if e["label"] == lab]
        if polys:
            ends[lab] = apply_affine(a, np.concatenate(polys)).mean(0)
    if "armhole" not in ends or ("hem" not in ends and cuff is None):
        return None
    return np.stack([ends["armhole"], ends.get("hem", np.asarray(cuff, float))])


def sleeve_sim(data: dict, name: str, warp, layout: dict, found: dict, side: str,
               scale: float) -> np.ndarray | None:
    """Per-sleeve map pinned at the armhole the torso warp already placed, onto the photo's own sleeve axis."""
    cuff = found.get(f"cuff_{side}")
    src = sleeve_axis(data, name, layout.get(f"cuff_{side}"))
    if cuff is None or src is None or float(np.linalg.norm(src[1] - src[0])) < 4.0:
        return None
    seam = [layout[k] for k in (f"shoulder_{side}", f"armpit_{side}") if k in layout]
    hole = np.mean(seam, 0)[None] if len(seam) == 2 else src[:1]
    dst = np.stack([warp(hole)[0], np.asarray(cuff, float)])
    s = float(np.linalg.norm(dst[1] - dst[0])) / float(np.linalg.norm(src[1] - src[0]))
    if not SLEEVE_SCALE[0] * scale <= s <= SLEEVE_SCALE[1] * scale:
        return None
    return sim_fit(src, dst)


def warp_jac(warp, p: np.ndarray, h: float = 0.5) -> np.ndarray:
    """Local layout cm -> px linear part by central differences, so a spline reports like a matrix."""
    q = warp(np.array([[p[0] - h, p[1]], [p[0] + h, p[1]], [p[0], p[1] - h], [p[0], p[1] + h]], float))
    return np.stack([(q[1] - q[0]) / (2 * h), (q[3] - q[2]) / (2 * h)], 1)


def warp_pose(j: np.ndarray) -> tuple[float, float, float]:
    """Rotation deg and both scales of that linear part, with the layout-to-image y flip undone."""
    u, s, vt = np.linalg.svd(j * np.array([1.0, -1.0]))
    r = u @ vt
    # a map that does not flip y is not a flat lay at all, so it reports as fully turned over
    rot = math.degrees(math.atan2(r[1, 0], r[0, 0])) if float(np.linalg.det(j)) < 0 else 180.0
    return rot, float(s[0]), float(s[1])


def unwarp(warp, target: np.ndarray, start: np.ndarray, steps: int = 6) -> np.ndarray:
    """Layout cm of a pixel: Newton steps on the warp, so the spline inverts as well as the linear part."""
    q = np.asarray(start, float)
    for _ in range(steps):
        j = warp_jac(warp, q)
        if abs(float(np.linalg.det(j))) < 1e-9:
            break
        q = q + np.linalg.solve(j, np.asarray(target, float) - warp(q[None])[0])
    return q


def panel_cover(data: dict, names: set[str], quad: np.ndarray, res: float = 0.25) -> float | None:
    """Share of a print area in layout cm that lands on these panels' front-lay outlines."""
    polys = [apply_affine(np.asarray(p["layout"]["affine"], float), np.asarray(p["outline_cm"], float))
             for n, p in data["panels"].items() if n in names and p["layout"]["affine"]]
    if not polys:
        return None
    pts = np.concatenate(polys + [quad])
    f = frame_of([pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()], 1.0 / res)
    hit = np.zeros((f["h"], f["w"]), bool)
    for q in polys:
        hit |= frame_mask(f, q)
    area = frame_mask(f, quad)
    return round(float((area & hit).sum()) / max(int(area.sum()), 1), 3)


def print_px(box: tuple[int, int, int, int], marks: dict, upper: bool) -> list[float]:
    """The lay's own print area when the spec names no placement box: the chest, or the front of a leg."""
    ba, bb, top, hem = box
    if upper:
        rows = [marks[k][1] for k in ("armpit_left", "armpit_right") if k in marks]
        return [0.5 * (ba + bb), 0.5 * (hem + (min(rows) if rows else top + 0.45 * (hem - top)))]
    a = marks.get("waist_left", [0.5 * (ba + bb), float(top)])
    b = marks.get("hem_inner_left", marks.get("hem_outer_left", [float(bb), float(hem)]))
    return [0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1])]


def register(data: dict, warp, probes: list[dict], upper: bool) -> list[dict]:
    """Where each print area lands in layout cm, and whether the map is upright and uniform getting there."""
    marks = data["landmarks"]["front"]
    low = [marks[k][1] for k in ("armpit_left", "armpit_right") if k in marks]
    high = [marks[k][1] for k in ("neck_left", "neck_right") if k in marks]
    out = []
    for pr in probes:
        q = unwarp(warp, np.asarray(pr["px"], float), np.asarray(pr["start"], float))
        j = warp_jac(warp, q)
        rot, s0, s1 = warp_pose(j)
        quad = q + (np.asarray(pr["poly"], float) - np.asarray(pr["px"], float)) @ np.linalg.inv(j).T
        chest = None
        if upper and low and high and pr["high"]:
            slack = CHEST_SLACK * (max(high) - min(low))
            chest = bool(min(low) - slack <= q[1] <= max(high) + slack)
        out.append({"what": pr["what"], "cm": [round(float(v), 1) for v in q], "rot_deg": round(rot, 2),
                    "ratio": round(max(s0, s1) / max(min(s0, s1), 1e-9), 3),
                    "px_per_cm": round(0.5 * (s0 + s1), 2), "chest": chest,
                    "cover": panel_cover(data, pr["panels"], quad)})
    return out


def flatten_shading(img: np.ndarray, valid: np.ndarray, size: int) -> np.ndarray:
    """Drop the photo's leftover fold shading so quilted patches do not show their seams."""
    m = valid.astype(np.float32)
    den = ndimage.uniform_filter(ndimage.uniform_filter(m, size), size)
    low = np.stack([ndimage.uniform_filter(ndimage.uniform_filter(img[..., k] * m, size), size)
                    / np.maximum(den, 1e-6) for k in range(3)], -1)
    return img - low + np.median(low[valid], axis=0)


def quilt(src: np.ndarray, valid: np.ndarray, shape: tuple[int, int], rng: np.random.Generator,
          fill: np.ndarray) -> np.ndarray:
    """Image quilting with feathered min-error-pick overlaps, drawn from the valid part of the photo."""
    h, w = shape
    p = min(PATCH, max(src.shape[0] // 2, 8), max(src.shape[1] // 2, 8))
    ov = max(min(OVERLAP, p // 4), 2)
    s = np.pad(valid.astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    cnt = s[p:, p:] - s[:-p, p:] - s[p:, :-p] + s[:-p, :-p]
    ys, xs = np.nonzero(cnt >= p * p * 0.995)
    if not len(ys):
        return np.broadcast_to(fill.astype(np.float32), (h, w, 3)).copy()
    pick = rng.choice(len(ys), min(POOL, len(ys)), replace=len(ys) < POOL)
    pool = np.stack([src[ys[k]:ys[k] + p, xs[k]:xs[k] + p] for k in pick]).astype(np.float32)
    step = p - ov
    out = np.zeros((h + p, w + p, 3), np.float32)
    ramp = np.linspace(0, 1, ov, dtype=np.float32)
    for i in range(0, h, step):
        for j in range(0, w, step):
            idx = rng.choice(len(pool), min(CANDS, len(pool)), replace=False)
            cand = pool[idx]
            cost = np.zeros(len(cand), np.float32)
            if i:
                cost += ((cand[:, :ov] - out[i:i + ov, j:j + p]) ** 2).sum((1, 2, 3))
            if j:
                cost += ((cand[:, :, :ov] - out[i:i + p, j:j + ov]) ** 2).sum((1, 2, 3))
            tile = cand[int(np.argmin(cost))]
            wgt = np.ones((p, p, 1), np.float32)
            if i:
                wgt[:ov] *= ramp[:, None, None]
            if j:
                wgt[:, :ov] *= ramp[None, :, None]
            out[i:i + p, j:j + p] = out[i:i + p, j:j + p] * (1 - wgt) + tile * wgt
    return out[:h, :w]


def set_normal(direction: StripeDirection, grain: np.ndarray) -> np.ndarray:
    if direction == StripeDirection.grain:
        return np.array([-grain[1], grain[0]])
    if direction == StripeDirection.cross:
        return grain.copy()
    c = math.cos(math.pi / 4)
    return np.array([c * grain[0] - c * grain[1], c * grain[0] + c * grain[1]])


def wave_cover(u: np.ndarray, half: float, period: float, width: float, offset: float) -> np.ndarray:
    """Exact box-filtered coverage of a periodic line pattern over a pixel footprint of 2*half."""
    def mass(x: np.ndarray) -> np.ndarray:
        q = (x - offset) / period
        k = np.floor(q)
        return k * width + np.clip((q - k) * period, 0, width)

    return np.clip((mass(u + half) - mass(u - half)) / (2 * half), 0, 1)


def spanning_tree(data: dict, root: str) -> tuple[list[dict], list[dict]]:
    usable = []
    for st in data["stitches"]:
        a, b = st["a"]["panel"], st["b"]["panel"]
        if a == b or st["label"] == "dart":
            continue
        if data["panels"][a]["rib"] or data["panels"][b]["rib"]:
            continue
        if data["panels"][a]["edges"][st["a"]["edge"]]["length_mismatch"]:
            continue
        usable.append(st)
    seen, tree, rest = {root}, [], []
    todo = sorted(usable, key=lambda s: -PRIORITY.get(s["label"], 1))
    while True:
        nxt = next((s for s in todo if (s["a"]["panel"] in seen) != (s["b"]["panel"] in seen)), None)
        if nxt is None:
            break
        seen.add(nxt["a"]["panel"])
        seen.add(nxt["b"]["panel"])
        tree.append(nxt)
        todo.remove(nxt)
    rest = [s for s in todo if s["a"]["panel"] in seen and s["b"]["panel"] in seen]
    return tree, rest


def seam_u(data: dict, side: dict, normals: dict, flip: bool, n: int) -> np.ndarray:
    poly = np.asarray(data["panels"][side["panel"]]["edges"][side["edge"]]["polyline_cm"], float)
    frac = np.linspace(0, 1, n)
    pts = along(poly, 1 - frac if flip else frac)
    return pts @ normals[side["panel"]]


def circ_mean(d: np.ndarray, period: float) -> float:
    z = np.exp(2j * np.pi * d / period).mean()
    return float(np.angle(z) * period / (2 * np.pi))


def circ_spread(d: np.ndarray, period: float) -> float:
    z = np.exp(2j * np.pi * d / period).mean()
    return float(np.sqrt(max(-2 * np.log(max(abs(z), 1e-9)), 0.0)) * period / (2 * np.pi))


def phase_offsets(data: dict, repeats: list, root: str) -> tuple[list[dict], dict]:
    """One offset per stripe set per panel so the pattern lines up across every seam of the tree."""
    tree, rest = spanning_tree(data, root)
    out, info = [], {"root": root, "tree": [f"{s['a']['panel']}|{s['b']['panel']}|{s['label']}" for s in tree],
                     "sets": []}
    for rep in repeats:
        normals = {}
        for name, p in data["panels"].items():
            nrm = set_normal(rep.direction, np.asarray(p["grain_axis"], float))
            a = p["layout"]["affine"]
            lay = np.asarray(a, float)[:, :2] @ nrm if a else nrm
            normals[name] = (nrm, lay / max(float(np.linalg.norm(lay)), 1e-9))
        ref = normals[root][1]
        normals = {k: (-v[0] if float(v[1] @ ref) < 0 else v[0]) for k, v in normals.items()}
        off = {name: 0.0 for name in data["panels"]}
        period = rep.period_cm
        done = {root}
        for st in tree:
            known, new = (st["a"], st["b"]) if st["a"]["panel"] in done else (st["b"], st["a"])
            done.add(new["panel"])
            length = data["panels"][known["panel"]]["edges"][known["edge"]]["length_cm"]
            n = max(int(length / SEAM_STEP_CM) + 1, 3)
            ua = seam_u(data, known, normals, False, n)
            ub = seam_u(data, new, normals, st["reversed"], n)
            off[new["panel"]] = off[known["panel"]] - circ_mean(ua - ub, period)
        worst_tree, worst_rest, spread, where = 0.0, 0.0, 0.0, "-"
        for st, store in [(s, True) for s in tree] + [(s, False) for s in rest]:
            length = data["panels"][st["a"]["panel"]]["edges"][st["a"]["edge"]]["length_cm"]
            n = max(int(length / SEAM_STEP_CM) + 1, 3)
            d = (seam_u(data, st["a"], normals, False, n) - off[st["a"]["panel"]]) - \
                (seam_u(data, st["b"], normals, st["reversed"], n) - off[st["b"]["panel"]])
            r = abs(circ_mean(d, period)) / period
            if store:
                worst_tree = max(worst_tree, r)
                sp = circ_spread(d, period) / period
                if sp > spread:
                    spread, where = sp, st["label"]
            else:
                worst_rest = max(worst_rest, r)
        out.append({"offsets": off, "normals": normals})
        info["sets"].append({"period_cm": period, "direction": rep.direction.value,
                             "tree_residual": round(worst_tree, 5), "tree_spread": round(spread, 4),
                             "spread_at": where, "worst_free_residual": round(worst_rest, 4)})
    return out, info


def trim_targets(data: dict, trim, garment: str) -> list[tuple[str, str]]:
    """Panels that carry this trim, each with the edge label its distance field is measured from."""
    pl = trim.placement.value
    if pl in SEAM_PLACEMENTS or pl in ("hem", "waist"):
        return [(n, pl) for n, p in data["panels"].items() if any(e["label"] == pl for e in p["edges"])]
    if pl == "cuff":
        cuffs = [n for n, p in data["panels"].items() if p["kind"] == "cuff"]
        if cuffs:
            return [(n, "hem") for n in cuffs if any(e["label"] == "hem" for e in data["panels"][n]["edges"])]
        want = ("front", "back") if garment == "bottom" else ("sleeve",)
        return [(n, "hem") for n, p in data["panels"].items()
                if p["kind"] in want and any(e["label"] == "hem" for e in p["edges"])]
    return []


def band_spans(trim) -> tuple[list[tuple[float, float]], float]:
    w = list(trim.widths_cm)
    gap = trim.gap_cm
    if trim.placement.value in SEAM_PLACEMENTS:
        total = sum(w) + gap * (len(w) - 1)
        start = -total / 2
    else:
        total = sum(w) + gap * len(w)
        start = gap
    spans = []
    for width in w:
        spans.append((start, start + width))
        start += width + gap
    return spans, total


def scan_bands(s: np.ndarray, covs: list[np.ndarray], f: dict, poly: np.ndarray) -> list[float]:
    """Band widths in cm at the seam's midpoint: coverage times the sub-pixel share that lies on this panel."""
    q = resample(poly, 0.4)
    mid = along(q, np.array([0.5]))[0]
    k = max(min(int(0.5 * (len(q) - 1)), len(q) - 2), 0)
    tan = q[k + 1] - q[k]
    tan = tan / max(float(np.linalg.norm(tan)), 1e-9)
    e = 1.0 / f["ppc"]
    if abs(tan[1]) >= abs(tan[0]):
        row = int(np.clip((f["y1"] - mid[1]) * f["ppc"], 0, f["h"] - 1))
        line, cut, step = s[row], [c[row] for c in covs], e * abs(tan[1])
    else:
        col = int(np.clip((mid[0] - f["x0"]) * f["ppc"], 0, f["w"] - 1))
        line, cut, step = s[:, col], [c[:, col] for c in covs], e * abs(tan[0])
    mine = np.clip(line / e + 0.5, 0, 1)
    return [round(float((c * mine).sum() * step), 3) for c in cut]


def band_sign(p: dict, placement: str) -> float:
    if placement in ("center_front", "center_back"):
        return -1.0 if p["side"] == "right" else 1.0
    return -1.0 if p["layout"]["view"] != "back" else 1.0


def render_panel(name: str, p: dict, ctx: dict) -> dict:
    f = frame_of(p["bbox_cm"], ctx["ppc"])
    xs, ys = frame_xy(f)
    pts = np.stack([xs.ravel(), ys.ravel()], 1)
    outline = np.asarray(p["outline_cm"], float)
    inside = frame_mask(f, outline)
    ground = ctx["ground"]
    tone = ctx["rib_color"].get(p["kind"] if p["rib"] else "collar" if p["kind"] == "collar" else "")
    if tone is not None:
        ground = tone
    solid = p["rib"] or tone is not None
    rgb = np.broadcast_to(ground.astype(np.float32), (f["h"], f["w"], 3)).copy()
    mode = "pattern"

    sets = []
    if not solid:
        for k, rep in enumerate(ctx["repeats"]):
            phase = ctx["phase"][k]
            nrm = phase["normals"][name]
            u = (pts @ nrm).reshape(f["h"], f["w"]) - phase["offsets"][name]
            half = 0.5 * (abs(nrm[0]) + abs(nrm[1])) / f["ppc"]
            cols = [hex_rgb(c.hex) for c in rep.colors] or [ground]
            if rep.period_cm < ctx["collapse"]:
                a = np.full((f["h"], f["w"]), min(rep.line_width_cm / rep.period_cm, 1.0), np.float32)
                c = np.broadcast_to(np.mean(cols, 0).astype(np.float32), (f["h"], f["w"], 3))
            else:
                a = np.zeros((f["h"], f["w"]), np.float32)
                c = np.zeros((f["h"], f["w"], 3), np.float32)
                big = rep.period_cm * len(cols)
                for i, col in enumerate(cols):
                    cv = wave_cover(u, half, big, rep.line_width_cm, rep.offset_cm + i * rep.period_cm)
                    a += cv
                    c += cv[..., None] * col
                c = c / np.maximum(a, 1e-6)[..., None]
                a = np.clip(a, 0, 1)
            sets.append((a, c))
    if sets:
        keep = np.ones((f["h"], f["w"]), np.float32)
        acc = np.zeros((f["h"], f["w"], 3), np.float32)
        tot = np.zeros((f["h"], f["w"]), np.float32)
        for a, c in sets:
            keep *= 1 - a
            acc += a[..., None] * c
            tot += a
        rgb = (keep[..., None] * ground + acc) / np.maximum(keep + tot, 1e-6)[..., None]

    cut = None
    if name in ctx["warps"]:
        lay = apply_affine(np.asarray(p["layout"]["affine"], float), pts)
        cut = ctx["warps"][name](lay)
        if ctx["tint"] is not None:
            on = sample_rgb(ctx["alpha"][..., None].astype(np.float32), cut)
            tint = 1 + (sample_rgb(ctx["tint"][..., None], cut) - 1) * (on > 0.5)
            rgb = rgb * tint.reshape(f["h"], f["w"], 1)

    if ctx["fallback"] and not p["rib"]:
        mode = "fallback"
        if "scaled" not in ctx:
            src, valid = ctx["source"]
            scale = f["ppc"] / ctx["photo_ppc"]
            sh = (max(int(src.shape[0] * scale), PATCH + 4), max(int(src.shape[1] * scale), PATCH + 4))
            big = np.asarray(Image.fromarray(src.astype(np.uint8)).resize(
                (sh[1], sh[0]), Image.Resampling.LANCZOS), np.float32)
            vm = np.asarray(Image.fromarray((valid * 255).astype(np.uint8)).resize(
                (sh[1], sh[0]), Image.Resampling.NEAREST)) > 200
            ctx["scaled"] = (flatten_shading(big, vm, 4 * PATCH), vm)
        rgb = quilt(*ctx["scaled"], (f["h"], f["w"]), ctx["rng"], ground)
        if cut is not None:
            cover = sample_rgb(ctx["alpha"][..., None].astype(np.float32), cut).reshape(f["h"], f["w"])
            cover = np.clip(ndimage.gaussian_filter(np.where(cover > 0.5, 1.0, 0.0), 1.0), 0, 1)[..., None]
            ph, pw = ctx["albedo"].shape[:2]
            for pm in ctx["placements"]:
                if name in pm["panels"]:
                    continue
                bx = [pm["box"][0] * pw, pm["box"][1] * ph, pm["box"][2] * pw, pm["box"][3] * ph]
                off = np.minimum.reduce([cut[:, 0] - bx[0], bx[2] - cut[:, 0],
                                         cut[:, 1] - bx[1], bx[3] - cut[:, 1]])
                cover = cover * np.clip(-off / 1.5 + 0.5, 0, 1).reshape(f["h"], f["w"], 1)
            photo = sample_rgb(ctx["albedo"], cut).reshape(f["h"], f["w"], 3)
            rgb = photo * cover + rgb * (1 - cover)

    bands_report = {}
    for trim in ctx["trims"]:
        if not trim.widths_cm or not trim.colors:
            continue
        label = dict(ctx["trim_targets"][id(trim)]).get(name)
        if label is None:
            continue
        polys = [np.asarray(e["polyline_cm"], float) for e in p["edges"] if e["label"] == label]
        if not polys:
            continue
        spans, total = band_spans(trim)
        reach = total + 1.0
        s = signed_distance(polys, f, reach, inside)
        t = band_sign(p, trim.placement.value) * s if trim.placement.value in SEAM_PLACEMENTS else s
        gate = np.ones((f["h"], f["w"]), np.float32)
        if trim.extent.value != "full" and p["extent_split_cm"] is not None:
            up = (pts @ np.asarray(p["up"], float)).reshape(f["h"], f["w"]) - p["extent_split_cm"]
            e = 1.0 / f["ppc"]
            gate = np.clip(up / e + 0.5, 0, 1) if trim.extent.value == "upper" else np.clip(-up / e + 0.5, 0, 1)
        e = 1.0 / f["ppc"]
        covs = []
        for i, (lo, hi) in enumerate(spans):
            cov = np.clip((t - lo) / e + 0.5, 0, 1) * np.clip((hi - t) / e + 0.5, 0, 1) * gate
            col = hex_rgb(trim.colors[i % len(trim.colors)].hex).astype(np.float32)
            rgb = rgb * (1 - cov[..., None]) + col * cov[..., None]
            covs.append(cov)
        bands_report[trim.placement.value] = scan_bands(s, covs, f, polys[0])

    for pm in ctx["placements"]:
        if name not in pm["panels"] or cut is None:
            continue
        h, w = ctx["albedo"].shape[:2]
        bx = [pm["box"][0] * w, pm["box"][1] * h, pm["box"][2] * w, pm["box"][3] * h]
        d = np.minimum.reduce([cut[:, 0] - bx[0], bx[2] - cut[:, 0], cut[:, 1] - bx[1], bx[3] - cut[:, 1]])
        on = sample_rgb(ctx["alpha"][..., None].astype(np.float32), cut)[:, 0]
        a = np.clip(d / 1.5 + 0.5, 0, 1) * np.clip(on, 0, 1)
        a = a.reshape(f["h"], f["w"], 1)
        rgb = sample_rgb(ctx["albedo"], cut).reshape(f["h"], f["w"], 3) * a + rgb * (1 - a)

    rgb = np.clip(np.nan_to_num(rgb, nan=float(ground.mean())), 0, 255).astype(np.float32)
    return {"rgb": rgb, "x0": f["x0"], "y1": f["y1"], "ppc": f["ppc"], "rib": bool(p["rib"]),
            "kind": p["kind"], "mode": mode, "bands": bands_report}


def sheets(data: dict) -> list[dict]:
    placed = []
    for view in ("front", "back"):
        for name, p in data["panels"].items():
            if p["layout"]["view"] == view:
                placed.append({"name": name, "panel": p, "view": view,
                               "A": np.asarray(p["layout"]["affine"], float)})
    spans = {}
    for view in ("front", "back"):
        mine = [i for i in placed if i["view"] == view]
        pts = np.concatenate([apply_affine(i["A"], np.asarray(i["panel"]["outline_cm"], float))
                              for i in mine]) if mine else np.zeros((1, 2))
        spans[view] = (float(pts[:, 0].min()), float(pts[:, 0].max()))
    gap = 12.0
    shift = {"front": 0.0, "back": spans["front"][1] - spans["back"][0] + gap}
    for item in placed:
        item["A"] = item["A"] + np.array([[0, 0, shift[item["view"]]], [0, 0, 0]], float)
    cursor = spans["back"][1] + shift["back"] + gap
    top = max((apply_affine(i["A"], np.asarray(i["panel"]["outline_cm"], float))[:, 1].max()
               for i in placed), default=0.0)
    for name, p in data["panels"].items():
        if p["layout"]["view"] is not None:
            continue
        out = np.asarray(p["outline_cm"], float)
        placed.append({"name": name, "panel": p, "view": None,
                       "A": np.array([[1, 0, cursor - out[:, 0].min()], [0, 1, top - out[:, 1].max()]], float)})
        cursor += float(out[:, 0].max() - out[:, 0].min()) + gap
    for item in placed:
        item["outline"] = apply_affine(item["A"], np.asarray(item["panel"]["outline_cm"], float))
    return placed


def preview(data: dict, rasters: dict, cutout: np.ndarray, marks: dict, used: list[str],
            title: str) -> Image.Image:
    placed = sheets(data)
    allpts = np.concatenate([i["outline"] for i in placed])
    x0, x1 = float(allpts[:, 0].min()), float(allpts[:, 0].max())
    y0, y1 = float(allpts[:, 1].min()), float(allpts[:, 1].max())
    pad, s = 6.0, PREVIEW_PPC
    w = int((x1 - x0 + 2 * pad) * s)
    h = int((y1 - y0 + 2 * pad) * s)
    canvas = Image.new("RGB", (w + THUMB, max(h, THUMB)), (255, 255, 255))
    sheet = np.full((h, w, 3), 255, np.float32)

    for item in placed:
        ras = rasters.get(item["name"])
        if ras is None:
            continue
        poly = np.stack([(item["outline"][:, 0] - x0 + pad) * s, (y1 + pad - item["outline"][:, 1]) * s], 1)
        c0, c1 = max(int(poly[:, 0].min()) - 1, 0), min(int(poly[:, 0].max()) + 2, w)
        r0, r1 = max(int(poly[:, 1].min()) - 1, 0), min(int(poly[:, 1].max()) + 2, h)
        if c1 <= c0 or r1 <= r0:
            continue
        mask = Image.new("L", (c1 - c0, r1 - r0), 0)
        ImageDraw.Draw(mask).polygon([(px - c0, py - r0) for px, py in poly], fill=255, outline=255)
        gx, gy = np.meshgrid(np.arange(c0, c1) + 0.5, np.arange(r0, r1) + 0.5)
        lay = np.stack([gx.ravel() / s + x0 - pad, y1 + pad - gy.ravel() / s], 1)
        m = np.linalg.inv(item["A"][:, :2])
        loc = (lay - item["A"][:, 2]) @ m.T
        cc = np.clip(((loc[:, 0] - ras["x0"]) * ras["ppc"]).astype(int), 0, ras["rgb"].shape[1] - 1)
        rr = np.clip(((ras["y1"] - loc[:, 1]) * ras["ppc"]).astype(int), 0, ras["rgb"].shape[0] - 1)
        patch = ras["rgb"][rr, cc].reshape(r1 - r0, c1 - c0, 3)
        sel = np.asarray(mask) > 127
        sheet[r0:r1, c0:c1][sel] = patch[sel]

    img = Image.fromarray(sheet.round().clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for item in placed:
        for e in item["panel"]["edges"]:
            line = apply_affine(item["A"], np.asarray(e["polyline_cm"], float))
            px = [((a - x0 + pad) * s, (y1 + pad - b) * s) for a, b in line]
            d.line(px, fill=LABEL_COLORS.get(e["label"], (150, 150, 150)), width=1)
        c = item["outline"].mean(0)
        d.text(((c[0] - x0 + pad) * s - 3 * len(item["name"]), (y1 + pad - c[1]) * s),
               item["name"], fill=(0, 0, 0))
    d.text((6, 6), title, fill=(0, 0, 0))
    canvas.paste(img, (0, 0))

    k = THUMB / max(cutout.shape[:2])
    thumb = Image.fromarray(cutout[..., :3]).resize((int(cutout.shape[1] * k), int(cutout.shape[0] * k)),
                                                    Image.Resampling.LANCZOS)
    td = ImageDraw.Draw(thumb)
    for key, pt in marks.items():
        a, b = pt[0] * k, pt[1] * k
        col = (0, 230, 0) if key in used else (255, 0, 0)
        td.ellipse([a - 4, b - 4, a + 4, b + 4], outline=col, width=2)
        td.text((a + 5, b - 5), key, fill=col)
    canvas.paste(thumb, (w, 0))
    return canvas


def synthesize(item_dir: Path, out_dir: Path, *, ppc: float = PPC, collapse_period_cm: float = 0.0,
               spec: PatternSpec | None = None, write: bool = True) -> dict:
    t0 = time.time()
    stress = spec is not None
    spec = spec or PatternSpec.model_validate_json((item_dir / "spec.json").read_text())
    data = json.loads((out_dir / "panels.json").read_text())
    albedo = np.asarray(Image.open(item_dir / "albedo.png").convert("RGBA"))
    mask = albedo[..., 3] > 127
    meta = json.loads((item_dir / "spec_meta.json").read_text()) if (item_dir / "spec_meta.json").exists() else {}
    photo_ppc = float((meta.get("calibration") or {}).get("px_per_cm") or 10.0)
    item = json.loads((item_dir / "item.json").read_text())
    back_photo = any((im.get("view") or "") == "back" for im in item.get("listing", {}).get("images", []))

    near = ndimage.distance_transform_edt(~mask, return_distances=False, return_indices=True)
    photo = albedo[..., :3][tuple(near)].astype(np.float32)
    base = hex_rgb(spec.base_color.hex)
    ground, like, like_frac = calibrate(albedo, mask, base)
    tint = tint_field(albedo, mask, like)
    marks, mark_notes, box = detect_marks(mask, data["garment"])
    lay_marks = dict(data["landmarks"]["front"])
    upper = data["garment"] == "upper"
    allow = TORSO_MARKS if upper else tuple(lay_marks)
    pts = torso_pts(data)
    lay = layout_box(data) if upper else (
        float(pts[:, 0].min()), float(pts[:, 0].max()), float(pts[:, 1].max()), float(pts[:, 1].min()))
    ys0, xs0 = np.nonzero(mask)
    diag = float(np.hypot(np.ptp(xs0), np.ptp(ys0)))
    prior = band_prior(lay, box) if upper else bbox_prior(lay, box)
    anchors = torso_anchors(mask, box, data, lay) if upper else ()
    warp, warp_mode, used, rms, lin = fit_warp(lay_marks, marks, prior, diag, allow, upper, anchors)
    scale = sim_pose(lin)[1] if upper else math.sqrt(max(abs(np.linalg.det(lin[:2])), 1e-9))
    # a torso band that disagrees with the photo's own scale is a crumpled lay, not a registration
    reg_ok = not upper or SCALE_GATE[0] <= scale / max(photo_ppc, 1e-6) <= SCALE_GATE[1]
    mark_notes += [f"dropped {k}" for k in marks if k not in used and k in allow]
    if not reg_ok:
        mark_notes.append(f"no registration: {scale:.1f} vs {photo_ppc:.1f} px/cm")

    rib_color = {}
    for trim in spec.trims:
        if trim.kind in (TrimKind.cuff, TrimKind.waistband, TrimKind.collar) and trim.colors:
            rib_color[trim.kind.value] = hex_rgb(trim.colors[0].hex)

    # placement region -> the panel kind and wearer's side it lands on; a print never reaches the back
    region = {"front": ("front", None), "other": ("front", None),
              "left_leg": ("front", "left"), "right_leg": ("front", "right"),
              "left_sleeve": ("sleeve", "left"), "right_sleeve": ("sleeve", "right"),
              "hood": ("hood", None), "back": (None, None)}
    placements = []
    for pm in spec.placements:
        kind, side = region.get(pm.panel.value, region["other"])
        hit = {n for n, p in data["panels"].items()
               if kind and p["kind"] == kind and (side is None or p["side"] == side)
               and (p["layout"]["view"] == "front" or kind == "hood")}
        placements.append({"box": pm.box, "kind": pm.kind.value, "panels": hit, "what": pm.panel.value})

    source_valid = mask.copy()
    h, w = mask.shape
    for pm in spec.placements:
        b = [int(pm.box[0] * w) - 8, int(pm.box[1] * h) - 8, int(pm.box[2] * w) + 8, int(pm.box[3] * h) + 8]
        source_valid[max(b[1], 0):max(b[3], 0), max(b[0], 0):max(b[2], 0)] = False

    fallback = spec.kind.value in ("graphic", "camo", "floral", "other")
    root = max((n for n, p in data["panels"].items() if p["kind"] == "front" and not p["rib"]),
               key=lambda n: np.prod(np.asarray(data["panels"][n]["bbox_cm"][2:])
                                     - np.asarray(data["panels"][n]["bbox_cm"][:2])), default=None)
    root = root or next(iter(data["panels"]))
    phase, phase_info = phase_offsets(data, spec.repeats, root)

    # the torso warp is fitted on torso landmarks only: the sleeve lay angle is the seller's, not the sim's
    warps = {n: warp for n, p in data["panels"].items()
             if reg_ok and p["kind"] == "front" and p["layout"]["view"] == "front"}
    for side in ("left", "right"):
        want = {n for n, p in data["panels"].items()
                if p["kind"] == "sleeve" and p["side"] == side and p["layout"]["view"] == "front"
                and (fallback or any(n in pm["panels"] for pm in placements))}
        for n in want:
            arm = sleeve_sim(data, n, warp, lay_marks, marks, side, scale) if reg_ok and upper else None
            if arm is None:
                mark_notes.append(f"{n} synthesised")
                continue
            warps[n] = lambda p, f=arm: apply_lin(f, p)

    targets = {id(t): trim_targets(data, t, data["garment"]) for t in spec.trims}
    ctx = {"ppc": ppc, "collapse": collapse_period_cm, "ground": ground, "rib_color": rib_color,
           "repeats": spec.repeats, "phase": phase, "trims": spec.trims, "trim_targets": targets,
           "placements": placements, "warps": warps, "albedo": photo,
           "tint": tint if warp_mode == "tps" else None,
           "alpha": mask, "fallback": fallback, "photo_ppc": photo_ppc,
           "source": (photo, source_valid),
           "quilt_cache": {}, "rng": np.random.default_rng(SEED)}

    rasters, report = {}, {}
    for name, p in data["panels"].items():
        r = render_panel(name, p, ctx)
        rasters[name] = {k: r[k] for k in ("rgb", "x0", "y1", "ppc", "rib")}
        report[name] = {"x0": round(r["x0"], 3), "y1": round(r["y1"], 3), "w": r["rgb"].shape[1],
                        "h": r["rgb"].shape[0], "kind": r["kind"], "rib": r["rib"], "mode": r["mode"],
                        "bands": r["bands"],
                        "offsets": [round(ph["offsets"][name], 4) for ph in phase]}

    front = {n for n, p in data["panels"].items() if p["kind"] == "front" and p["layout"]["view"] == "front"}
    start = np.array([0.5 * (pts[:, 0].min() + pts[:, 0].max()), 0.5 * (pts[:, 1].min() + pts[:, 1].max())])
    # only a print the photo puts in the upper garment is held to chest height; the spec places others low
    chest_row = ys0.min() + CHEST_FRAC * np.ptp(ys0)
    probes = [{"what": pm["what"], "panels": pm["panels"], "start": start,
               "high": bool(0.5 * (pm["box"][1] + pm["box"][3]) * h <= chest_row),
               "px": [0.5 * (pm["box"][0] + pm["box"][2]) * w, 0.5 * (pm["box"][1] + pm["box"][3]) * h],
               "poly": [[pm["box"][0] * w, pm["box"][1] * h], [pm["box"][2] * w, pm["box"][1] * h],
                        [pm["box"][2] * w, pm["box"][3] * h], [pm["box"][0] * w, pm["box"][3] * h]]}
              for pm in placements if any(n in front for n in pm["panels"])]
    if fallback and not probes:
        aim = {n for n in front if upper or data["panels"][n]["side"] == "left"}
        px = print_px(box, marks, upper)
        r = 0.12 * (box[1] - box[0])
        probes = [{"what": "print area", "panels": aim, "start": start, "px": px, "high": False,
                   "poly": [[px[0] - r, px[1] - r], [px[0] + r, px[1] - r],
                            [px[0] + r, px[1] + r], [px[0] - r, px[1] + r]]}]
    reg = register(data, warp, probes, upper) if reg_ok and probes else []
    fit_ratio = warp_pose(lin[:2].T)[1] / max(warp_pose(lin[:2].T)[2], 1e-9)

    live = [r.period_cm for r in spec.repeats if r.period_cm >= collapse_period_cm]
    info = {"safe": out_dir.name, "ppc": ppc, "kind": spec.kind.value,
            "mode": "fallback" if fallback else "pattern",
            "ground": [int(round(v)) for v in ground], "ground_from_photo": like_frac >= GROUND_FRAC,
            "ground_like_frac": round(like_frac, 3), "min_period_cm": min(live) if live else None,
            "collapsed": [i for i, r in enumerate(spec.repeats) if r.period_cm < collapse_period_cm],
            "phase": phase_info, "landmarks": {"mode": warp_mode, "pairs": len(used), "used": used,
                                               "rms_cm": round(rms, 2),
                                               "found": {k: [round(v, 1) for v in pt] for k, pt in marks.items()},
                                               "notes": mark_notes},
            "register": {"scale_px_per_cm": round(scale, 2), "photo_px_per_cm": round(photo_ppc, 2),
                         "fit_ratio": round(fit_ratio, 3), "accepted": bool(reg_ok), "probes": reg},
            "back_photo": back_photo, "panels": report, "seconds": round(time.time() - t0, 2)}

    if write:
        sub = out_dir / ("synth_stress" if stress else "synth")
        sub.mkdir(parents=True, exist_ok=True)
        for name, r in rasters.items():
            Image.fromarray(r["rgb"].round().clip(0, 255).astype(np.uint8)).save(sub / f"{name}.png")
        (sub / "synth.json").write_text(json.dumps(info, indent=1))
        cut = np.asarray(Image.open(item_dir / "cutout.png").convert("RGB"))
        name = "synth_stress_preview.png" if stress else "synth_preview.png"
        preview(data, rasters, cut, marks, used,
                f"{out_dir.name} {spec.kind.value} - front | back | unplaced").save(out_dir / name)
    info["seconds"] = round(time.time() - t0, 2)
    return {"ppc": ppc, "min_period_cm": info["min_period_cm"], "panels": rasters, "meta": info}


def line_metrics(ras: dict, p: dict, nrm: np.ndarray, period: float) -> dict:
    """Angle of the rendered lines against the grain and their spacing, read back off the raster."""
    g = ras["rgb"].mean(-1)
    out: dict = {}
    if g.std() < 1.0:
        return out
    f = {"x0": ras["x0"], "y1": ras["y1"], "w": g.shape[1], "h": g.shape[0], "ppc": ras["ppc"]}
    keep = frame_mask(f, np.asarray(p["outline_cm"], float))
    lines = (g > (g[keep].min() + g[keep].max()) / 2) & keep
    gy, gx = np.gradient(g)
    gx, gy = gx * keep, gy * keep
    ang = 0.5 * math.atan2(2 * float((gx * gy).sum()), float((gx * gx).sum() - (gy * gy).sum()))
    grad = np.array([math.cos(ang), -math.sin(ang)])
    out["angle_err_deg"] = round(math.degrees(math.acos(min(abs(float(grad @ nrm)), 1.0))), 3)
    counts, spacing, cover = [], [], []
    for r in (int(0.25 * g.shape[0]), int(0.75 * g.shape[0])):
        rr = runs_of(lines[r])
        counts.append(len(rr))
        cover.append(round(float(keep[r].sum()) / ras["ppc"] * abs(nrm[0]), 2))
        if len(rr) >= 3:
            mid = (rr[:, 0] + rr[:, 1]) / 2
            spacing.append(float(np.median(np.diff(mid)) / ras["ppc"] * abs(nrm[0])))
    out["lines_top"], out["lines_bottom"] = counts[0], counts[1]
    out["cm_top"], out["cm_bottom"] = cover[0], cover[1]
    out["count_err"] = round(max(abs(c - w / period) for c, w in zip(counts, cover)), 2)
    if spacing:
        out["spacing_cm"] = round(float(np.median(spacing)), 3)
        out["spacing_err"] = round(abs(out["spacing_cm"] - period) / period, 4)
    return out


def verify_item(data: dict, spec: PatternSpec, res: dict, stress: bool) -> tuple[list[str], dict]:
    bad: list[str] = []
    info = res["meta"]
    stats: dict = {}
    for name, p in data["panels"].items():
        r = res["panels"].get(name)
        if r is None:
            bad.append(f"{name}: no raster")
            continue
        if r["ppc"] < 20:
            bad.append(f"{name}: ppc {r['ppc']}")
        bb = p["bbox_cm"]
        if r["x0"] > bb[0] - MARGIN_CM + 1e-6 or r["y1"] < bb[3] + MARGIN_CM - 1e-6:
            bad.append(f"{name}: raster origin inside bbox+margin")
        if r["rgb"].shape[1] / r["ppc"] + r["x0"] < bb[2] + MARGIN_CM - 1e-6 or \
                r["y1"] - r["rgb"].shape[0] / r["ppc"] > bb[1] - MARGIN_CM + 1e-6:
            bad.append(f"{name}: raster does not cover bbox+margin")
        if not np.isfinite(r["rgb"]).all() or r["rgb"].min() < 0 or r["rgb"].max() > 255:
            bad.append(f"{name}: values out of 0..255")

    rg = info["register"]
    if rg["probes"] and rg["fit_ratio"] > RATIO_MAX:
        bad.append(f"registration scale ratio {rg['fit_ratio']:.2f}")
    # a leg lies at whatever angle the seller left it; only the upright torso fit is held to the tight gate
    gate = ROT_GATE if info["landmarks"]["mode"] in ("upright", "similarity", "prior") else 2 * ROT_GATE
    for pr in rg["probes"]:
        if abs(pr["rot_deg"]) > gate:
            bad.append(f"{pr['what']} print rotated {pr['rot_deg']:.1f} deg")
        if pr["cover"] is not None and pr["cover"] < COVER_MIN:
            bad.append(f"{pr['what']} print at {pr['cm']} cm, {pr['cover']:.0%} on its panels")
        if pr["chest"] is False:
            bad.append(f"{pr['what']} print at {pr['cm'][1]} cm, not chest height")
    stats["register"] = [(p["what"], p["rot_deg"], p["ratio"], p["cm"], p["cover"], p["chest"])
                         for p in rg["probes"]]

    for k, s in enumerate(info["phase"]["sets"]):
        if s["tree_residual"] > 0.02:
            bad.append(f"set {k}: tree residual {s['tree_residual']:.3f}")
    stats["phase"] = [(s["tree_residual"], s["tree_spread"], s["spread_at"], s["worst_free_residual"])
                      for s in info["phase"]["sets"]]

    trims = []
    for trim in spec.trims:
        if trim.placement != TrimPlacement.outseam or not trim.widths_cm:
            continue
        pairs = [s for s in data["stitches"] if s["label"] == "outseam"]
        carry = {n for n, p in data["panels"].items() if any(e["label"] == "outseam" for e in p["edges"])}
        for n in carry:
            if not info["panels"][n]["bands"].get("outseam"):
                bad.append(f"{n}: no outseam trim")
        for st in pairs:
            a, b = st["a"]["panel"], st["b"]["panel"]
            ba = info["panels"][a]["bands"].get("outseam")
            bb_ = info["panels"][b]["bands"].get("outseam")
            if not ba or not bb_:
                continue
            tot = [x + y for x, y in zip(ba, bb_)]
            for i, (got, want) in enumerate(zip(tot, trim.widths_cm)):
                if abs(got - want) > 0.05 * want:
                    bad.append(f"{a}|{b} band {i} {got:.2f} vs {want:.2f} cm")
            trims.append((f"{a}|{b}", [round(v, 2) for v in tot]))
    stats["trims"] = trims

    lines = []
    for k, rep in enumerate(spec.repeats if len(spec.repeats) == 1 else []):
        name = info["phase"]["root"]
        nrm = set_normal(rep.direction, np.asarray(data["panels"][name]["grain_axis"], float))
        mk = line_metrics(res["panels"][name], data["panels"][name], nrm, rep.period_cm)
        if not mk:
            continue
        lines.append((k, mk))
        if stress:
            if mk.get("angle_err_deg", 9) > 0.5:
                bad.append(f"set {k}: line angle err {mk['angle_err_deg']:.2f} deg")
            if mk.get("spacing_err", 1) > 0.05:
                bad.append(f"set {k}: spacing {mk.get('spacing_cm')} vs {rep.period_cm}")
            if mk["count_err"] > 1.5:
                bad.append(f"set {k}: {mk['lines_top']}/{mk['lines_bottom']} lines over "
                           f"{mk['cm_top']}/{mk['cm_bottom']} cm, off by {mk['count_err']}")
    stats["lines"] = lines
    return bad, stats


def items(inputs: Path, out: Path, only: str | None) -> list[tuple[Path, Path]]:
    found = []
    for d in sorted(p for p in inputs.iterdir() if p.is_dir()):
        if only and d.name != only:
            continue
        if (d / "item.json").exists() and (out / d.name / "panels.json").exists():
            found.append((d, out / d.name))
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs")
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out")
    ap.add_argument("--only")
    ap.add_argument("--spec", type=Path)
    ap.add_argument("--ppc", type=float, default=PPC)
    ap.add_argument("--collapse", type=float, default=0.0)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    found = items(a.inputs, a.out, a.only)
    if not found:
        raise SystemExit(f"no items with item.json under {a.inputs} and panels.json under {a.out}")
    override = PatternSpec.model_validate_json(a.spec.read_text()) if a.spec else None
    bad_items = []
    for item_dir, out_dir in found:
        res = synthesize(item_dir, out_dir, ppc=a.ppc, collapse_period_cm=a.collapse, spec=override)
        data = json.loads((out_dir / "panels.json").read_text())
        spec = override or PatternSpec.model_validate_json((item_dir / "spec.json").read_text())
        bad, stats = verify_item(data, spec, res, override is not None)
        info = res["meta"]
        ph = "-" if not stats["phase"] else " ".join(f"{t:.3f}/{sp:.2f}@{at}/{f:.2f}"
                                                     for t, sp, at, f in stats["phase"])
        tr = " ".join(f"{k}{v}" for k, v in stats["trims"][:2]) or "-"
        ln = " ".join(f"s{k}:{v.get('angle_err_deg', '-')}deg/{v.get('spacing_cm', '-')}cm/"
                      f"{v['lines_top']}in{v['cm_top']}cm>{v['lines_bottom']}in{v['cm_bottom']}cm"
                      for k, v in stats["lines"]) or "-"
        rg = info["register"]
        shots = []
        for p in rg["probes"]:
            cov = "-" if p["cover"] is None else f"{p['cover']:.0%}"
            band = "" if p["chest"] is None else ("/chest" if p["chest"] else "/NOTCHEST")
            shots.append(f"{p['what']}:{p['rot_deg']:+.1f}deg/x{p['ratio']:.2f}/"
                         f"({p['cm'][0]:.0f},{p['cm'][1]:.0f})cm/{cov}{band}")
        rp = " ".join(shots) or ("-" if rg["accepted"] else "none")
        print(f"{info['safe']} | {len(info['panels'])} panels | {info['mode']} | ground "
              f"#{''.join(f'{v:02x}' for v in info['ground'])}{'*' if info['ground_from_photo'] else ''} | "
              f"lm {info['landmarks']['pairs']} {info['landmarks']['mode']} "
              f"rms {info['landmarks']['rms_cm']}cm"
              f"{' ' + ';'.join(info['landmarks']['notes']) if info['landmarks']['notes'] else ''} | "
              f"reg {rg['scale_px_per_cm']}px/cm x{rg['fit_ratio']} {rp} | "
              f"phase {ph} | trim {tr} | lines {ln} | {info['seconds']}s"
              + (f" | ISSUES {len(bad)}: {'; '.join(bad[:3])}" if bad else ""))
        if bad:
            bad_items.append(info["safe"])
    if a.verify and bad_items:
        raise SystemExit(f"verify failed: {', '.join(bad_items)}")
    sub = "synth_stress" if a.spec else "synth"
    print(f"ok: {len(found)} items -> {a.out}/<safe>/{sub}/")


if __name__ == "__main__":
    main()
