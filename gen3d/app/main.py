import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from seam_shared.models import ApiError
from starlette.exceptions import HTTPException

from app import jobs, settings
from app.routes import health


async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    body = ApiError(error=HTTPStatus(exc.status_code).phrase, detail=str(exc.detail))
    return JSONResponse(body.model_dump(), status_code=exc.status_code, headers=exc.headers)


async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    body = ApiError(error=HTTPStatus(422).phrase, detail=detail)
    return JSONResponse(body.model_dump(), status_code=422)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    jobs.load()
    worker = asyncio.create_task(jobs.worker())
    yield
    worker.cancel()


def create_app() -> FastAPI:
    app = FastAPI(
        title="seam gen3d",
        lifespan=lifespan,
        exception_handlers={HTTPException: http_error, RequestValidationError: validation_error},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o for o in ("http://localhost:5173", os.getenv("VERCEL_ORIGIN")) if o],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (health, jobs):
        app.include_router(module.router)
    # only public folders: DATA_DIR also holds seam.db
    for sub in ("clean", "glb", "thumb"):
        app.mount(f"/static/{sub}", StaticFiles(directory=settings.DATA_DIR / sub, check_dir=False), name=f"static_{sub}")
    return app


app = create_app()
