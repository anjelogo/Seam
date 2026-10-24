"""PBR texturing of draped garments: spec -> delight -> panels -> synth -> UV atlas (--legacy: photo front projection)."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy.ndimage import gaussian_filter

from drape._repo import DRAPE, bootstrap

bootstrap()

SIZE = 1024
SEED = 1337
CM = 100.0
SEAM_PX = 2
SEAM_DARKEN = 0.92
BACK_BLUR = 24 / 1024
BACK_MIX = 0.7
FILL_PX = 3
MIN_PERIOD_PX = 3.0
WAVE_FADE_PX = (2.0, 3.5)  # a wave fades out between these pixel periods
GRAIN_SIGMA_PX = 0.8  # noise below this blur radius would alias instead of reading as grain
TWILL_SETS = ((0.34, 0.0, 1.0), (0.16, 0.5, 0.55))  # duty, offset in periods, weight
TWILL_HARMONICS = 4
TWILL_AMP = 0.10
DENIM_GRAIN = (0.09, 0.013, 3)  # fibre noise: cm, height std, diagonal smear taps
DENIM_SLUB = (0.30, 0.004)  # weave irregularity: cm, height std; louder than this reads as crumple once minified
JERSEY_AMP = 0.055
JERSEY_GRAIN = (0.12, 0.030)  # cm, height std

# roughness, normal strength, pattern period in cm
FABRIC = {
    "jersey": {"rough": 0.85, "strength": 0.9, "period": 0.10},
    "rib": {"rough": 0.85, "strength": 4.0, "period": 0.5},
    "denim": {"rough": 0.90, "strength": 2.4, "period": 0.10},
    "canvas": {"rough": 0.88, "strength": 2.5, "period": 0.2},
    "leather": {"rough": 0.40, "strength": 1.5, "period": 0.8},
}
MATERIAL_FABRIC = {
    "denim": "denim", "jean": "denim", "leather": "leather", "suede": "leather",
    "canvas": "canvas", "twill": "canvas", "corduroy": "canvas", "linen": "canvas",
    "knit": "jersey", "jersey": "jersey", "cotton jersey": "jersey", "fleece": "jersey",
    "cotton": "jersey", "wool": "jersey", "polyester": "jersey", "nylon": "jersey",
}
CATEGORY_FABRIC = {
    "jeans": "denim", "denim": "denim", "sweats": "jersey", "hoodie": "jersey",
    "sweatshirt": "jersey", "tee": "jersey", "pants": "jersey", "cargo": "canvas",
}


# ---------------------------------------------------------------- items + mesh


def item_dirs(inputs: Path, only: str | None = None) -> list[dict]:
    meta = {}
    mf = inputs / "manifest.json"
    if mf.exists():
        meta = {e["safe"]: e for e in json.loads(mf.read_text()).get("items", [])}
    out = []
    for d in sorted(p for p in inputs.iterdir() if p.is_dir()):
        if only and d.name != only:
            continue
        if not (d / "item.json").exists():
            continue
        out.append({"safe": d.name, "dir": d, "item": json.loads((d / "item.json").read_text()),
                    "meta": meta.get(d.name, {})})
    return out


def find_mesh(out: Path, safe: str) -> Path | None:
    """Post-sim obj (re-posed to the web pose when the sim ran in the A-pose), else the pre-sim boxmesh."""
    base = out / safe
    if not base.exists():
        return None
    for pat in ("sim/**/*_sim_posed.obj", "sim/**/*_sim.obj", "sim*/**/*_sim.obj", "sim/**/*_boxmesh.obj",
                "sim*/**/*_boxmesh.obj"):
        hits = sorted(base.glob(pat))
        if hits:
            return hits[0]
    return None


def mesh_name(path: Path) -> str:
    stem = path.stem
    for suffix in ("_sim_posed", "_sim", "_boxmesh"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def load_obj(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    verts, uvs, fv, ft = [], [], [], []
    for line in path.read_text().splitlines():
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("vt "):
            uvs.append([float(x) for x in line.split()[1:3]])
        elif line.startswith("f "):
            corners = [c.split("/") for c in line.split()[1:]]
            vi = [int(c[0]) - 1 for c in corners]
            ti = [int(c[1]) - 1 if len(c) > 1 and c[1] else -1 for c in corners]
            for k in range(1, len(vi) - 1):
                fv.append([vi[0], vi[k], vi[k + 1]])
                ft.append([ti[0], ti[k], ti[k + 1]])
    return (np.array(verts, np.float64), np.array(uvs, np.float64),
            np.array(fv, np.int64), np.array(ft, np.int64))


def vertex_labels(mesh_path: Path, n_verts: int) -> list[str]:
    seg = mesh_path.parent / f"{mesh_name(mesh_path)}_sim_segmentation.txt"
    if not seg.exists():
        raise SystemExit(f"{seg} missing - cannot tell panels apart")
    labels = seg.read_text().split()
    if len(labels) != n_verts:
        raise SystemExit(f"{seg.name}: {len(labels)} labels for {n_verts} vertices")
    return labels


def face_panels(faces_v: np.ndarray, labels: list[str]) -> tuple[np.ndarray, list[str]]:
    """Panel index per face; seam (stitch_N) vertices get the panel their neighbours vote for."""
    panels = sorted({v for v in labels if v and not v.startswith("stitch")})
    index = {p: i for i, p in enumerate(panels)}
    vid = np.array([index.get(v, -1) for v in labels], np.int64)
    face = np.full(len(faces_v), -1, np.int64)
    for i, row in enumerate(vid[faces_v].tolist()):
        valid = [v for v in row if v >= 0]
        if valid:
            face[i] = Counter(sorted(valid)).most_common(1)[0][0]

    by_vert: dict[int, list[int]] = {}
    for i, row in enumerate(faces_v.tolist()):
        for v in row:
            by_vert.setdefault(v, []).append(i)
    todo = np.flatnonzero(face < 0).tolist()
    while todo:
        left = []
        for i in todo:
            votes = [int(face[j]) for v in faces_v[i].tolist() for j in by_vert[v] if face[j] >= 0]
            if votes:
                face[i] = Counter(sorted(votes)).most_common(1)[0][0]
            else:
                left.append(i)
        if len(left) == len(todo):
            break
        todo = left
    return face, panels


# ---------------------------------------------------------------- atlas raster


def texel_geometry(verts: np.ndarray, uvs: np.ndarray, faces_v: np.ndarray, faces_vt: np.ndarray,
                   size: int) -> tuple[np.ndarray, ...]:
    """Rasterize the uv atlas: per-texel face index and the 3D point (cm) it covers."""
    tri = uvs[faces_vt] * [size, -size] + [0, size]
    img = Image.new("I", (size, size), 0)
    draw = ImageDraw.Draw(img)
    for i, poly in enumerate(tri.reshape(-1, 6).tolist(), 1):
        draw.polygon(poly, fill=i, outline=i)
    painted = np.asarray(img).astype(np.int64)
    rows, cols = np.nonzero(painted)
    f = painted[rows, cols] - 1
    a, b, c = tri.transpose(1, 0, 2)
    e1, e2 = b - a, c - a
    den = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    den[np.abs(den) < 1e-12] = 1e-12
    d = np.stack([cols, rows], 1) + 0.5 - a[f]
    l1 = (d[:, 0] * e2[f, 1] - d[:, 1] * e2[f, 0]) / den[f]
    l2 = (e1[f, 0] * d[:, 1] - e1[f, 1] * d[:, 0]) / den[f]
    # texels on a triangle's edge can sit just outside it: clamp onto the triangle
    bary = np.clip(np.stack([1 - l1 - l2, l1, l2], 1), 0, 1)
    bary /= bary.sum(1, keepdims=True)
    corner = faces_v[f]
    xyz = sum(bary[:, k, None] * verts[corner[:, k]] for k in range(3))
    return rows, cols, f, xyz


def _neighbours(a: np.ndarray) -> list[np.ndarray]:
    p = np.pad(a, [(1, 1), (1, 1)] + [(0, 0)] * (a.ndim - 2))
    return [p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]]


def grow(filled: np.ndarray, layers: list[np.ndarray], n: int) -> np.ndarray:
    """Bleed every layer outwards by n texels so bilinear sampling never pulls in empty atlas."""
    filled = filled.copy()
    for _ in range(n):
        hole = ~filled
        for k, c in enumerate(_neighbours(filled.astype(np.uint8))):
            take = hole & (c != 0)
            if not take.any():
                continue
            for layer in layers:
                layer[take] = _neighbours(layer)[k][take]
            filled = filled | take
            hole &= ~take
    return filled


def borders(ids: np.ndarray, width: int) -> np.ndarray:
    edge = np.zeros(ids.shape, bool)
    for c in _neighbours(ids):
        edge |= c != ids
    edge &= ids != 0
    for _ in range(width - 1):
        grown = edge.copy()
        for c in _neighbours(edge.astype(np.uint8)):
            grown |= (c != 0) & (ids != 0)
        edge = grown
    return edge


def panel_area_cm2(panel_dir: Path, panel: str) -> float:
    """Real-world area of the flat pattern piece."""
    obj = panel_dir / f"{panel}.obj"
    if not obj.exists():
        return 0.0
    verts, _, faces, _ = load_obj(obj)
    if len(verts) < 3:
        return 0.0
    if len(faces):
        t = verts[faces]
        return float(np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2)
    flat = verts - verts.mean(0)
    axes = np.linalg.svd(flat, full_matrices=False)[2][:2]
    return float(np.prod(np.ptp(flat @ axes.T, axis=0)))


# ---------------------------------------------------------------- panel kinds


def panel_kind(name: str) -> str:
    n = name.lower()
    parts = n.split("_")
    if "cuff" in n or "wb" in parts or "waistband" in n or "hem" in parts:
        return "rib"
    if "hood" in n:
        return "hood"
    if "sleeve" in n:
        return "sleeve"
    if "btorso" in n or "back" in n or "b" in parts:
        return "back"
    if "ftorso" in n or "front" in n or "f" in parts:
        return "front"
    return "other"


def fabric_for(material: str | None, category: str | None, role: str | None) -> str:
    key = (material or "").strip().lower()
    if key in MATERIAL_FABRIC:
        return MATERIAL_FABRIC[key]
    for word, fab in MATERIAL_FABRIC.items():
        if word in key:
            return fab
    for tag in ((role or "").lower(), (category or "").lower()):
        if tag in CATEGORY_FABRIC:
            return CATEGORY_FABRIC[tag]
    return "jersey"


# ---------------------------------------------------------------- cutout


def dominant(rgb: np.ndarray) -> np.ndarray:
    bins = (rgb // 32).astype(np.int64) @ [64, 8, 1]
    return rgb[bins == np.bincount(bins).argmax()].mean(0).round().astype(np.uint8)


def garment_crop(item_dir: Path, item: dict) -> tuple[np.ndarray, np.ndarray]:
    """RGBA crop of the garment region plus its dominant colour."""
    px = np.asarray(Image.open(item_dir / "cutout.png").convert("RGBA"))
    opaque = px[..., 3] > 127
    ys, xs = np.nonzero(opaque)
    if not len(xs):
        raise SystemExit(f"{item_dir.name}/cutout.png has no opaque pixels")
    box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    tagged = ((item.get("tags") or {}).get("garment_box")) or None
    if tagged and len(tagged) == 4:
        h, w = px.shape[:2]
        t = [tagged[0] * w, tagged[1] * h, tagged[2] * w, tagged[3] * h]
        inter = [max(box[0], t[0]), max(box[1], t[1]), min(box[2], t[2]), min(box[3], t[3])]
        area = max(inter[2] - inter[0], 0) * max(inter[3] - inter[1], 0)
        if area > 0.25 * (box[2] - box[0]) * (box[3] - box[1]):
            box = [int(round(v)) for v in inter]
    crop = px[box[1] : box[3], box[0] : box[2]]
    rgb = crop[crop[..., 3] > 127, :3]
    if not len(rgb):
        rgb = px[opaque][:, :3]
    return crop, dominant(rgb)


def flatten(crop: np.ndarray, color: np.ndarray) -> Image.Image:
    a = crop[..., 3:] / 255
    return Image.fromarray((crop[..., :3] * a + color * (1 - a)).round().astype(np.uint8))


def region_color(crop: np.ndarray, kind: str, fallback: np.ndarray) -> np.ndarray:
    h, w = crop.shape[:2]
    if kind == "sleeve":
        edge = max(int(w * 0.12), 1)
        part = np.concatenate([crop[:, :edge].reshape(-1, 4), crop[:, w - edge :].reshape(-1, 4)])
    elif kind == "hood":
        part = crop[: max(int(h * 0.15), 1)].reshape(-1, 4)
    elif kind == "rib":
        part = crop[h - max(int(h * 0.15), 1) :].reshape(-1, 4)
    else:
        part = crop.reshape(-1, 4)
    rgb = part[part[:, 3] > 127, :3]
    return dominant(rgb) if len(rgb) >= 200 else fallback


def project(photo: Image.Image, xyz: np.ndarray, box: np.ndarray, mirror: bool, blur: float) -> np.ndarray:
    """Front view of the garment: the world x,y of each texel picks its pixel in the garment crop."""
    ar = photo.height / photo.width
    tw = max(int(round(math.sqrt(max(len(xyz), 256) / ar))), 16)
    img = photo.resize((tw, max(int(round(tw * ar)), 16)), Image.Resampling.LANCZOS)
    if mirror:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur * img.width))
    arr = np.asarray(img.convert("RGB"))
    span = np.maximum(box[1] - box[0], 1e-6)
    u = (xyz[:, 0] - box[0][0]) / span[0]
    v = (box[1][1] - xyz[:, 1]) / span[1]
    if mirror:
        u = 1 - u
    cols = np.clip((u * (arr.shape[1] - 1)).round().astype(np.int64), 0, arr.shape[1] - 1)
    rows = np.clip((v * (arr.shape[0] - 1)).round().astype(np.int64), 0, arr.shape[0] - 1)
    return arr[rows, cols]


# ---------------------------------------------------------------- procedural


def noise(size: int) -> np.ndarray:
    return np.random.default_rng(SEED).random((size, size), dtype=np.float32)


def band_fade(period_px: float) -> float:
    """A wave shorter than two texels can only alias, so fade it out instead of drawing it."""
    lo, hi = WAVE_FADE_PX
    t = min(max((period_px - lo) / (hi - lo), 0.0), 1.0)
    return float(t * t * (3 - 2 * t))


def tile_cycles(period_px: float, size: int, diagonal: bool) -> tuple[float, float]:
    """Frequency snapped to a whole number of cycles per tile, so the field has no seam when tiled."""
    axis = math.sqrt(2.0) if diagonal else 1.0
    n = max(round(size / (period_px * axis)), 1)
    return n / size, size / (n * axis)


def grain(white: np.ndarray, period_px: float, std: float, smear_taps: int = 0) -> np.ndarray:
    """Noise low-passed to its own scale, so it reads as fibre sheen rather than per-texel bumps."""
    g = gaussian_filter(white - 0.5, max(period_px / 2.0, GRAIN_SIGMA_PX), mode="wrap")
    half = smear_taps // 2
    if half:
        # averaged along the wale line, which is what tilts the grain with the weave
        acc = np.zeros_like(g)
        for k in range(-half, half + 1):
            acc += np.roll(g, (-k, k), (0, 1))
        g = acc / (2 * half + 1)
    sd = float(g.std())
    return (g * (std / sd)).astype(np.float32) if sd > 1e-9 else g.astype(np.float32)


def twill(x: np.ndarray, y: np.ndarray, period_px: float, size: int) -> tuple[np.ndarray, float]:
    """Two offset diagonal wale sets as square waves, each harmonic faded out once it goes sub-pixel."""
    f, realized = tile_cycles(period_px, size, True)
    phase = (f * (x + y)).astype(np.float32)
    probe = np.linspace(0, 1, 1024, dtype=np.float64)
    h, ref = np.zeros_like(phase), np.zeros_like(probe)
    for duty, off, weight in TWILL_SETS:
        for k in range(1, TWILL_HARMONICS + 1):
            amp = weight * 2.0 / (k * math.pi) * math.sin(k * math.pi * duty)
            ref += amp * np.cos(2 * math.pi * k * (probe - off))
            fade = band_fade(realized / k)
            if fade > 0:
                h += np.float32(amp * fade) * np.cos(2 * np.pi * k * (phase - off))
    peak = float(np.abs(ref).max())
    return (h / peak if peak > 1e-9 else h), realized


def height_field(fabric: str, px_per_cm: float, size: int, white: np.ndarray) -> np.ndarray:
    raw = FABRIC[fabric]["period"] * px_per_cm
    period = max(raw, MIN_PERIOD_PX)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    if fabric == "jersey":
        f, realized = tile_cycles(raw, size, False)
        loop = band_fade(realized) * np.cos(2 * np.pi * f * x)
        h = 0.5 + JERSEY_AMP * loop + grain(white, JERSEY_GRAIN[0] * px_per_cm, JERSEY_GRAIN[1])
    elif fabric == "rib":
        h = 0.5 + 0.45 * np.sin(2 * np.pi * x / period) + 0.05 * (white - 0.5)
    elif fabric == "denim":
        wale, _ = twill(x, y, raw, size)
        slub = np.roll(white, (size // 3, size // 7), (0, 1))
        h = (0.5 + TWILL_AMP * wale
             + grain(white, DENIM_GRAIN[0] * px_per_cm, DENIM_GRAIN[1], DENIM_GRAIN[2])
             + grain(slub, DENIM_SLUB[0] * px_per_cm, DENIM_SLUB[1]))
    elif fabric == "canvas":
        h = 0.5 + 0.20 * np.sin(2 * np.pi * x / period) + 0.20 * np.sin(2 * np.pi * y / period)
    else:
        blur = Image.fromarray((white * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(period / 2))
        h = 0.5 + 0.9 * (np.asarray(blur, np.float32) / 255 - 0.5)
    return np.clip(h, 0, 1).astype(np.float32)


def to_normal(height: np.ndarray, strength: np.ndarray) -> np.ndarray:
    p = np.pad(height, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    n = np.stack([-gx * strength, -gy * strength, np.ones_like(height)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return ((n * 0.5 + 0.5) * 255).round().clip(0, 255).astype(np.uint8)


# ---------------------------------------------------------------- per item


def texture_legacy(entry: dict, out_root: Path, size: int) -> dict:
    safe = entry["safe"]
    mesh_path = find_mesh(out_root, safe)
    if mesh_path is None:
        raise SystemExit(f"{safe}: no *_sim.obj or *_boxmesh.obj under {out_root / safe}")
    verts, uvs, faces_v, faces_vt = load_obj(mesh_path)
    if not len(uvs):
        raise SystemExit(f"{mesh_path.name} has no vt uvs")
    face, panels = face_panels(faces_v, vertex_labels(mesh_path, len(verts)))
    rows, cols, f, xyz = texel_geometry(verts, uvs, faces_v, faces_vt, size)
    keep = face[f] >= 0
    rows, cols, xyz, panel_of = rows[keep], cols[keep], xyz[keep], face[f][keep]
    ids = np.zeros((size, size), np.int32)
    ids[rows, cols] = panel_of + 1

    tags = entry["item"].get("tags") or {}
    meta = entry["meta"]
    crop, dom = garment_crop(entry["dir"], entry["item"])
    photo = flatten(crop, dom)
    fabric = fabric_for(meta.get("material") or tags.get("material"),
                        meta.get("category") or tags.get("category"), meta.get("role"))
    kinds = {p: panel_kind(p) for p in panels}
    kind_of = np.array([kinds[p] for p in panels])[panel_of]

    color = np.broadcast_to(dom, (len(rows), 3)).astype(np.float32).copy()
    front, back = kind_of == "front", kind_of == "back"
    # the crop frames the whole garment, so the whole garment's extent is what maps onto it
    box = np.array([xyz.min(0), xyz.max(0)])
    if front.any():
        color[front] = project(photo, xyz[front], box, False, 0.0)
    if back.any():
        # mirrored to line up with the front through the body, blurred so prints don't read backwards
        color[back] = project(photo, xyz[back], box, True, BACK_BLUR) * BACK_MIX + dom * (1 - BACK_MIX)

    panel_dir = mesh_path.parent / "panels"
    white = noise(size)
    cache: dict[tuple[str, float], np.ndarray] = {}
    height = np.full((size, size), 0.5, np.float32)
    rough = np.ones((size, size), np.float32)
    strength = np.zeros((size, size), np.float32)
    counts = np.bincount(panel_of, minlength=len(panels))
    areas = [panel_area_cm2(panel_dir, p) for p in panels]
    scales = [math.sqrt(c / a) for c, a in zip(counts, areas) if a > 1e-6 and c]
    median_ppc = float(np.median(scales)) if scales else size / 100.0
    report = {}
    for i, p in enumerate(panels):
        if not counts[i]:
            continue
        sel = panel_of == i
        r, c = rows[sel], cols[sel]
        ppc = math.sqrt(counts[i] / areas[i]) if areas[i] > 1e-6 else median_ppc
        fab = "rib" if kinds[p] == "rib" else fabric
        key = (fab, round(ppc, 1))
        if key not in cache:
            cache[key] = height_field(fab, ppc, size, white)
        height[r, c] = cache[key][r, c]
        rough[r, c] = FABRIC[fab]["rough"]
        strength[r, c] = FABRIC[fab]["strength"]
        report[p] = {"kind": kinds[p], "fabric": fab, "texels": int(counts[i]),
                     "panel_cm2": round(areas[i], 1), "px_per_cm": round(ppc, 2)}
        if kinds[p] not in ("front", "back"):
            tone = region_color(crop, kinds[p], dom)
            color[sel] = tone
            report[p]["color"] = [int(v) for v in tone]

    atlas = np.broadcast_to(dom, (size, size, 3)).astype(np.float32).copy()
    atlas[rows, cols] = color
    filled = np.zeros((size, size), bool)
    filled[rows, cols] = True
    filled = grow(filled, [atlas, height, rough, strength], FILL_PX)
    seam = borders(ids, SEAM_PX)
    atlas[seam] *= SEAM_DARKEN

    basecolor = atlas.round().clip(0, 255).astype(np.uint8)
    rough_px = np.zeros((size, size, 3), np.uint8)
    rough_px[..., 1] = (rough * 255).round().clip(0, 255).astype(np.uint8)
    normal = to_normal(height, strength)

    tex_dir = out_root / safe / "texture_legacy"
    tex_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(basecolor).save(tex_dir / "basecolor.png")
    Image.fromarray(normal).save(tex_dir / "normal.png")
    Image.fromarray(rough_px).save(tex_dir / "roughness.png")

    outline = basecolor.copy()
    outline[borders(ids, 1)] = [255, 0, 255]
    preview = Image.fromarray(outline)
    draw = ImageDraw.Draw(preview)
    for i, p in enumerate(panels):
        if counts[i]:
            sel = panel_of == i
            draw.text((int(cols[sel].mean()) - 20, int(rows[sel].mean())), p, fill=(255, 255, 0))
    preview.save(tex_dir / "preview.png")

    info = {
        "mode": "legacy", "safe": safe, "mesh": str(mesh_path.relative_to(out_root)), "fabric": fabric,
        "dominant": [int(v) for v in dom], "size": size,
        "garment_cm": [round(float(v), 1) for v in (box[1] - box[0])],
        "coverage": round(float(filled.mean()), 3), "unlabeled_faces": int((face < 0).sum()),
        "panels": report,
    }
    (tex_dir / "meta.json").write_text(json.dumps(info, indent=2))
    return info


def texture_v2(entry: dict, inputs: Path, out_root: Path, normal_size: int = 2048) -> dict:
    from drape import atlas, delight, panels, spec, synth

    safe, item_dir = entry["safe"], entry["dir"]
    mesh_path = find_mesh(out_root, safe)
    if mesh_path is None:
        raise SystemExit(f"{safe}: no *_sim.obj or *_boxmesh.obj under {out_root / safe}")
    if not (item_dir / "spec.json").exists():
        spec.process({"safe": safe}, inputs, force=False)
    if not (item_dir / "albedo.png").exists():
        delight.process_item(item_dir)
    # rebuilt from the pattern this mesh came from, so panels and the atlas fit never drift apart
    panels.write_item(out_root, safe, mesh_path.parent / f"{mesh_name(mesh_path)}_specification.json")
    pspec = spec.load_spec(item_dir)

    fits = atlas.fit_islands(mesh_path)
    s = atlas.atlas_scale(fits)
    periods = [r.period_cm for r in pspec.repeats]
    size = atlas.pick_size(atlas.features_cm(pspec.repeats), s)
    collapse = atlas.collapse_cm(size, s)
    res = synth.synthesize(item_dir, out_root / safe, ppc=atlas.ppc_for(size, s), collapse_period_cm=collapse)
    packed = atlas.pack(mesh_path, res["panels"], size, fits)
    rows, cols, panel_of, names = packed["rows"], packed["cols"], packed["panel_of"], packed["panels"]

    tags = entry["item"].get("tags") or {}
    meta = entry["meta"]
    fabric = fabric_for(meta.get("material") or tags.get("material"),
                        meta.get("category") or tags.get("category"), meta.get("role"))
    rib = {n: bool(res["panels"].get(n, {}).get("rib")) for n in names}
    ppc = size * s
    white = noise(size)
    height = np.full((size, size), 0.5, np.float32)
    rough = np.ones((size, size), np.float32)
    strength = np.zeros((size, size), np.float32)
    fields: dict[str, np.ndarray] = {}
    report = {}
    for i, n in enumerate(names):
        sel = panel_of == i
        if not sel.any():
            continue
        fab = "rib" if rib[n] else fabric
        if fab not in fields:
            fields[fab] = height_field(fab, ppc, size, white)
        r, c = rows[sel], cols[sel]
        height[r, c] = fields[fab][r, c]
        rough[r, c] = FABRIC[fab]["rough"]
        strength[r, c] = FABRIC[fab]["strength"]
        report[n] = {"fabric": fab, "texels": int(sel.sum()), "rib": rib[n]}

    rgb = packed["rgb"]
    filled = np.zeros((size, size), bool)
    filled[rows, cols] = True
    filled = grow(filled, [rgb, height, rough, strength], FILL_PX)
    rgb[borders(packed["ids"], SEAM_PX)] *= SEAM_DARKEN
    basecolor = rgb.round().clip(0, 255).astype(np.uint8)
    normal = Image.fromarray(to_normal(height, strength))
    rough_px = np.zeros((size, size, 3), np.uint8)
    rough_px[..., 1] = (rough * 255).round().clip(0, 255).astype(np.uint8)
    rough_img = Image.fromarray(rough_px)
    if size > normal_size:
        normal = normal.resize((normal_size, normal_size), Image.Resampling.BOX)
        rough_img = rough_img.resize((normal_size, normal_size), Image.Resampling.BOX)

    tex_dir = out_root / safe / "texture"
    tex_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(basecolor).save(tex_dir / "basecolor.png")
    normal.save(tex_dir / "normal.png")
    rough_img.save(tex_dir / "roughness.png")
    preview = basecolor.copy()
    preview[borders(packed["ids"], 1)] = [255, 0, 255]
    Image.fromarray(preview).resize((1024, 1024), Image.Resampling.BOX).save(tex_dir / "preview.png")

    info = {
        "mode": "v2", "safe": safe, "mesh": str(mesh_path.relative_to(out_root)), "fabric": fabric, "size": size,
        "atlas_ppc": round(ppc, 3), "synth_ppc": res["ppc"], "uv_per_cm": s,
        "min_period_cm": res.get("min_period_cm"),
        "min_period_px": round(min(periods) * ppc, 2) if periods else None,
        "collapse_period_cm": round(collapse, 4), "coverage": round(float(filled.mean()), 3),
        "fit_resid_cm": max(f["resid_cm"] for f in fits.values()), "missing_panels": packed["missing"],
        "synth": res.get("meta", {}), "panels": report,
    }
    (tex_dir / "meta.json").write_text(json.dumps(info, indent=2, default=str))
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs")
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out")
    ap.add_argument("--only")
    ap.add_argument("--legacy", action="store_true", help="old front projection, written to <safe>/texture_legacy/")
    ap.add_argument("--size", type=int, default=SIZE, help="legacy atlas size; v2 picks 2048 or 4096 itself")
    a = ap.parse_args()

    entries = item_dirs(a.inputs, a.only)
    if not entries:
        raise SystemExit(f"no items with item.json under {a.inputs}")
    for e in entries:
        if a.legacy:
            info = texture_legacy(e, a.out, a.size)
            kinds = Counter(p["kind"] for p in info["panels"].values())
            ppc = [p["px_per_cm"] for p in info["panels"].values()]
            print(f"{info['safe']} | legacy | {Path(info['mesh']).name} | {info['fabric']} | "
                  f"panels {dict(sorted(kinds.items()))} | atlas {info['coverage'] * 100:.1f}% | "
                  f"px/cm {min(ppc):.1f}-{max(ppc):.1f} | unlabeled faces {info['unlabeled_faces']}")
            continue
        info = texture_v2(e, a.inputs, a.out)
        print(f"{info['safe']} | v2 | {Path(info['mesh']).name} | {info['size']}px @ {info['atlas_ppc']:.1f} px/cm | "
              f"min period {info['min_period_px']} px | atlas {info['coverage'] * 100:.1f}% | "
              f"fit {info['fit_resid_cm']:.1e} cm | missing {info['missing_panels'] or 'none'}")
    print(f"ok: {len(entries)} items -> {a.out}/<safe>/{'texture_legacy' if a.legacy else 'texture'}/")


if __name__ == "__main__":
    main()
