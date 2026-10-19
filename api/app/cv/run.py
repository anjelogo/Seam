import logging

from seam_shared import db
from seam_shared.models import Condition

from app.cv import cutout, tag

log = logging.getLogger("seam.cv")


def tag_one(item_id: str) -> bool:
    """Tag, cut out and condition-check one item; True when tags were saved. Thread-safe."""
    with db.pool().connection() as conn:
        item = db.get_item(conn, item_id)
    if item is None:
        return False
    listing = item.listing
    result = tag.tag(listing)
    if result is None:
        return False
    tags, views = result
    listing.images = [img.model_copy(update={"view": v}) for img, v in zip(listing.images, views)] + listing.images[len(views) :]
    best = listing.images[tags.best_view_index]
    try:
        tags.clean_image, problem = cutout.cutout(item_id, best.local_path, tags.garment_box, best.view, tags.category)
        if problem and tags.usable_for_3d:
            tags.usable_for_3d, tags.unusable_reason = False, problem
    except Exception:
        log.exception("cutout %s", item_id)
        tags.usable_for_3d, tags.unusable_reason = False, tags.unusable_reason or "cutout_failed"
    if listing.condition == Condition.unknown:
        try:
            listing.condition = tag.condition(best.local_path)
        except Exception:
            log.exception("condition %s", item_id)
    with db.pool().connection() as conn:
        db.save_tags(conn, item_id, listing, tags)
    return True
