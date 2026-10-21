"""Pack per-panel cm rasters into the garment's UV atlas: every texel gets its exact panel-local cm."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from drape._repo import bootstrap

bootstrap()

from pygarment.pattern.rotation import euler_xyz_to_R  # noqa: E402

from drape.texture import load_obj, mesh_name, vertex_labels  # noqa: E402

SIZES = (2048, 4096)
MIN_PERIOD_PX = 4.0
COLLAPSE_PX = 2.0


def spec_for(mesh_path: Path) -> dict:
    path = mesh_path.parent / f"{mesh_name(mesh_path)}_specification.json"
    if not path.exists():
        raise SystemExit(f"{path} missing - the atlas needs the pattern the mesh was built from")
    return json.loads(path.read_text())


def fit_islands(mesh_path: Path) -> dict[str, dict]:
    """Per panel: uv = s * panel_cm + off, least squares over the boxmesh vertices that belong to it alone."""
    box = mesh_path.parent / f"{mesh_name(mesh_path)}_boxmesh.obj"
    if not box.exists():
        raise SystemExit(f"{box} missing - the atlas fit needs the pre-sim boxmesh")
    verts, uvs, faces_v, faces_vt = load_obj(box)
    labels = np.array(vertex_labels(mesh_path, len(verts)))
    panels = spec_for(mesh_path)["pattern"]["panels"]
    corners = np.unique(np.stack([faces_v.ravel(), faces_vt.ravel()], 1), axis=0)
    uv_count = np.bincount(corners[:, 0], minlength=len(verts))
    fits = {}
    for name, p in panels.items():
        sel = corners[(labels[corners[:, 0]] == name) & (uv_count[corners[:, 0]] == 1)]
        if len(sel) < 3:
            continue
        rot = np.asarray(euler_xyz_to_R(p["rotation"]))
        local = (verts[sel[:, 0]] - np.asarray(p["translation"])) @ rot
        uv = uvs[sel[:, 1]]
        a = np.zeros((2 * len(sel), 3))
        a[0::2, 0], a[0::2, 1] = local[:, 0], 1.0
        a[1::2, 0], a[1::2, 2] = local[:, 1], 1.0
        sol = np.linalg.lstsq(a, uv.ravel(), rcond=None)[0]
        resid = np.abs(a @ sol - uv.ravel()).max() / max(sol[0], 1e-12)
        fits[name] = {"s": float(sol[0]), "off": sol[1:].tolist(), "resid_cm": float(resid),
                      "plane_cm": float(np.abs(local[:, 2]).max()), "n": int(len(sel))}
    if not fits:
        raise SystemExit(f"{box.name}: no panel vertices to fit the atlas")
    return fits


def island_panels(faces_v: np.ndarray, faces_vt: np.ndarray, n_uv: int, labels: list[str]) -> tuple[np.ndarray, list[str]]:
    """Panel index per face from its uv island; vertex-label votes misplace faces whose corners are all seam vertices."""
    lab = np.asarray(labels)
    panels = sorted({v for v in labels if v and not v.startswith("stitch")})
    index = {p: i for i, p in enumerate(panels)}
    edges = np.concatenate([faces_vt[:, [0, 1]], faces_vt[:, [1, 2]]])
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(n_uv, n_uv))
    comp = connected_components(graph, directed=False)[1][faces_vt[:, 0]]
    face = np.full(len(faces_v), -1, np.int64)
    for c in np.unique(comp):
        sel = comp == c
        names = [n for n in lab[faces_v[sel].ravel()] if n in index]
        if names:
            vals, counts = np.unique(names, return_counts=True)
            face[sel] = index[vals[counts.argmax()]]
    return face, panels


def atlas_scale(fits: dict[str, dict]) -> float:
    return float(np.median([f["s"] for f in fits.values()]))


def pick_size(min_period_cm: float | None, s: float) -> int:
    if min_period_cm and min_period_cm * SIZES[0] * s < MIN_PERIOD_PX:
        return SIZES[1]
    return SIZES[0]


def texel_panels(uvs: np.ndarray, faces_vt: np.ndarray, face_panel: np.ndarray, size: int) -> tuple[np.ndarray, ...]:
    """Rasterize uv triangles: row, col and panel index of every covered texel."""
    tri = uvs[faces_vt] * [size, -size] + [0, size]
    img = Image.new("I", (size, size), 0)
    draw = ImageDraw.Draw(img)
    for i, poly in enumerate(tri.reshape(-1, 6).tolist(), 1):
        if face_panel[i - 1] >= 0:
            draw.polygon(poly, fill=i, outline=i)
    painted = np.asarray(img).astype(np.int64)
    rows, cols = np.nonzero(painted)
    return rows, cols, face_panel[painted[rows, cols] - 1]


def texel_cm(rows: np.ndarray, cols: np.ndarray, size: int, fit: dict) -> np.ndarray:
    uv = np.stack([(cols + 0.5) / size, 1.0 - (rows + 0.5) / size], 1)
    return (uv - np.asarray(fit["off"])) / fit["s"]


def box_sample(raster: np.ndarray, x0: float, y1: float, ppc: float, xy: np.ndarray, half_cm: float) -> np.ndarray:
    """Exact area average of a cm raster over squares centred at xy: summed-area table, bilinear at the box corners."""
    h, w = raster.shape[:2]
    sat = np.zeros((h + 1, w + 1) + raster.shape[2:], np.float64)
    sat[1:, 1:] = raster.astype(np.float64).cumsum(0).cumsum(1)
    cx, cy = (xy[:, 0] - x0) * ppc, (y1 - xy[:, 1]) * ppc
    r = half_cm * ppc

    def at(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        x, y = np.clip(x, 0, w), np.clip(y, 0, h)
        i0, j0 = np.minimum(np.floor(y).astype(np.int64), h - 1), np.minimum(np.floor(x).astype(np.int64), w - 1)
        fy, fx = (y - i0)[:, None], (x - j0)[:, None]
        return ((1 - fy) * ((1 - fx) * sat[i0, j0] + fx * sat[i0, j0 + 1])
                + fy * ((1 - fx) * sat[i0 + 1, j0] + fx * sat[i0 + 1, j0 + 1]))

    xa, xb = np.clip(cx - r, 0, w), np.clip(cx + r, 0, w)
    ya, yb = np.clip(cy - r, 0, h), np.clip(cy + r, 0, h)
    area = np.maximum((xb - xa) * (yb - ya), 1e-9)[:, None]
    return (at(xb, yb) - at(xa, yb) - at(xb, ya) + at(xa, ya)) / area


def pack(mesh_path: Path, rasters: dict[str, dict], size: int, fits: dict[str, dict] | None = None) -> dict:
    """rasters: panel -> {"rgb": HxWx3 float, "x0", "y1", "ppc"}; returns the packed atlas and its texel bookkeeping."""
    fits = fits or fit_islands(mesh_path)
    verts, uvs, faces_v, faces_vt = load_obj(mesh_path)
    face, panels = island_panels(faces_v, faces_vt, len(uvs), vertex_labels(mesh_path, len(verts)))
    rows, cols, panel_of = texel_panels(uvs, faces_vt, face, size)
    atlas = np.zeros((size, size, 3), np.float32)
    ids = np.zeros((size, size), np.int32)
    ids[rows, cols] = panel_of + 1
    missing = []
    for i, name in enumerate(panels):
        sel = panel_of == i
        if not sel.any():
            continue
        if name not in fits or name not in rasters:
            missing.append(name)
            continue
        fit, ras = fits[name], rasters[name]
        xy = texel_cm(rows[sel], cols[sel], size, fit)
        atlas[rows[sel], cols[sel]] = box_sample(ras["rgb"], ras["x0"], ras["y1"], ras["ppc"], xy, 0.5 / (size * fit["s"]))
    return {"rgb": atlas, "rows": rows, "cols": cols, "panel_of": panel_of, "panels": panels, "ids": ids,
            "face": face, "missing": missing, "ppc": size * atlas_scale(fits), "fits": fits}


def collapse_cm(size: int, s: float) -> float:
    return COLLAPSE_PX / (size * s)


def ppc_for(size: int, s: float, floor: float = 20.0) -> float:
    return max(floor, math.ceil(2 * size * s))
