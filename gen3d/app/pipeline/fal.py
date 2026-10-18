import logging
import tempfile
from pathlib import Path

import fal_client
import httpx
import trimesh

from app import settings
from app.pipeline.bake import template_mesh, texture_or_mock

log = logging.getLogger(__name__)
IMAGE_TO_3D = "fal-ai/trellis-2"
RETEXTURE = "fal-ai/trellis-2/retexture"
TIMEOUT_S = 600


class FalBackend:
    name = "fal"

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise RuntimeError("GEN3D_BACKEND=fal needs FAL_KEY in the repo-root .env")
        self.client = fal_client.AsyncClient(key=settings.FAL_KEY)

    async def _run(self, endpoint: str, arguments: dict, out_path: Path) -> Path:
        result = await self.client.subscribe(
            endpoint,
            arguments,
            client_timeout=TIMEOUT_S,
            on_enqueue=lambda request_id: log.info("%s request %s", endpoint, request_id),
        )
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
            response = await http.get(result["model_glb"]["url"])
            response.raise_for_status()
        out_path.write_bytes(response.content)
        return out_path

    async def image_to_3d(self, image_path: Path, out_path: Path, resolution: int) -> Path:
        hi = resolution >= 1024
        arguments = {
            "image_url": await self.client.upload_file(image_path),
            "resolution": 1024 if hi else 512,
            "texture_size": 2048 if hi else 1024,
            "decimation_target": 100_000 if hi else 40_000,
        }
        return await self._run(IMAGE_TO_3D, arguments, out_path)

    async def texture_mesh(self, mesh_path: Path, image_path: Path, out_path: Path) -> Path:
        async def retexture() -> trimesh.Trimesh:
            with tempfile.TemporaryDirectory() as tmp:
                upload = Path(tmp) / "template.glb"
                verts, faces, _ = template_mesh(mesh_path)
                trimesh.Trimesh(verts, faces).export(upload)
                arguments = {
                    "image_url": await self.client.upload_file(image_path),
                    "mesh_url": await self.client.upload_file(upload),
                }
                return trimesh.load_mesh(await self._run(RETEXTURE, arguments, Path(tmp) / "textured.glb"))

        return await texture_or_mock(mesh_path, image_path, out_path, retexture)
