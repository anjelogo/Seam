import asyncio
import logging
import mimetypes
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from seam_shared import db
from seam_shared.models import ImageRef, Listing, ListingStatus, Slot, Source

from app import dedup
from app.dedup import PhotoMeta
from app.settings import DATA_DIR
from app.sources import ADAPTERS
from app.sources.fetch import BlockedError, fetch_bytes
from app.worker import app

log = logging.getLogger("seam.worker")

SEED_SLOTS = [Slot.top, Slot.bottom, Slot.outer, Slot.shoes]
LIMIT = 12
# depop can't page, so keep everything its two gender variants return (2 x 24)
LIMITS = {Source.depop: 48}
# downloads dominate ingest time; 4 photos is enough to pick a best view
MAX_PHOTOS = 4
# blocked, config (missing keys) and HTTP 4xx errors won't change on a retry
NO_RETRY = (BlockedError, RuntimeError)


async def cache_image(listing: Listing, i: int, img: ImageRef, hashed: set[int]) -> tuple[ImageRef, PhotoMeta | None]:
    folder = DATA_DIR / "raw" / listing.source.value
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{listing.source_id}_{i}"
    path = next((p for p in folder.glob(f"{stem}.*") if p.suffix != ".tmp"), None)
    if path is None:
        content, ctype = await fetch_bytes(img.url, source=listing.source)
        ext = mimetypes.guess_extension(ctype.split(";")[0].strip()) or ".jpg"
        path = folder / f"{stem}{ext}"
        meta = await asyncio.to_thread(dedup.store_photo, path, content)
    elif i not in hashed:
        meta = await asyncio.to_thread(dedup.store_photo, path)
    else:
        meta = None
    url = f"/static/{meta.path}" if meta else f"/static/raw/{listing.source.value}/{path.name}"
    update = {"url": url, "local_path": str(path)}
    if meta:
        update |= {"width": meta.width, "height": meta.height}
    return img.model_copy(update=update), meta


def _hashed(listing_id: str) -> set[int]:
    with db.pool().connection() as conn:
        return db.photo_idxs(conn, listing_id)


def _save_listing(listing: Listing, listing_id: str, slot: Slot, cached: list[tuple[ImageRef, PhotoMeta | None]]):
    with db.pool().connection() as conn:
        result = db.upsert_listing(conn, listing.model_copy(update={"images": [ref for ref, _ in cached]}))
        for i, (_, meta) in enumerate(cached):
            if meta:
                db.upsert_photo(
                    conn, listing_id, i, path=meta.path, width=meta.width, height=meta.height, phash=meta.phash,
                    exif_rotated=meta.exif_rotated,
                )
        garment_id = None if db.garment_for_listing(conn, listing_id) else dedup.link(conn, listing_id, slot)
    return result, garment_id


@app.task(queue="scrape", retry=RetryStrategy(max_attempts=2, exponential_wait=10))
async def scrape(source: str, query: str, slot: str, page: int = 0):
    src = Source(source)
    with db.pool().connection() as conn:
        run_id = db.start_run(conn, src.value, query, slot)
    fetched = added = updated = errors = 0
    last_error = None
    try:
        listings = await ADAPTERS[src](query, Slot(slot), LIMITS.get(src, LIMIT), page)
        fetched = len(listings)
        for listing in listings:
            listing_id = f"{src.value}:{listing.source_id}"
            try:
                hashed = await asyncio.to_thread(_hashed, listing_id)
                cached = await asyncio.gather(
                    *(cache_image(listing, i, img, hashed) for i, img in enumerate(listing.images[:MAX_PHOTOS]))
                )
            except BlockedError:
                raise
            except Exception as e:
                errors += 1
                last_error = f"images {listing.source_id}: {e!r}"
                log.warning("%s %s", source, last_error)
                continue
            result, garment_id = await asyncio.to_thread(_save_listing, listing, listing_id, Slot(slot), list(cached))
            if result == "added":
                added += 1
            else:
                updated += 1
            if garment_id:
                try:
                    await tag.configure(queueing_lock=garment_id).defer_async(garment_id=garment_id)
                except AlreadyEnqueued:
                    pass
    except Exception as e:
        errors += 1
        last_error = repr(e)
        log.warning("scrape %s %r %s p%d: %r", source, query, slot, page, e)
        if not isinstance(e, NO_RETRY):
            raise
    finally:
        with db.pool().connection() as conn:
            db.finish_run(conn, run_id, fetched=fetched, added=added, updated=updated, errors=errors, last_error=last_error)
        log.info("scrape %s %r %s p%d: fetched=%d added=%d updated=%d errors=%d", source, query, slot, page, fetched, added, updated, errors)


