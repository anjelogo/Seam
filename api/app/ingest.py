import mimetypes
import time

from seam_shared.models import ImageRef, Listing, Slot, Source

from app import db
from app.sources import client, ebay, grailed, poshmark

ADAPTERS = {Source.ebay: ebay.search, Source.poshmark: poshmark.search, Source.grailed: grailed.search}
SEED_SLOTS = [Slot.top, Slot.bottom, Slot.outer, Slot.shoes]


def cache_image(listing: Listing, i: int, img: ImageRef) -> ImageRef:
    folder = db.DATA_DIR / "raw" / listing.source.value
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{listing.source_id}_{i}"
    path = next(folder.glob(f"{stem}.*"), None)
    if path is None:
        time.sleep(0.2)
        r = client.get(img.url)
        r.raise_for_status()
        ext = mimetypes.guess_extension(r.headers.get("content-type", "").split(";")[0]) or ".jpg"
        path = folder / f"{stem}{ext}"
        path.write_bytes(r.content)
    return img.model_copy(update={"url": f"/static/raw/{listing.source.value}/{path.name}", "local_path": str(path)})


def run(queries: list[str], sources: list[Source], limit: int = 12) -> int:
    added = 0
    conn = db.connect()
    try:
        for source in sources:
            for query in queries:
                for slot in SEED_SLOTS:
                    try:
                        listings = ADAPTERS[source](query, slot, limit)
                    except Exception as e:
                        print(f"ingest {source.value} {query!r} {slot.value}: {e!r}")
                        continue
                    for listing in listings:
                        try:
                            images = [cache_image(listing, i, img) for i, img in enumerate(listing.images)]
                        except Exception as e:
                            print(f"ingest images {listing.source_id}: {e!r}")
                            continue
                        added += db.upsert_listing(conn, listing.model_copy(update={"images": images}))
                    conn.commit()
                    time.sleep(1)
    finally:
        conn.close()
    return added
