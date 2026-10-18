import sys

from seam_shared.models import Condition, Listing

from app import db
from app.cv import cutout, tag

# shortcut: sequential, one listing at a time; add a thread pool if seeding a few hundred items is too slow


def main(limit: int) -> None:
    conn = db.connect()
    rows = conn.execute("SELECT id, listing FROM items WHERE tags IS NULL LIMIT ?", (limit,)).fetchall()
    done = 0
    for item_id, raw in rows:
        listing = Listing.model_validate_json(raw)
        result = tag.tag(listing)
        if result is None:
            continue
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
        db.save_tags(conn, item_id, listing, tags)
        conn.commit()
        done += 1
        print(f"{done}/{len(rows)} {item_id} {tags.category.value} usable_for_3d={tags.usable_for_3d}")
    conn.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
