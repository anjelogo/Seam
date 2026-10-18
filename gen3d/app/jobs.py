import asyncio
import io
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException
from PIL import Image
from pydantic import BaseModel
from seam_shared.models import TEMPLATE_FOR_CATEGORY, Asset3D, AssetStatus, AssetTier, BodyBase, Category, GenJob, Slot

from app import settings, store
from app.fit.fit import fit_mesh
from app.pipeline import get_backend
from app.voxel import voxelize

log = logging.getLogger(__name__)
router = APIRouter()
jobs: dict[str, Asset3D] = {}
queue: asyncio.Queue[tuple[Asset3D, GenJob]] = asyncio.Queue()

GLB_DIR = settings.DATA_DIR / "glb"
CLEAN_DIR = settings.DATA_DIR / "clean"
TEMPLATES_DIR = settings.ASSETS_DIR / "templates"
SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")
DOWNLOAD_TIMEOUT_S = 30
SLOT_FOR_CATEGORY = {
    Category(name): slot
    for slot, names in (
        (Slot.top, "tee longsleeve tank button_up polo sweater hoodie sweatshirt"),
        (Slot.outer, "jacket denim_jacket leather_jacket coat vest"),
        (Slot.bottom, "jeans pants cargo shorts skirt"),
        (Slot.onepiece, "dress jumpsuit"),
        (Slot.shoes, "sneakers boots shoes_other"),
    )
    for name in names.split()
}


class Prebake(BaseModel):
    item_ids: list[str]
    resolution: int = 1024


class Queued(BaseModel):
    queued: int


def _tier(category: Category) -> tuple[AssetTier, str | None]:
    template_id = TEMPLATE_FOR_CATEGORY.get(category)
    if template_id and (TEMPLATES_DIR / f"{template_id}_masc.glb").is_file():
        return AssetTier.template_textured, template_id
    return AssetTier.generated, None


def _url(path: Path) -> str:
    return f"/static/glb/{path.name}"


def _save_png(data: bytes, path: Path) -> None:
    with Image.open(io.BytesIO(data)) as image:
        image.convert("RGBA").save(path, "PNG")


async def _image(url: str, safe_id: str) -> Path:
    if url.startswith("/static/"):
        path = (settings.DATA_DIR / url.removeprefix("/static/")).resolve()
        if not (path.is_relative_to(settings.DATA_DIR) and path.is_file()):
            raise ValueError(f"image_url {url!r} is not a file under /static")
        return path
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"image_url {url!r} must be an http(s) URL or a /static/... path")
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    path = CLEAN_DIR / f"{safe_id}.png"
    await asyncio.to_thread(_save_png, response.content, path)
    return path


async def _generate(asset: Asset3D, job: GenJob) -> None:
    safe_id = asset.item_id.replace(":", "_")
    image = await _image(job.image_url, safe_id)
    backend = get_backend()
    glb = GLB_DIR / f"{safe_id}.glb"
    if asset.tier == AssetTier.template_textured:
        await asyncio.gather(
            backend.texture_mesh(TEMPLATES_DIR / f"{asset.template_id}_masc.glb", image, glb),
            backend.texture_mesh(TEMPLATES_DIR / f"{asset.template_id}_fem.glb", image, GLB_DIR / f"{safe_id}_fem.glb"),
        )
        # TODO(anjelo): per-base glb urls
        asset.glb_url = _url(glb)
    else:
        voxel = GLB_DIR / f"{safe_id}_voxel.glb"
        await backend.image_to_3d(image, glb, job.resolution)
        slot = SLOT_FOR_CATEGORY.get(job.category, Slot.accessory)
        fit = await asyncio.to_thread(fit_mesh, glb, slot, BodyBase.masc)
        await asyncio.to_thread(voxelize, glb, voxel)
        asset.fit, asset.glb_url, asset.voxel_glb_url = fit, _url(glb), _url(voxel)


async def _run(asset: Asset3D, job: GenJob) -> None:
    start = time.monotonic()
    asset.status = AssetStatus.processing
    store.upsert(asset)
    try:
        await _generate(asset, job)
        asset.status = AssetStatus.ready
    except Exception as e:
        log.exception("job %s failed", asset.item_id)
        asset.status, asset.error = AssetStatus.failed, str(e) or type(e).__name__
    asset.gen_seconds = time.monotonic() - start
    store.upsert(asset)


async def worker() -> None:
    while True:
        asset, job = await queue.get()
        # skip assets replaced by a re-submit with another tier while queued
        if jobs.get(asset.item_id) is asset:
            await _run(asset, job)


def load() -> None:
    GLB_DIR.mkdir(parents=True, exist_ok=True)
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    for asset in store.load():
        if asset.status in (AssetStatus.queued, AssetStatus.processing):
            asset.status, asset.error = AssetStatus.failed, "interrupted by restart"
            store.upsert(asset)
        jobs[asset.item_id] = asset


def submit(job: GenJob) -> Asset3D:
    # gen3d decides the tier; job.tier is ignored
    tier, template_id = _tier(job.category)
    existing = jobs.get(job.item_id)
    if existing and existing.tier == tier and existing.status != AssetStatus.failed:
        return existing
    asset = Asset3D(
        item_id=job.item_id,
        tier=tier,
        template_id=template_id,
        follows_body_morphs=tier == AssetTier.template_textured,
    )
    if not SAFE_ID.fullmatch(job.item_id.replace(":", "_")):
        asset.status = AssetStatus.failed
        asset.error = f"item_id {job.item_id!r} may only contain letters, digits, ':', '.', '_' and '-'"
    jobs[job.item_id] = asset
    store.upsert(asset)
    if asset.status == AssetStatus.queued:
        queue.put_nowait((asset, job))
    return asset


@router.post("/gen3d/jobs", response_model=Asset3D)
async def post_job(job: GenJob) -> Asset3D:
    return submit(job)


@router.get("/gen3d/jobs/{item_id}", response_model=Asset3D)
async def get_job(item_id: str) -> Asset3D:
    if item_id not in jobs:
        raise HTTPException(404, f"no job for {item_id}")
    return jobs[item_id]


@router.post("/gen3d/prebake", response_model=Queued)
async def prebake(req: Prebake) -> Queued:
    todo = set(req.item_ids) - jobs.keys()
    for item_id in todo:
        # TODO(anjelo): look up real category and image
        submit(GenJob(item_id=item_id, image_url="", category=Category.unknown, resolution=req.resolution))
    return Queued(queued=len(todo))
