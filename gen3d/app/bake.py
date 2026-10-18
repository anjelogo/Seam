import argparse
import asyncio
import logging
from pathlib import Path

from seam_shared.models import AssetStatus, GenJob

from app import jobs, settings
from app.pipeline import BACKENDS

MAX_JOBS = 10


def _photo(arg: str) -> tuple[str, Path]:
    item_id, _, path = arg.partition("=")
    photo = Path(path).expanduser()
    if not (jobs.SAFE_ID.fullmatch(item_id.replace(":", "_")) and photo.is_file()):
        raise argparse.ArgumentTypeError(f"expected ITEM_ID=PATH to an existing file, got {arg!r}")
    return item_id, photo


async def _bake(todo: list[GenJob]) -> int:
    failed = 0
    for job in todo:
        asset = await jobs.bake(job)
        failed += asset.status == AssetStatus.failed
        print(f"{asset.item_id}: {asset.status.value} in {asset.gen_seconds or 0:.1f}s {asset.error or asset.glb_url}")
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Bake item GLBs into DATA_DIR/glb, at most {MAX_JOBS} a run.")
    parser.add_argument("item_ids", nargs="*", metavar="item_id")
    parser.add_argument("--fixtures", action="store_true", help="every item in shared/schema/fixtures")
    parser.add_argument("--image", action="append", type=_photo, default=[], metavar="ITEM_ID=PATH")
    parser.add_argument("--backend", choices=BACKENDS, default=settings.GEN3D_BACKEND)
    args = parser.parse_args()
    photos = dict(args.image)
    ids = dict.fromkeys([*args.item_ids, *(jobs.fixture_items() if args.fixtures else ()), *photos])
    if not ids:
        parser.error("give item ids, --fixtures or --image")
    jobs.GLB_DIR.mkdir(parents=True, exist_ok=True)
    jobs.CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    todo = []
    for item_id in ids:
        if job := jobs.job_for(item_id):
            todo.append(job)
        else:
            print(f"skip {item_id}: not found, untagged or not usable_for_3d")
    if len(todo) > MAX_JOBS:
        parser.error(f"{len(todo)} jobs, at most {MAX_JOBS} a run")
    for job in todo:
        if photo := photos.get(job.item_id):
            safe_id = job.item_id.replace(":", "_")
            jobs._save_png(photo.read_bytes(), jobs.CLEAN_DIR / f"{safe_id}.png")
            job.image_url = f"/static/clean/{safe_id}.png"
    # get_backend() reads this on its first call
    settings.GEN3D_BACKEND = args.backend
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(_bake(todo)) > 0)


if __name__ == "__main__":
    main()
