import logging
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from app.glb import add_accessor, new_gltf, read_accessor, read_glb, write_glb

log = logging.getLogger(__name__)
MAX_CELLS = 128
SAMPLES_PER_VOXEL_FACE = 16
MAX_SAMPLES = 2_000_000
GREY_LINEAR = 0.6


def _scene(glb_path: Path) -> trimesh.Scene:
    gltf, blob = read_glb(glb_path)
    morphed = False
    for mesh in gltf.get("meshes", []):
        if not any(mesh.get("weights", [])):
            continue
        for prim in mesh["primitives"]:
            verts = read_accessor(gltf, blob, prim["attributes"]["POSITION"]).astype(np.float64)
            for weight, target in zip(mesh["weights"], prim.get("targets", [])):
                if "POSITION" in target:
                    verts += weight * read_accessor(gltf, blob, target["POSITION"])
            prim["attributes"]["POSITION"] = add_accessor(gltf, blob, verts.astype(np.float32))
            morphed = True
    with tempfile.TemporaryDirectory() as tmp:
        # trimesh skips morph targets, so load a copy with the default weights baked in
        return trimesh.load_scene(write_glb(Path(tmp) / "baked.glb", gltf, blob) if morphed else glb_path)


def _instances(glb_path: Path) -> list[tuple[trimesh.Trimesh, trimesh.visual.base.Visuals]]:
    scene = _scene(glb_path)
    # not scene.dump(): it copies every texture, which raises on a corrupt image
    instances = []
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        geom = scene.geometry[name]
        if isinstance(geom, trimesh.Trimesh) and geom.area > 0:
            world = trimesh.Trimesh(trimesh.transform_points(geom.vertices, transform), geom.faces, process=False)
            instances.append((world, geom.visual))
    return instances


def _linear(srgb: np.ndarray) -> np.ndarray:
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def _samples(mesh: trimesh.Trimesh, visual: trimesh.visual.base.Visuals, count: int) -> tuple[np.ndarray, np.ndarray]:
    points, face, bary = trimesh.sample.sample_surface(mesh, count, return_barycentric=True, seed=0)
    corners = mesh.faces[face]
    material = getattr(visual, "material", None)
    vertex = visual.vertex_colors if visual.kind == "vertex" else getattr(visual, "vertex_attributes", {}).get("color")
    # glTF base color = factor * texture * COLOR_0, all linear once the sRGB texture is converted
    color = np.full((count, 3), GREY_LINEAR if material is None and vertex is None else 1.0)
    if getattr(material, "baseColorFactor", None) is not None:
        color *= material.baseColorFactor[:3] / 255
    image, uv = getattr(material, "baseColorTexture", None), getattr(visual, "uv", None)
    if image is not None and uv is not None:
        try:
            texels = np.asarray(image.convert("RGB"))
            h, w = texels.shape[:2]
            st = (bary[..., None] * uv[corners]).sum(1)
            rows = np.clip(((1 - st[:, 1]) * h).astype(int), 0, h - 1)
            cols = np.clip((st[:, 0] * w).astype(int), 0, w - 1)
            color *= _linear(texels[rows, cols] / 255)
        except Exception:
            log.warning("texture sampling failed, using flat colors", exc_info=True)
    if vertex is not None:
        color *= (bary[..., None] * trimesh.visual.color.to_float(vertex)[corners][..., :3]).sum(1)
    return points, color


def _write(out_path: Path, grid: trimesh.voxel.VoxelGrid, pitch: float, colors: np.ndarray) -> Path:
    box = trimesh.creation.box()
    occupied, cells = np.pad(grid.matrix, 1), grid.sparse_indices + 1
    exposed = np.stack([~occupied[tuple((cells + d).T)] for d in np.round(box.face_normals).astype(int)], 1)
    voxel, tri = np.nonzero(exposed)
    used, faces = np.unique(8 * voxel[:, None] + box.faces[tri], return_inverse=True)
    voxel, corner = np.divmod(used, 8)
    gltf, blob = new_gltf()
    prim = {
        "attributes": {
            "POSITION": add_accessor(gltf, blob, (grid.points[voxel] + pitch * box.vertices[corner]).astype(np.float32)),
            "COLOR_0": add_accessor(gltf, blob, colors[voxel].astype(np.float32)),
        },
        "indices": add_accessor(gltf, blob, faces.astype(np.uint32).ravel(), indices=True),
        "material": 0,
    }
    gltf.update(
        materials=[{"name": "voxel", "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.9}}],
        meshes=[{"name": "voxel", "primitives": [prim]}],
        nodes=[{"name": "voxel", "mesh": 0}],
        scenes=[{"nodes": [0]}],
        scene=0,
    )
    return write_glb(out_path, gltf, blob)


def voxelize(glb_path: Path, out_path: Path, pitch: float = 0.02) -> Path:
    instances = _instances(glb_path)
    if not instances:
        raise ValueError(f"{glb_path.name} has no surface to voxelize")
    surface = trimesh.util.concatenate([mesh for mesh, _ in instances])
    pitch = max(pitch, float(surface.extents.max()) / MAX_CELLS)
    grid = surface.voxelized(pitch)
    budget = min(SAMPLES_PER_VOXEL_FACE * surface.area / pitch**2, MAX_SAMPLES) / surface.area
    samples = [_samples(mesh, visual, int(budget * mesh.area) + 1) for mesh, visual in instances]
    points, colors = (np.vstack(s) for s in zip(*samples))
    nearest = cKDTree(points).query(grid.points, workers=-1)[1]
    return _write(out_path, grid, pitch, colors[nearest])
