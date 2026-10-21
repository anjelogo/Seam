import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from seam_shared import db

from app.cv import sizes
from app.cv.run import tag_one

# 2 threads overlap Perceptron calls with the (serialized) background removal; more adds memory, not speed
WORKERS = 2
BATCH = 500


def backfill_sizes(conn) -> None:
    """Re-map size_normalized on already tagged garments onto the per-slot ladder; idempotent."""
    ids = [r["id"] for r in conn.execute("SELECT id FROM garments WHERE tags IS NOT NULL ORDER BY created_at")]
    for start in range(0, len(ids), BATCH):
        for garment in db.get_garments_by_id(conn, ids[start : start + BATCH]).values():
            tags = garment.tags
            size = sizes.ladder(tags.slot, tags.size_normalized, garment.best_listing().size_raw)
            if size == tags.size_normalized:
                continue
            tags.size_normalized = size
            db.save_garment_tags(conn, garment.id, tags, garment.pattern_spec, garment.best_photo.id if garment.best_photo else None)


def main(limit: int) -> None:
    with db.pool().connection() as conn:
        backfill_sizes(conn)
        ids = db.untagged_garment_ids(conn, limit)
    done = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(tag_one, garment_id): garment_id for garment_id in ids}
        for future in as_completed(futures):
            garment_id = futures[future]
            try:
                if not future.result():
                    continue
            except Exception as e:
                print(f"tag {garment_id}: {e!r}")
                continue
            done += 1
            print(f"{done}/{len(ids)} {garment_id}", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
