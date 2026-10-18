from functools import cache

from app import settings
from app.pipeline.base import Backend

BACKENDS = ("mock", "fal", "local")


@cache
def get_backend() -> Backend:
    name = settings.GEN3D_BACKEND
    if name == "mock":
        from app.pipeline.mock import MockBackend

        return MockBackend()
    if name == "fal":
        from app.pipeline.fal import FalBackend

        return FalBackend()
    if name == "local":
        from app.pipeline.local_trellis import LocalTrellisBackend

        return LocalTrellisBackend()
    raise ValueError(f"GEN3D_BACKEND={name!r}, expected one of: {', '.join(BACKENDS)}")
