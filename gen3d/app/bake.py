import argparse
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from seam_shared.models import AssetStatus, Category, GenJob

from app import jobs, settings, store
from app.pipeline import BACKENDS

MAX_JOBS = 10
SHOES = [c.value for c in (Category.sneakers, Category.boots, Category.shoes_other)]


def _photo(arg: str) -> tuple[str, Path]:
    garment_id, _, path = arg.partition("=")
    photo = Path(path).expanduser()
    if not (jobs.SAFE_ID.fullmatch(garment_id.replace(":", "_")) and photo.is_file()):
        raise argparse.ArgumentTypeError(f"expected GARMENT_ID=PATH to an existing file, got {arg!r}")
    return garment_id, photo


def _ready() -> list[str]:
    # ready assets baked before the current templates, plus usable shoes not baked since
    built = max((p.stat().st_mtime for p in jobs.TEMPLATES_DIR.glob("*.glb")), default=0.0)
    cutoff = datetime.fromtimestamp(built, timezone.utc)
    stamps = store.stamped()
    ready = [i for i, (asset, at) in stamps.items() if asset.status == AssetStatus.ready and at < cutoff]
    return ready + [i for i in store.usable(SHOES) if i not in stamps or stamps[i][1] < cutoff]


async def _bake(todo: list[GenJob]) -> int:
    failed = 0
    for job in todo:
        asset = await jobs.bake(job)
        failed += asset.status == AssetStatus.failed
        print(f"{asset.item_id}: {asset.status.value} in {asset.gen_seconds or 0:.1f}s {asset.error or asset.glb_url}")
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Bake garment GLBs into DATA_DIR/glb, at most {MAX_JOBS} a run.")
    parser.add_argument("garment_ids", nargs="*", metavar="garment_id")
    parser.add_argument("--fixtures", action="store_true", help="every item in shared/schema/fixtures")
    parser.add_argument("--image", action="append", type=_photo, default=[], metavar="GARMENT_ID=PATH")
    parser.add_argument("--backend", choices=BACKENDS, default=settings.GEN3D_BACKEND)
    parser.add_argument(
        "--ready", action="store_true", help="ready assets older than the templates, plus usable shoes; rerun until none left"
    )
    args = parser.parse_args()
    photos = dict(args.image)
    ready = _ready() if args.ready else []
    ids = dict.fromkeys([*args.garment_ids, *(jobs.fixture_items() if args.fixtures else ()), *photos, *ready])
    if not ids and not args.ready:
        parser.error("give garment ids, --fixtures, --image or --ready")
    jobs.GLB_DIR.mkdir(parents=True, exist_ok=True)
    jobs.CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    todo = []
    for garment_id in ids:
        if job := jobs.job_for(garment_id):
            todo.append(job)
        else:
            print(f"skip {garment_id}: no such garment, untagged or not usable_for_3d")
    if args.ready and not todo:
        print("nothing to rebake")
    elif args.ready and len(todo) > MAX_JOBS:
        print(f"{len(todo) - MAX_JOBS} left after this run, run --ready again")
        todo = todo[:MAX_JOBS]
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
