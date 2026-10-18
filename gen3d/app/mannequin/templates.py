from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull

from app.mannequin.export import blend, morph_normals, morphs, write_morph_glb
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
from app.mannequin.params import body_params

TEMPLATE_MATERIAL = {
    "name": "garment",
    "pbrMetallicRoughness": {"baseColorFactor": [0.9, 0.9, 0.9, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9},
    "doubleSided": True,
}
# sleeve/legs: (end landmark, extra gap at the opening); drape: tube over both legs (hem above knee, flare)
TEMPLATES = {
    "tee_v1": dict(offset=0.015, torso=("hip", "neckbase"), sleeve=("mid_upper", 0.008)),
    "longsleeve_v1": dict(offset=0.015, torso=("hip", "neckbase"), sleeve=("wrist", 0.0)),
    "hoodie_v1": dict(offset=0.022, torso=("hip", "top"), sleeve=("wrist", 0.004), hood=True),
    "jacket_v1": dict(offset=0.030, torso=("hip", "neckbase"), sleeve=("wrist", 0.005)),
    "coat_v1": dict(offset=0.030, torso=("waist", "neckbase"), sleeve=("wrist", 0.005), drape=(-0.05, 0.08)),
    "pants_v1": dict(offset=0.010, seat=True, legs=("ankle", 0.016)),
    "shorts_v1": dict(offset=0.010, seat=True, legs=("mid_thigh", 0.012)),
    "skirt_v1": dict(offset=0.010, drape=(0.03, 0.12)),
    "dress_v1": dict(offset=0.015, torso=("waist", "neckline"), drape=(0.0, 0.10)),
}
N_DRAPE, N_SEAT, SEAT_DROP = 24, 12, 0.035
HOOD_OFFSET, NECK_OFFSET = 0.045, 0.012


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


def drape_rings(p: dict, ys: np.ndarray, d: float, flare: float, y0: float, y1: float) -> np.ndarray:
    sn, cs = angles(N_TRUNK)
    out, above = [], None
    for y in ys[::-1]:
        loops = [trunk_ring(p, y)[:, [0, 2]]] if y > p["crotch"] else []
        leg = leg_ring_at(p, y)
        if leg is not None:
            loops += [leg[:, [0, 2]], leg[:, [0, 2]] * [-1.0, 1.0]]
        pts = [_offset2d(loop, d) for loop in loops]
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


def _torso(p: dict, parts: dict, spec: dict) -> tuple[np.ndarray, np.ndarray]:
    d = spec["offset"]
    rings, start, end, keep = [], None, None, None
    if "torso" in spec:
        lo, hi = spec["torso"]
        i0 = TRUNK[lo]
        i1 = TRUNK["rings"] - 1 if hi == "top" else TRUNK["neckbase"] - 2 if hi == "neckline" else TRUNK[hi]
        r, _, e = parts["trunk"]
        n, _, ne = part_normals("trunk", parts["trunk"])
        # a full offset would fold in the neck-shoulder hollow
        offsets = d + (NECK_OFFSET - d) * smoothstep(TRUNK["shoulder"], TRUNK["neckbase"], np.arange(i0, i1 + 1))
        if spec.get("hood"):
            offsets[TRUNK["neckbase"] - i0 + 1 :] = HOOD_OFFSET
        shell = r[i0 : i1 + 1] + n[i0 : i1 + 1] * offsets[:, None, None]
        if spec.get("hood"):
            shell, keep = _hood(shell, i0)
        rings.append(shell)
        end = e + ne * offsets[-1] if hi == "top" else None
    y_hip, y_waist = p["torso"][:2, 0]
    if "drape" in spec:
        hem, flare = spec["drape"]
        h, u, length = leg_axis(p)
        y_hem = h[1] + u[1] * LEG_MARKS[1] * length + hem
        ys = y_hem + (y_waist - y_hem) * np.arange(N_DRAPE + ("torso" not in spec)) / N_DRAPE
        rings.insert(0, drape_rings(p, ys, d, flare, y_hip, y_hem))
    if spec.get("seat"):
        y0 = p["crotch"] + 0.005
        ys = y0 + (y_waist - y0) * np.arange(N_SEAT) / (N_SEAT - 1)
        seat = drape_rings(p, ys, d, 0.0, y0, y0 - 1.0)
        # round off the crotch between the legs instead of a flat cap
        c = np.array([0.0, y0, p["torso"][0, 4]])
        b = np.pi / 2 * np.arange(3, 0, -1)[:, None, None] / 4
        drop = np.array([0.0, SEAT_DROP, 0.0])
        rings.append(np.concatenate([c + (seat[0] - c) * np.cos(b) - drop * np.sin(b), seat]))
        start = c - drop
    rings = np.concatenate(rings)
    faces = tube_faces(len(rings), N_TRUNK, start is not None, end is not None, part_flip("trunk"), keep)
    return tube_vertices(rings, start, end), faces


def _limb(parts: dict, name: str, end: int, extra: float, d: float) -> tuple[np.ndarray, np.ndarray]:
    r, s, _ = parts[name]
    n, ns, _ = part_normals(name, parts[name])
    idx = np.arange(end + 1)
    offsets = d + extra * smoothstep(max(ARM["joint"], end - 17), end, idx)
    verts = tube_vertices(r[: end + 1] + n[: end + 1] * offsets[:, None, None], s + ns * d)
    return verts, tube_faces(end + 1, r.shape[1], True, False, part_flip(name))


def template_mesh(template_id: str, base, sliders: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    spec = TEMPLATES[template_id]
    p = body_params(base, sliders)
    parts = body_parts(p)
    patches = [_torso(p, parts, spec)]
    for key, kind, marks in (("sleeve", "arm", ARM), ("legs", "leg", LEG)):
        if key in spec:
            end, extra = spec[key]
            patches += [_limb(parts, f"{kind}_{side}", marks[end], extra, spec["offset"]) for side in "lr"]
    verts, faces, n = [], [], 0
    for v, f in patches:
        verts.append(v)
        faces.append(f + n)
        n += len(v)
    return np.vstack(verts) * p["scale"], np.vstack(faces)


def export_template(template_id: str, base: str, path: Path) -> Path:
    verts, faces, targets = morphs(lambda s: template_mesh(template_id, base, s))
    normals, target_normals = morph_normals(verts, faces, targets)
    half = blend(verts, targets, 0.5)
    front = vertex_normals(half, faces)[faces].mean(1)[:, 2] >= 0
    # vertices shared by front and back faces are split: that is the uv seam
    used, inv = np.unique(np.where(front[:, None], faces, faces + len(verts)), return_inverse=True)
    src, back = used % len(verts), used >= len(verts)
    (x0, y0), (x1, y1) = half[src, :2].min(0), half[src, :2].max(0)
    x, y = half[src, 0], half[src, 1]
    u = np.where(back, 0.5 + 0.5 * (x1 - x) / (x1 - x0), 0.5 * (x - x0) / (x1 - x0))
    uv = np.stack([u, (y1 - y) / (y1 - y0)], 1)
    return write_morph_glb(
        path, f"{template_id}_{base}", verts[src], normals[src], targets[:, src], target_normals[:, src],
        inv.reshape(-1, 3), TEMPLATE_MATERIAL, uv,
    )
