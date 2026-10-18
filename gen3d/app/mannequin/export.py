from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.glb import add_accessor, new_gltf, write_glb
from app.mannequin.generator import body_mesh, vertex_normals
from app.mannequin.params import SLIDERS

ZERO = dict.fromkeys(SLIDERS, 0.0)
AVATAR_MATERIAL = {
    "name": "mannequin",
    "pbrMetallicRoughness": {"baseColorFactor": [0.78, 0.78, 0.78, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.85},
}


def morphs(build: Callable[[dict], tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    base, faces = build(ZERO)
    targets = np.stack([build({**ZERO, k: 1.0})[0] for k in SLIDERS]) - base
    return base, faces, targets


def blend(base: np.ndarray, targets: np.ndarray, weights) -> np.ndarray:
    return base + np.tensordot(np.broadcast_to(np.asarray(weights, float), len(SLIDERS)), targets, 1)


def morph_normals(base: np.ndarray, faces: np.ndarray, targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    normals = vertex_normals(base, faces)
    return normals, np.stack([vertex_normals(base + t, faces) - normals for t in targets])


def _f32(a: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(a, dtype=np.float32)


def write_morph_glb(
    path: Path,
    name: str,
    verts: np.ndarray,
    normals: np.ndarray,
    targets: np.ndarray,
    target_normals: np.ndarray,
    faces: np.ndarray,
    material: dict,
    uv: np.ndarray | None = None,
) -> Path:
    gltf, blob = new_gltf()
    attrs = {"POSITION": add_accessor(gltf, blob, _f32(verts)), "NORMAL": add_accessor(gltf, blob, _f32(normals))}
    if uv is not None:
        attrs["TEXCOORD_0"] = add_accessor(gltf, blob, _f32(uv))
    prim = {
        "attributes": attrs,
        "indices": add_accessor(gltf, blob, faces.astype(np.uint32).ravel(), indices=True),
        "material": 0,
        "targets": [
            {"POSITION": add_accessor(gltf, blob, _f32(t)), "NORMAL": add_accessor(gltf, blob, _f32(tn))}
            for t, tn in zip(targets, target_normals)
        ],
    }
    gltf.update(
        materials=[material],
        meshes=[{"name": name, "primitives": [prim], "weights": [0.5] * len(SLIDERS), "extras": {"targetNames": list(SLIDERS)}}],
        nodes=[{"name": name, "mesh": 0}],
        scenes=[{"nodes": [0]}],
        scene=0,
    )
    return write_glb(path, gltf, blob)


def export_avatar(base: str, path: Path) -> Path:
    verts, faces, targets = morphs(lambda s: body_mesh(base, s))
    normals, target_normals = morph_normals(verts, faces, targets)
    return write_morph_glb(path, f"avatar_{base}", verts, normals, targets, target_normals, faces, AVATAR_MATERIAL)
