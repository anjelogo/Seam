from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.glb import add_accessor, new_gltf, write_glb
from app.mannequin.generator import body_mesh, vertex_normals
from app.mannequin.params import SLIDERS

ZERO, MID = dict.fromkeys(SLIDERS, 0.0), dict.fromkeys(SLIDERS, 0.5)
# garment-only targets after the body sliders, default influence 0
GARMENT_MORPHS = ("ease", "crop")
AVATAR_MATERIAL = {
    "name": "mannequin",
    "pbrMetallicRoughness": {"baseColorFactor": [0.78, 0.78, 0.78, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.85},
}


def morphs(
    build: Callable[[dict], tuple[np.ndarray, np.ndarray]], extra: tuple[str, ...] = ()
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    base, faces = build(ZERO)
    targets = [build({**ZERO, k: 1.0})[0] - base for k in SLIDERS]
    if extra:
        # garment morphs are measured on the middle body, the one seen most
        mid = build(MID)[0]
        targets += [build({**MID, k: 1.0})[0] - mid for k in extra]
    return base, faces, np.stack(targets)


def blend(base: np.ndarray, targets: np.ndarray, weights) -> np.ndarray:
    return base + np.tensordot(np.broadcast_to(np.asarray(weights, float), len(targets)), targets, 1)


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
    names: tuple[str, ...] = SLIDERS,
    extras: dict | None = None,
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
    weights = [0.5 if k in SLIDERS else 0.0 for k in names]
    gltf.update(
        materials=[material],
        meshes=[{"name": name, "primitives": [prim], "weights": weights, "extras": {"targetNames": list(names), **(extras or {})}}],
        nodes=[{"name": name, "mesh": 0}],
        scenes=[{"nodes": [0]}],
        scene=0,
    )
    return write_glb(path, gltf, blob)


def export_avatar(base: str, path: Path) -> Path:
    verts, faces, targets = morphs(lambda s: body_mesh(base, s))
    normals, target_normals = morph_normals(verts, faces, targets)
    return write_morph_glb(path, f"avatar_{base}", verts, normals, targets, target_normals, faces, AVATAR_MATERIAL)
