import os
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from seam_shared.models import ApiError
from starlette.exceptions import HTTPException

from app.routes import health, items, outfits


async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    body = ApiError(error=HTTPStatus(exc.status_code).phrase, detail=str(exc.detail))
    return JSONResponse(body.model_dump(), status_code=exc.status_code, headers=exc.headers)


async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    body = ApiError(error=HTTPStatus(422).phrase, detail=detail)
    return JSONResponse(body.model_dump(), status_code=422)


def create_app() -> FastAPI:
    app = FastAPI(
        title="seam api",
        exception_handlers={HTTPException: http_error, RequestValidationError: validation_error},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o for o in ("http://localhost:5173", os.getenv("VERCEL_ORIGIN")) if o],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (health, outfits, items):
        app.include_router(module.router)
    app.mount("/static", StaticFiles(directory=os.getenv("DATA_DIR", "../data")), name="static")
    return app


app = create_app()
