import asyncio
import io
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree

from app.glb import add_bytes, read_accessor, read_glb, write_glb

log = logging.getLogger(__name__)
TEX_W, TEX_H = 2048, 1024
SOURCE_TEX_MAX = 2048
CLAMP_TO_EDGE = 33071


def cutout(image_path: Path) -> tuple[np.ndarray, np.ndarray]:
    px = np.asarray(Image.open(image_path).convert("RGBA"))
    ys, xs = np.nonzero(px[..., 3] > 127)
    if not len(xs):
        raise ValueError(f"{image_path.name} has no opaque pixels")
    px = px[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    rgb = px[px[..., 3] > 127, :3]
    bins = (rgb // 32).astype(np.int64) @ [64, 8, 1]
    return px, rgb[bins == np.bincount(bins).argmax()].mean(0).round().astype(np.uint8)


def inject_texture(mesh_path: Path, texture: Image.Image, out_path: Path) -> Path:
    gltf, blob = read_glb(mesh_path)
    png = io.BytesIO()
    texture.save(png, "PNG")
    images = gltf.setdefault("images", [])
    images.append({"bufferView": add_bytes(gltf, blob, png.getvalue()), "mimeType": "image/png"})
    samplers = gltf.setdefault("samplers", [])
    samplers.append({"wrapS": CLAMP_TO_EDGE, "wrapT": CLAMP_TO_EDGE})
    textures = gltf.setdefault("textures", [])
    textures.append({"source": len(images) - 1, "sampler": len(samplers) - 1})
    pbr = gltf["materials"][0].setdefault("pbrMetallicRoughness", {})
    pbr.update(baseColorTexture={"index": len(textures) - 1}, baseColorFactor=[1.0, 1.0, 1.0, 1.0])
    return write_glb(out_path, gltf, blob)


def mock_texture(mesh_path: Path, image_path: Path, out_path: Path) -> Path:
    px, color = cutout(image_path)
    alpha = px[..., 3:] / 255
    front = Image.fromarray((px[..., :3] * alpha + color * (1 - alpha)).round().astype(np.uint8))
    tex = Image.new("RGB", (TEX_W, TEX_H), tuple(color.tolist()))
    tex.paste(front.resize((TEX_W // 2, TEX_H), Image.Resampling.LANCZOS))
    return inject_texture(mesh_path, tex, out_path)


def template_mesh(mesh_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    gltf, blob = read_glb(mesh_path)
    mesh = gltf["meshes"][0]
    prim = mesh["primitives"][0]
    verts = read_accessor(gltf, blob, prim["attributes"]["POSITION"]).astype(np.float64)
    for weight, target in zip(mesh.get("weights", []), prim.get("targets", [])):
        verts += weight * read_accessor(gltf, blob, target["POSITION"])
    faces = read_accessor(gltf, blob, prim["indices"]).reshape(-1, 3)
    return verts, faces, read_accessor(gltf, blob, prim["attributes"]["TEXCOORD_0"]).astype(np.float64)


def texel_points(verts: np.ndarray, faces: np.ndarray, uv: np.ndarray, w: int, h: int) -> tuple[np.ndarray, ...]:
    tris = (uv * [w, h])[faces]
    ids = Image.new("I", (w, h))
    draw = ImageDraw.Draw(ids)
    for i, tri in enumerate(tris.reshape(-1, 6).tolist(), 1):
        draw.polygon(tri, fill=i)
    face_id = np.asarray(ids)
    rows, cols = np.nonzero(face_id)
    fi = face_id[rows, cols] - 1
    a, b, c = tris.transpose(1, 0, 2)
    e1, e2 = b - a, c - a
    den = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    den[np.abs(den) < 1e-12] = 1e-12
    d = np.stack([cols, rows], 1) + 0.5 - a[fi]
    l1 = (d[:, 0] * e2[fi, 1] - d[:, 1] * e2[fi, 0]) / den[fi]
    l2 = (e1[fi, 0] * d[:, 1] - e1[fi, 1] * d[:, 0]) / den[fi]
    # texels on a triangle's edge can sit just outside it: clamp onto the triangle
    bary = np.clip(np.stack([1 - l1 - l2, l1, l2], 1), 0, 1)
    bary /= bary.sum(1, keepdims=True)
    f = faces[fi]
    return rows, cols, sum(bary[:, k, None] * verts[f[:, k]] for k in range(3))


def bake(mesh_path: Path, source: trimesh.Trimesh, out_path: Path) -> Path:
    image = getattr(getattr(source.visual, "material", None), "baseColorTexture", None)
    if image is None or getattr(source.visual, "uv", None) is None:
        raise ValueError("retextured mesh has no base color texture")
    image = image.convert("RGB")
    image.thumbnail((SOURCE_TEX_MAX, SOURCE_TEX_MAX))
    s_rows, s_cols, s_xyz = texel_points(
        source.vertices, source.faces, source.visual.uv * [1, -1] + [0, 1], *image.size
    )
    verts, faces, uv = template_mesh(mesh_path)
    rows, cols, xyz = texel_points(verts, faces, uv, TEX_W, TEX_H)
    lo, hi = verts.min(0), verts.max(0)
    s_lo, s_hi = source.bounds
    # retexturing hands back the mesh normalized to a unit cube: match bounds to undo it
    s_xyz = (s_xyz - (s_lo + s_hi) / 2) * ((hi - lo).max() / (s_hi - s_lo).max()) + (lo + hi) / 2
    dist, idx = cKDTree(s_xyz).query(xyz, workers=-1)
    if np.median(dist) > 0.01 * (hi - lo).max():
        raise ValueError(f"retextured mesh is {np.median(dist):.3f} m off the template")
    tex = np.zeros((TEX_H, TEX_W, 3), np.uint8)
    tex[rows, cols] = np.asarray(image)[s_rows, s_cols][idx]
    empty = np.ones((TEX_H, TEX_W), bool)
    empty[rows, cols] = False
    near = ndimage.distance_transform_edt(empty, return_distances=False, return_indices=True)
    return inject_texture(mesh_path, Image.fromarray(tex[near[0], near[1]]), out_path)


async def texture_or_mock(
    mesh_path: Path, image_path: Path, out_path: Path, retexture: Callable[[], Awaitable[trimesh.Trimesh]]
) -> Path:
    try:
        return await asyncio.to_thread(bake, mesh_path, await retexture(), out_path)
    except Exception:
        log.exception("real texturing failed for %s, using the mock texture", mesh_path.name)
        return await asyncio.to_thread(mock_texture, mesh_path, image_path, out_path)
