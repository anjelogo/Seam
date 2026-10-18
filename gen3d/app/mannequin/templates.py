from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull

from app.mannequin.export import GARMENT_MORPHS, blend, morph_normals, morphs, write_morph_glb
from app.mannequin.generator import (
    ARM,
    LEG,
    LEG_MARKS,
    N_TRUNK,
    TRUNK,
    angles,
    body_parts,
    leg_axis,
    leg_ring_at,
    part_flip,
    part_normals,
    sexp,
    smoothstep,
    trunk_ring,
    trunk_section,
    tube_faces,
    tube_vertices,
    vertex_normals,
)
from app.mannequin.params import SLIDERS, body_params

TEMPLATE_MATERIAL = {
    "name": "garment",
    "pbrMetallicRoughness": {"baseColorFactor": [0.9, 0.9, 0.9, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9},
    "doubleSided": True,
}
# sleeve/legs: (end landmark, extra gap at the opening); drape: tube over both legs (hem above knee, flare)
# ease_flare: ease also widens the bottom openings; open: front left open with lapels
TEMPLATES = {
    "tee_v1": dict(offset=0.015, torso=("hip", "neckbase"), sleeve=("mid_upper", 0.008)),
    "longsleeve_v1": dict(offset=0.015, torso=("hip", "neckbase"), sleeve=("wrist", 0.0)),
    "hoodie_v1": dict(offset=0.022, torso=("hip", "top"), sleeve=("wrist", 0.004), hood=True),
    "jacket_v1": dict(offset=0.030, torso=("hip", "neckbase"), sleeve=("wrist", 0.005)),
    "coat_v1": dict(offset=0.030, torso=("waist", "neckbase"), sleeve=("wrist", 0.005), drape=(-0.05, 0.08)),
    "pants_v1": dict(offset=0.010, seat=True, legs=("ankle", 0.016), ease_flare=True),
    "shorts_v1": dict(offset=0.010, seat=True, legs=("mid_thigh", 0.012), ease_flare=True),
    "skirt_v1": dict(offset=0.010, drape=(0.03, 0.12), ease_flare=True),
    "dress_v1": dict(offset=0.015, torso=("waist", "neckline"), drape=(0.0, 0.10)),
}
TEMPLATES |= {f"{t}_open": dict(TEMPLATES[t], open=True) for t in ("jacket_v1", "coat_v1")}
N_DRAPE, N_SEAT, SEAT_DROP = 24, 12, 0.035
HOOD_OFFSET, NECK_OFFSET = 0.045, 0.012
# ease morph: extra offset, what is left of it at collar and hood, extra flare at bottom openings
EASE, EASE_NECK, EASE_FLARE, INSEAM = 0.06, 0.02, 0.03, 0.004
# ease adds girth, not height: shoulders and hood do not balloon upward
FLAT = np.array([1.0, 0.0, 1.0])
CROP = 0.25
# open front: half gap through the body and at the collar, edge to lapel hinge, lapel swing
GAP, GAP_COLLAR, HINGE, LAPEL = 0.06, 0.03, 0.07, np.radians(15.0)
# ring column that becomes the opening edge, last column the opening may shift
OPEN_COL, OPEN_SPAN = 3, 12


def _cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def _offset2d(loop: np.ndarray, d: float) -> np.ndarray:
    t = np.roll(loop, -1, 0) - np.roll(loop, 1, 0)
    n = np.stack([-t[:, 1], t[:, 0]], 1)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    return loop + d * n * np.sign(-_cross(loop, np.roll(loop, -1, 0)).sum())


def _raycast(poly: np.ndarray, c: np.ndarray, dirs: np.ndarray) -> np.ndarray:
    e, rel = np.roll(poly, -1, 0) - poly, poly - c
    den = _cross(dirs[:, None], e[None])
    with np.errstate(divide="ignore", invalid="ignore"):
        t = _cross(rel[None], e[None]) / den
        lam = _cross(rel[None], dirs[:, None]) / den
    hit = (np.abs(den) > 1e-12) & (lam >= -1e-9) & (lam <= 1 + 1e-9) & (t > 0)
    return np.where(hit, t, np.inf).min(1)


def drape_rings(p: dict, ys: np.ndarray, d: float | np.ndarray, flare: float, y0: float, y1: float) -> np.ndarray:
    sn, cs = angles(N_TRUNK)
    out, above = [], None
    for y, dy in zip(ys[::-1], np.broadcast_to(d, ys.shape)[::-1]):
        loops = [trunk_ring(p, y)[:, [0, 2]]] if y > p["crotch"] else []
        leg = leg_ring_at(p, y)
        if leg is not None:
            loops += [leg[:, [0, 2]], leg[:, [0, 2]] * [-1.0, 1.0]]
        pts = [_offset2d(loop, dy) for loop in loops]
        # below the hips fabric hangs: never narrower than the ring above
        if above is not None and y < y0:
            pts.append(above)
        pts = np.vstack(pts)
        hull = above = pts[ConvexHull(pts).vertices]
        _, _, _, zc, ex = trunk_section(p, max(y, p["torso"][0, 0]))
        c = np.array([0.0, zc])
        # trunk-style angles so drape rings line up with torso rings
        depth = np.where(cs >= 0, hull[:, 1].max() - zc, zc - hull[:, 1].min())
        dirs = np.stack([np.abs(hull[:, 0]).max() * sexp(sn, ex), depth * sexp(cs, ex)], 1)
        grow = 1 + flare * np.clip((y0 - y) / (y0 - y1), 0.0, 1.0)
        xz = c + grow * _raycast(hull, c, dirs)[:, None] * dirs
        out.append(np.stack([xz[:, 0], np.full(N_TRUNK, y), xz[:, 1]], 1))
    return np.stack(out[::-1])


def _hood(shell: np.ndarray, i0: int) -> tuple[np.ndarray, np.ndarray]:
    # hood hangs from the collar to the head instead of hugging the neck
    a, b = TRUNK["neckbase"] - i0, TRUNK["head"] - i0
    t = np.linspace(0.0, 1.0, b - a + 1)[:, None, None]
    s = np.sin(np.pi / 2 * t)
    shell = shell.copy()
    shell[a : b + 1] = shell[a] + (shell[b] - shell[a]) * np.concatenate([s, t, s], -1)
    rows = np.arange(len(shell) - 1)
    inside = np.abs(np.arctan2(*angles(N_TRUNK))) <= np.radians(64.0)
    face = ((rows >= a) & (rows < b + 3))[:, None] & (inside & np.roll(inside, -1))[None]
    return shell, ~face


def _lerp(rings: np.ndarray, f: np.ndarray) -> np.ndarray:
    i = np.clip(f.astype(int), 0, len(rings) - 2)
    return rings[i] + (rings[i + 1] - rings[i]) * (f - i)[:, None, None]


def _hem(p: dict, hem: float) -> float:
    h, u, length = leg_axis(p)
    return h[1] + u[1] * LEG_MARKS[1] * length + hem


def _waistband(p: dict, ys: np.ndarray) -> np.ndarray:
    # bottoms keep the waistband near the waist as tops keep the collar near the neck
    return EASE + (EASE_NECK - EASE) * smoothstep(*p["torso"][:2, 0], ys)


def _open(rings: np.ndarray, gap: np.ndarray, swing: np.ndarray) -> np.ndarray:
    out, k = rings.copy(), np.arange(OPEN_SPAN + 1)
    for j, (g, lapel) in enumerate(zip(gap, swing)):
        for cols, sx in ((k, 1.0), (-k % N_TRUNK, -1.0)):
            pts = rings[j, cols] * [sx, 1.0, 1.0]
            # slide the edge column along the ring onto x = gap so the opening edge runs straight
            s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
            sg, sc = np.interp(g, pts[:, 0], s), s[OPEN_COL]
            t = np.where(k <= OPEN_COL, s * sg / sc, sg + (s - sc) * (s[-1] - sg) / (s[-1] - sc))
            pts = np.stack([np.interp(t, s, pts[:, i]) for i in range(3)], 1)
            # lapel: swing the strip between edge and hinge forward about a vertical axis
            hx = min(g + HINGE, pts[-1, 0])
            hz = np.interp(hx, pts[:, 0], pts[:, 2])
            a = lapel * smoothstep(hx, g, pts[:, 0])
            dx, dz = pts[:, 0] - hx, pts[:, 2] - hz
            pts[:, 0], pts[:, 2] = hx + dx * np.cos(a) + dz * np.sin(a), hz - dx * np.sin(a) + dz * np.cos(a)
            out[j, cols] = pts * [sx, 1.0, 1.0]
    return out


def _torso(p: dict, parts: dict, spec: dict, ease: float, crop: float) -> tuple[np.ndarray, np.ndarray]:
    d = spec["offset"]
    rings, heights, start, end, keep = [], [], None, None, None
    y_hip, y_waist = p["torso"][:2, 0]
    if "torso" in spec:
        lo, hi = spec["torso"]
        i0 = TRUNK[lo]
        i1 = TRUNK["rings"] - 1 if hi == "top" else TRUNK["neckbase"] - 2 if hi == "neckline" else TRUNK[hi]
        idx = np.arange(i0, i1 + 1)
        r, _, e = parts["trunk"]
        n, _, ne = part_normals("trunk", parts["trunk"])
        neck = smoothstep(TRUNK["shoulder"], TRUNK["neckbase"], idx)
        # a full offset would fold in the neck-shoulder hollow
        offsets = d + (NECK_OFFSET - d) * neck
        loose = ease * (EASE + (EASE_NECK - EASE) * neck)
        if spec.get("hood"):
            offsets[TRUNK["neckbase"] - i0 + 1 :] = HOOD_OFFSET
            loose[TRUNK["neckbase"] - i0 + 1 :] = ease * EASE_NECK
        shell = r[idx] + n[idx] * offsets[:, None, None] + n[idx] * FLAT * loose[:, None, None]
        if spec.get("hood"):
            shell, keep = _hood(shell, i0)
        rings.append(shell)
        heights.append(r[idx, 0, 1])
        end = e + ne * offsets[-1] + ne * FLAT * loose[-1] if hi == "top" else None
    if "drape" in spec:
        hem, flare = spec["drape"]
        y_hem, ref = _hem(p, hem), body_params(p["base"])
        # the hip ring, where the drape stops narrowing, keeps one index for every body so morphs line up
        n_hip = round(N_DRAPE * (ref["torso"][0, 0] - _hem(ref, hem)) / (ref["torso"][1, 0] - _hem(ref, hem)))
        ys = np.interp(np.arange(N_DRAPE + ("torso" not in spec)), [0, n_hip, N_DRAPE], [y_hem, y_hip, y_waist])
        loose = EASE if "torso" in spec else _waistband(p, ys)
        loose += spec.get("ease_flare", False) * EASE_FLARE * smoothstep(0.6, 1.0, (y_waist - ys) / (y_waist - y_hem))
        rings.insert(0, drape_rings(p, ys, d + ease * loose, flare, y_hip, y_hem))
        heights.insert(0, ys)
    if crop and rings:
        ys = np.concatenate(heights)
        y_fix, y_top = (r[TRUNK["chest"], 0, 1], r[min(i1, TRUNK["neckbase"]), 0, 1]) if "torso" in spec else (y_waist, y_waist)
        # everything below y_fix squeezes toward it so the hem rises by CROP of the garment length
        k = 1 - CROP * crop * (y_top - ys[0]) / (y_fix - ys[0])
        f = np.interp(np.where(ys < y_fix, y_fix - (y_fix - ys) * k, ys), ys, np.arange(len(ys)))
        rings = [_lerp(np.concatenate(rings), f)]
    if spec.get("seat"):
        y0 = p["crotch"] + 0.005
        ys = y0 + (y_waist - y0) * np.arange(N_SEAT) / (N_SEAT - 1)
        seat = drape_rings(p, ys, d + ease * _waistband(p, ys), 0.0, y0, y0 - 1.0)
        # round off the crotch between the legs instead of a flat cap
        c = np.array([0.0, y0, p["torso"][0, 4]])
        b = np.pi / 2 * np.arange(3, 0, -1)[:, None, None] / 4
        drop = np.array([0.0, SEAT_DROP, 0.0])
        rings.append(np.concatenate([c + (seat[0] - c) * np.cos(b) - drop * np.sin(b), seat]))
        start = c - drop
    rings = np.concatenate(rings)
    if spec.get("open"):
        # the opening narrows and the lapels settle flat toward the collar
        collar = smoothstep(TRUNK["shoulder"], i1, np.r_[np.full(len(rings) - len(idx), i0), idx])
        rings = _open(rings, GAP + (GAP_COLLAR - GAP) * collar, LAPEL * (1 - collar))
        keep = np.ones((len(rings) - 1, N_TRUNK), bool)
        keep[:, :OPEN_COL] = keep[:, N_TRUNK - OPEN_COL :] = False
    faces = tube_faces(len(rings), N_TRUNK, start is not None, end is not None, part_flip("trunk"), keep)
    return tube_vertices(rings, start, end), faces


def _limb(
    parts: dict, name: str, end: int, extra: float, d: float, ease: float, crop: float, flare: bool
) -> tuple[np.ndarray, np.ndarray]:
    r, s, e = parts[name]
    n, ns, _ = part_normals(name, parts[name])
    # distance of every ring along the limb from the joint
    t = (r[:, 0] - r[ARM["joint"], 0]) @ ((e - s) / np.linalg.norm(e - s))
    idx = np.arange(end + 1)
    offsets = d + extra * smoothstep(max(ARM["joint"], end - 17), end, idx)
    loose = ease * (EASE + flare * EASE_FLARE * smoothstep(0.6 * t[end], t[end], t[idx]))
    # crop pulls the rings past the joint up the limb, opening flare and all
    f = np.interp(np.where(t[idx] > 0, t[idx] * (1 - CROP * crop), t[idx]), t, np.arange(len(r)))
    rr, nn = _lerp(r, f), _lerp(n, f)
    nn /= np.linalg.norm(nn, axis=-1, keepdims=True)
    shell = rr + nn * offsets[:, None, None] + nn * FLAT * loose[:, None, None]
    verts = tube_vertices(shell, s + ns * d + ns * FLAT * ease * EASE)
    if ease and name.startswith("leg"):
        # eased legs meet at the inseam instead of crossing
        sx = 1.0 if name.endswith("_l") else -1.0
        verts[:, 0] = sx * np.maximum(sx * verts[:, 0], INSEAM)
    return verts, tube_faces(end + 1, r.shape[1], True, False, part_flip(name))


def garment_mesh(spec: dict, base, sliders: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    sliders = sliders or {}
    ease, crop = sliders.get("ease", 0.0), sliders.get("crop", 0.0)
    p = body_params(base, sliders)
    parts = body_parts(p)
    patches = [_torso(p, parts, spec, ease, crop)]
    for key, kind, marks in (("sleeve", "arm", ARM), ("legs", "leg", LEG)):
        if key in spec:
            end, extra = spec[key]
            patches += [
                _limb(parts, f"{kind}_{side}", marks[end], extra, spec["offset"], ease, crop, spec.get("ease_flare", False))
                for side in "lr"
            ]
    verts, faces, n = [], [], 0
    for v, f in patches:
        verts.append(v)
        faces.append(f + n)
        n += len(v)
    return np.vstack(verts) * p["scale"], np.vstack(faces)


def template_mesh(template_id: str, base, sliders: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    return garment_mesh(TEMPLATES[template_id], base, sliders)


def export_template(template_id: str, base: str, path: Path) -> Path:
    spec = TEMPLATES[template_id]
    verts, faces, targets = morphs(lambda s: garment_mesh(spec, base, s), GARMENT_MORPHS)
    normals, target_normals = morph_normals(verts, faces, targets)
    closed, closed_faces, closed_targets = verts, faces, targets[: len(SLIDERS)]
    if spec.get("open"):
        # uv of the closed garment so a texture lands the same on both
        closed, closed_faces, closed_targets = morphs(lambda s: garment_mesh(dict(spec, open=False), base, s))
    half = blend(closed, closed_targets, 0.5)
    front = vertex_normals(half, closed_faces)[faces].mean(1)[:, 2] >= 0
    # vertices shared by front and back faces are split: that is the uv seam
    used, inv = np.unique(np.where(front[:, None], faces, faces + len(verts)), return_inverse=True)
    src, back = used % len(verts), used >= len(verts)
    bounds = half[np.unique(closed_faces), :2]
    (x0, y0), (x1, y1) = bounds.min(0), bounds.max(0)
    x, y = half[src, 0], half[src, 1]
    u = np.where(back, 0.5 + 0.5 * (x1 - x) / (x1 - x0), 0.5 * (x - x0) / (x1 - x0))
    uv = np.stack([u, (y1 - y) / (y1 - y0)], 1)
    return write_morph_glb(
        path, f"{template_id}_{base}", verts[src], normals[src], targets[:, src], target_normals[:, src],
        inv.reshape(-1, 3), TEMPLATE_MATERIAL, uv, (*SLIDERS, *GARMENT_MORPHS),
    )
