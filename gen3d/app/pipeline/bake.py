import asyncio
import io
import itertools
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage
from scipy.spatial import cKDTree

from app.glb import add_bytes, read_accessor, read_glb, write_glb

log = logging.getLogger(__name__)
TEX_W, TEX_H = 2048, 1024
SOURCE_TEX_MAX = 2048
CLAMP_TO_EDGE = 33071
BACK_BLUR = 24 / 1024
BACK_MIX = 0.7
PROBE_POINTS = 4096
MAX_OFF = 0.01
GAIN = (0.5, 3.0)
ROTATIONS = [
    m
    for m in (np.diag(s) @ p for p in itertools.permutations(np.eye(3)) for s in itertools.product((1, -1), repeat=3))
    if np.linalg.det(m) > 0
]


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


def copy_texture(textured_path: Path, mesh_path: Path, out_path: Path) -> Path:
    gltf, blob = read_glb(textured_path)
    index = gltf["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    view = gltf["bufferViews"][gltf["images"][gltf["textures"][index]["source"]]["bufferView"]]
    start = view.get("byteOffset", 0)
    return inject_texture(mesh_path, Image.open(io.BytesIO(bytes(blob[start : start + view["byteLength"]]))), out_path)


def uv_layout(mesh_path: Path) -> str:
    return read_glb(mesh_path)[0]["meshes"][0].get("extras", {}).get("uv_layout", "front_back")


def toe_right(photo: Image.Image, alpha: np.ndarray) -> Image.Image:
    heights = (alpha > 127).sum(0)
    end = max(len(heights) // 4, 1)
    # a side-view shoe is taller at the heel than at the toe
    if heights[-end:].mean() > heights[:end].mean():
        return photo.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return photo


def mock_texture(mesh_path: Path, image_path: Path, out_path: Path) -> Path:
    px, color = cutout(image_path)
    alpha = px[..., 3:] / 255
    photo = Image.fromarray((px[..., :3] * alpha + color * (1 - alpha)).round().astype(np.uint8))
    if uv_layout(mesh_path) == "side":
        tex = toe_right(photo, px[..., 3]).resize((TEX_W, TEX_H), Image.Resampling.LANCZOS)
        return inject_texture(mesh_path, tex, out_path)
    front = photo.resize((TEX_W // 2, TEX_H), Image.Resampling.LANCZOS)
    # mirrored to line up with the front through the body, blurred so prints don't read backwards
    back = front.transpose(Image.Transpose.FLIP_LEFT_RIGHT).filter(ImageFilter.GaussianBlur(BACK_BLUR * front.width))
    tex = Image.new("RGB", (TEX_W, TEX_H))
    tex.paste(front)
    tex.paste(Image.blend(Image.new("RGB", back.size, tuple(color.tolist())), back, BACK_MIX), (TEX_W // 2, 0))
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


def unnormalize(points: np.ndarray, src: np.ndarray, dst: np.ndarray, target: cKDTree) -> np.ndarray:
    # retexturing hands the mesh back recentered in a unit cube, maybe turned: match bounds, then try each axis turn
    size = np.ptp(dst, 0).max()
    k = size / np.ptp(src, 0).max()
    fits = [(k * rot.T, dst.mean(0) - k * rot @ src.mean(0)) for rot in ROTATIONS]
    probe = points[:: max(len(points) // PROBE_POINTS, 1)]
    query = {"distance_upper_bound": MAX_OFF * size, "workers": -1}
    score = [np.median(target.query(probe @ a + b, **query)[0]) for a, b in fits]
    best = int(np.argmin(score))
    # garments are near mirror-symmetric: only turn when that fits clearly better than as-is
    a, b = fits[best if score[best] < score[0] / 2 else 0]
    return points @ a + b


def match_colors(colors: np.ndarray, front: np.ndarray, photo: np.ndarray) -> np.ndarray:
    # retextures come back darker than the photo: move the front's mean and spread onto the photo's
    src, ref = colors[front].astype(float), photo.astype(float)
    gain = np.clip(ref.std(0) / np.maximum(src.std(0), 1.0), *GAIN)
    return np.clip((colors - src.mean(0)) * gain + ref.mean(0), 0, 255).round().astype(np.uint8)


def bake(mesh_path: Path, source: trimesh.Trimesh, out_path: Path, image_path: Path) -> Path:
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
    bounds = np.array([verts.min(0), verts.max(0)])
    dist, idx = cKDTree(unnormalize(s_xyz, source.bounds, bounds, cKDTree(xyz))).query(xyz, workers=-1)
    if np.median(dist) > MAX_OFF * np.ptp(bounds, 0).max():
        raise ValueError(f"retextured mesh is {np.median(dist):.3f} m off the template")
    px, _ = cutout(image_path)
    tex = np.zeros((TEX_H, TEX_W, 3), np.uint8)
    tex[rows, cols] = match_colors(np.asarray(image)[s_rows, s_cols][idx], cols < TEX_W // 2, px[px[..., 3] > 127, :3])
    empty = np.ones((TEX_H, TEX_W), bool)
    empty[rows, cols] = False
    near = ndimage.distance_transform_edt(empty, return_distances=False, return_indices=True)
    return inject_texture(mesh_path, Image.fromarray(tex[near[0], near[1]]), out_path)


async def texture_or_mock(
    mesh_path: Path, image_path: Path, out_path: Path, retexture: Callable[[], Awaitable[trimesh.Trimesh]]
) -> Path:
    if uv_layout(mesh_path) == "side":
        log.info("%s has overlapping side uvs, projecting the photo instead of retexturing", mesh_path.name)
    else:
        try:
            return await asyncio.to_thread(bake, mesh_path, await retexture(), out_path, image_path)
        except Exception:
            log.exception("real texturing failed for %s, using the mock texture", mesh_path.name)
    return await asyncio.to_thread(mock_texture, mesh_path, image_path, out_path)
