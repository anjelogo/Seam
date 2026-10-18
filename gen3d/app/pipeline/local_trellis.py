import asyncio
import os
import threading
from pathlib import Path

import trimesh
from PIL import Image

from app.pipeline.bake import template_mesh, texture_or_mock

MODEL = "microsoft/TRELLIS.2-4B"
PIPELINE_TYPE = {512: "512", 1024: "1024_cascade", 1536: "1536_cascade"}
_gpu = threading.Lock()
_pipelines: dict[str, object] = {}


def _pipeline(kind: str):
    if kind not in _pipelines:
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        from trellis2.pipelines import Trellis2ImageTo3DPipeline, Trellis2TexturingPipeline

        if kind == "image":
            pipeline = Trellis2ImageTo3DPipeline.from_pretrained(MODEL)
        else:
            pipeline = Trellis2TexturingPipeline.from_pretrained(MODEL, config_file="texturing_pipeline.json")
        pipeline.cuda()
        _pipelines[kind] = pipeline
    return _pipelines[kind]


def _image_to_3d(image_path: Path, out_path: Path, resolution: int) -> Path:
    import o_voxel

    hi = resolution >= 1024
    with _gpu:
        mesh = _pipeline("image").run(
            Image.open(image_path).convert("RGBA"), pipeline_type=PIPELINE_TYPE.get(resolution, "1024_cascade")
        )[0]
        mesh.simplify(16777216)  # nvdiffrast limit
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=100_000 if hi else 40_000,
            texture_size=2048 if hi else 1024,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
        )
    glb.export(out_path, extension_webp=True)
    return out_path


def _retexture(mesh_path: Path, image_path: Path) -> trimesh.Trimesh:
    verts, faces, _ = template_mesh(mesh_path)
    with _gpu:
        return _pipeline("texturing").run(trimesh.Trimesh(verts, faces), Image.open(image_path).convert("RGBA"))


class LocalTrellisBackend:
    name = "local"

    async def image_to_3d(self, image_path: Path, out_path: Path, resolution: int) -> Path:
        return await asyncio.to_thread(_image_to_3d, image_path, out_path, resolution)

    async def texture_mesh(self, mesh_path: Path, image_path: Path, out_path: Path) -> Path:
        return await texture_or_mock(
            mesh_path, image_path, out_path, lambda: asyncio.to_thread(_retexture, mesh_path, image_path)
        )
