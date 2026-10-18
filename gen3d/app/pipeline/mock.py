import asyncio
from pathlib import Path

import trimesh

from app.pipeline.bake import cutout, mock_texture


def _box(image_path: Path, out_path: Path) -> Path:
    px, color = cutout(image_path)
    h, w = px.shape[:2]
    box = trimesh.creation.box(extents=(w / max(w, h), h / max(w, h), 0.08))
    # glTF color factors are linear, the cutout is sRGB
    linear = ((color / 255 + 0.055) / 1.055) ** 2.4
    material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=[*linear, 1.0], metallicFactor=0.0, roughnessFactor=0.9
    )
    box.visual = trimesh.visual.TextureVisuals(material=material)
    box.export(out_path, file_type="glb")
    return out_path


class MockBackend:
    name = "mock"

    async def image_to_3d(self, image_path: Path, out_path: Path, resolution: int) -> Path:
        return await asyncio.to_thread(_box, image_path, out_path)

    async def texture_mesh(self, mesh_path: Path, image_path: Path, out_path: Path) -> Path:
        return await asyncio.to_thread(mock_texture, mesh_path, image_path, out_path)
