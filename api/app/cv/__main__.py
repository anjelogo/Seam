import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from seam_shared import db

from app.cv import sizes
from app.cv.run import tag_one

# 2 threads overlap Perceptron calls with the (serialized) background removal; more adds memory, not speed
WORKERS = 2


def backfill_sizes(conn) -> None:
    """Re-map size_normalized on already tagged items onto the per-slot ladder; idempotent."""
    items, _ = db.get_items(conn, status=None, limit=None)
    for item in items:
        if item.tags is None:
            continue
        size = sizes.ladder(item.tags.slot, item.tags.size_normalized, item.listing.size_raw)
        if size != item.tags.size_normalized:
            item.tags.size_normalized = size
            db.save_tags(conn, item.id, item.listing, item.tags)


def main(limit: int) -> None:
    with db.pool().connection() as conn:
        backfill_sizes(conn)
        ids = db.untagged_ids(conn, limit)
    done = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(tag_one, item_id): item_id for item_id in ids}
        for future in as_completed(futures):
            item_id = futures[future]
            try:
                if not future.result():
                    continue
            except Exception as e:
                print(f"tag {item_id}: {e!r}")
                continue
            done += 1
            print(f"{done}/{len(ids)} {item_id}", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
