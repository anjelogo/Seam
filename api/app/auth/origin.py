import os

from fastapi import Request
from fastapi.responses import JSONResponse
from seam_shared.models import ApiError

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def allowed() -> set[str]:
    raw = os.getenv("PUBLIC_ORIGINS") or "http://localhost:5273"
    return {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}


async def check_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method in UNSAFE and origin and origin not in allowed():
        return JSONResponse(ApiError(error="Forbidden", detail="origin not allowed.").model_dump(), status_code=403)
    return await call_next(request)
