import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from seam_shared.models import TEMPLATE_FOR_CATEGORY, Asset3D, AssetStatus, AssetTier, Category, GenJob

router = APIRouter()
jobs: dict[str, Asset3D] = {}
_tasks: set[asyncio.Task] = set()


class Prebake(BaseModel):
    item_ids: list[str]
    resolution: int = 1024


class Queued(BaseModel):
    queued: int


async def _fake_generate(asset: Asset3D) -> None:
    # TODO(anjelo): call pipeline.generate here
    await asyncio.sleep(1)
    asset.status = AssetStatus.processing
    await asyncio.sleep(3)
    slug = asset.item_id.replace(":", "_")
    asset.glb_url = f"/static/glb/{slug}.glb"
    asset.thumbnail_url = f"/static/thumb/{slug}.png"
    asset.status = AssetStatus.ready


def submit(job: GenJob) -> Asset3D:
    template_id = TEMPLATE_FOR_CATEGORY.get(job.category)
    # gen3d decides the tier; job.tier is ignored
    tier = AssetTier.template_textured if template_id else AssetTier.generated
    existing = jobs.get(job.item_id)
    if existing and existing.tier == tier:
        return existing
    asset = Asset3D(
        item_id=job.item_id,
        tier=tier,
        template_id=template_id,
        follows_body_morphs=tier == AssetTier.template_textured,
    )
    jobs[job.item_id] = asset
    task = asyncio.create_task(_fake_generate(asset))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
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
