import asyncio
import logging
import mimetypes
import os

from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from seam_shared import db
from seam_shared.models import ImageRef, Listing, Slot, Source

from app.settings import DATA_DIR
from app.sources import ADAPTERS
from app.sources.fetch import BlockedError, fetch_bytes
from app.worker import app

log = logging.getLogger("seam.worker")

SEED_SLOTS = [Slot.top, Slot.bottom, Slot.outer, Slot.shoes]
LIMIT = 12
# downloads dominate ingest time; 4 photos is enough to pick a best view
MAX_PHOTOS = 4
# blocked, config (missing keys) and HTTP 4xx errors won't change on a retry
NO_RETRY = (BlockedError, RuntimeError)


async def cache_image(listing: Listing, i: int, img: ImageRef) -> ImageRef:
    folder = DATA_DIR / "raw" / listing.source.value
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{listing.source_id}_{i}"
    path = next(folder.glob(f"{stem}.*"), None)
    if path is None:
        content, ctype = await fetch_bytes(img.url, source=listing.source)
        ext = mimetypes.guess_extension(ctype.split(";")[0].strip()) or ".jpg"
        path = folder / f"{stem}{ext}"
        path.write_bytes(content)
    return img.model_copy(update={"url": f"/static/raw/{listing.source.value}/{path.name}", "local_path": str(path)})


@app.task(queue="scrape", retry=RetryStrategy(max_attempts=2, exponential_wait=10))
async def scrape(source: str, query: str, slot: str, page: int = 0):
    src = Source(source)
    with db.pool().connection() as conn:
        run_id = db.start_run(conn, src.value, query, slot)
    fetched = added = updated = errors = 0
    last_error = None
    try:
        listings = await ADAPTERS[src](query, Slot(slot), LIMIT, page)
        fetched = len(listings)
        for listing in listings:
            try:
                images = await asyncio.gather(*(cache_image(listing, i, img) for i, img in enumerate(listing.images[:MAX_PHOTOS])))
            except BlockedError:
                raise
            except Exception as e:
                errors += 1
                last_error = f"images {listing.source_id}: {e!r}"
                log.warning("%s %s", source, last_error)
                continue
            async with db.apool().connection() as conn:
                result = await db.aupsert_listing(conn, listing.model_copy(update={"images": images}))
            if result == "added":
                added += 1
                await tag.defer_async(item_id=f"{src.value}:{listing.source_id}")
            else:
                updated += 1
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


@app.task(queue="cv")
async def tag(item_id: str):
    from app.cv.run import tag_one  # keeps cv deps out of the scrape worker

    if not await asyncio.to_thread(tag_one, item_id):
        log.warning("tag %s: not tagged", item_id)


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
