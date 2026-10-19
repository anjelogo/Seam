import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from seam_shared.models import Condition, ItemTags, Listing

from app import db
from app.cv import cutout, sizes, tag

# 2 threads overlap Perceptron calls with the (serialized) background removal; more adds memory, not speed
WORKERS = 2


def backfill_sizes(conn) -> None:
    """Re-map size_normalized on already tagged items onto the per-slot ladder; idempotent."""
    for item_id, raw_listing, raw_tags in conn.execute("SELECT id, listing, tags FROM items WHERE tags IS NOT NULL").fetchall():
        listing, tags = Listing.model_validate_json(raw_listing), ItemTags.model_validate_json(raw_tags)
        size = sizes.ladder(tags.slot, tags.size_normalized, listing.size_raw)
        if size != tags.size_normalized:
            tags.size_normalized = size
            db.save_tags(conn, item_id, listing, tags)
    conn.commit()


def process(item_id: str, raw: str) -> Optional[tuple[Listing, ItemTags]]:
    """Tag, cut out and condition-check one listing; no DB access so it can run in a worker thread."""
    listing = Listing.model_validate_json(raw)
    result = tag.tag(listing)
    if result is None:
        return None
    tags, views = result
    listing.images = [img.model_copy(update={"view": v}) for img, v in zip(listing.images, views)] + listing.images[len(views) :]
    best = listing.images[tags.best_view_index]
    try:
        tags.clean_image, problem = cutout.cutout(item_id, best.local_path, tags.garment_box, best.view, tags.category)
        if problem and tags.usable_for_3d:
            tags.usable_for_3d, tags.unusable_reason = False, problem
    except Exception as e:
        print(f"cutout {item_id}: {e!r}")
        tags.usable_for_3d, tags.unusable_reason = False, tags.unusable_reason or "cutout_failed"
    if listing.condition == Condition.unknown:
        try:
            listing.condition = tag.condition(best.local_path)
        except Exception as e:
            print(f"condition {item_id}: {e!r}")
    return listing, tags


def main(limit: int) -> None:
    conn = db.connect()
    backfill_sizes(conn)
    rows = conn.execute("SELECT id, listing FROM items WHERE tags IS NULL ORDER BY random() LIMIT ?", (limit,)).fetchall()
    done = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(process, item_id, raw): item_id for item_id, raw in rows}
        for future in as_completed(futures):
            item_id = futures[future]
            try:
                out = future.result()
            except Exception as e:
                print(f"tag {item_id}: {e!r}")
                continue
            if out is None:
                continue
            listing, tags = out
            db.save_tags(conn, item_id, listing, tags)
            conn.commit()
            done += 1
            print(f"{done}/{len(rows)} {item_id} {tags.category.value} usable_for_3d={tags.usable_for_3d}", flush=True)
    conn.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
