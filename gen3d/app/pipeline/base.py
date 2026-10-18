from pathlib import Path
from typing import Protocol


class Backend(Protocol):
    name: str

    async def image_to_3d(self, image_path: Path, out_path: Path, resolution: int) -> Path: ...

    async def texture_mesh(self, mesh_path: Path, image_path: Path, out_path: Path) -> Path: ...