_cv_pool: ProcessPoolExecutor | None = None


def _tag_one(garment_id: str, retag: bool) -> bool:
    from app.cv.run import tag_one  # keeps cv deps out of the scrape worker

    return tag_one(garment_id, retag)


def _resolve_garment(item_id: str) -> str | None:
    with db.pool().connection() as conn:
        garment_id = db.garment_for_listing(conn, item_id)
        if garment_id is None and conn.execute("SELECT 1 FROM listings WHERE id = %s", (item_id,)).fetchone():
            garment_id = dedup.link(conn, item_id)
        return garment_id


@app.task(queue="cv")
async def tag(garment_id: str | None = None, item_id: str | None = None, retag: bool = False):
    global _cv_pool
    if garment_id is None and item_id:
        garment_id = await asyncio.to_thread(_resolve_garment, item_id)
    if garment_id is None:
        log.info("tag %s: skipped, no garment", item_id)
        return
    with db.pool().connection() as conn:
        garment = db.get_garment(conn, garment_id)
    if garment is None or not any(offer.status == ListingStatus.active for offer in garment.listings):
        log.info("tag %s: skipped, no longer active", garment_id)
        return
    if _cv_pool is None:
        # one fresh process per job: onnxruntime holds a job's ~11 GB peak until its process exits
        _cv_pool = ProcessPoolExecutor(
            int(os.getenv("CV_CONCURRENCY") or 1), mp_context=multiprocessing.get_context("spawn"), max_tasks_per_child=1
        )
    try:
        ok = await asyncio.get_running_loop().run_in_executor(_cv_pool, _tag_one, garment_id, retag)
    except BrokenProcessPool:
        _cv_pool = None  # a child died (OOM): this job fails, the next one gets a new pool
        raise
    if not ok:
        log.warning("tag %s: not tagged", garment_id)


@app.periodic(cron=os.getenv("SCRAPE_CRON") or "0 9 * * *")
@app.task(queue="default")
async def scrape_all(timestamp: int = 0):
    queries = [q.strip() for q in (os.getenv("SCRAPE_QUERIES") or "vintage").split(",") if q.strip()]
    pages = int(os.getenv("SCRAPE_PAGES") or 1)
    deferred = 0
    # source innermost: jobs run in queue order, so this keeps every source busy at once
    for query in queries:
        for slot in SEED_SLOTS:
            for page in range(pages):
                for source in ADAPTERS:
                    lock = f"{source.value}:{query}:{slot.value}:{page}"
                    try:
                        await scrape.configure(queueing_lock=lock).defer_async(source=source.value, query=query, slot=slot.value, page=page)
                        deferred += 1
                    except AlreadyEnqueued:
                        pass
    log.info("scrape_all: deferred %d scrape jobs", deferred)


@app.periodic(cron="0 * * * *")
@app.task(queue="default")
async def expire_stale(timestamp: int = 0):
    hours = float(os.getenv("STALE_HOURS") or 72)
    with db.pool().connection() as conn:
        n = db.expire_stale(conn, hours)
    log.info("expire_stale: %d items gone", n)
