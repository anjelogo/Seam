import logging
from typing import Optional

from seam_shared import db
from seam_shared.models import (
    Condition,
    Garment,
    ImageView,
    ItemTags,
    ListingOffer,
    ListingStatus,
    PatternSpec,
    Photo,
    PhotoState,
    Placement,
    Wrinkle,
)

from app.cv import cutout, tag

log = logging.getLogger("seam.cv")
VIEW_RANK = {ImageView.flat_lay: 4, ImageView.hanger: 3, ImageView.mannequin: 2, ImageView.on_model: 1, ImageView.detail: 0, ImageView.unknown: 0}
WRINKLE_RANK = {Wrinkle.low: 2, Wrinkle.medium: 1, Wrinkle.unknown: 1, Wrinkle.high: 0}


def rank(photo: Photo) -> tuple[int, bool, int]:
    return VIEW_RANK[photo.view], photo.state == PhotoState.spread, WRINKLE_RANK[photo.wrinkle]


def _photo_set(listings: list[ListingOffer], unknown_only: bool = False) -> list[Photo]:
    """Round-robin over the listings so a capped set still covers several stores."""
    picked = []
    for idx in range(max((len(o.photos) for o in listings), default=0)):
        for offer in listings:
            photo = offer.photos[idx] if idx < len(offer.photos) else None
            if photo and (not unknown_only or photo.state == PhotoState.unknown):
                picked.append(photo)
                if len(picked) == tag.MAX_IMAGES:
                    return picked
    return picked


def _conditions(listings: list[ListingOffer]) -> dict[str, Condition]:
    """Our own read of each listing's best photo."""
    out = {}
    for offer in listings:
        best = max(offer.photos, key=rank, default=None)
        if best is None:
            continue
        try:
            out[offer.id] = tag.condition(str(tag.photo_file(best)))
        except Exception:
            log.exception("condition %s", offer.id)
    return out


def _spec(pattern: Optional[tag.PatternOut], boxes: list[tuple[float, float, float, float]]) -> Optional[PatternSpec]:
    if pattern is None:
        return None
    placements = [Placement(kind=p.kind, box=box, panel=p.panel) for p, box in zip(pattern.placements, boxes)]
    return PatternSpec(**pattern.model_dump(exclude={"placements"}), placements=placements)


def _cut(garment: Garment, tags: ItemTags, photo: Photo, out: tag.PhotoOut, boxes) -> cutout.Cut:
    return cutout.cutout(garment.id, str(tag.photo_file(photo)), tags.garment_box, out.view, tags.category, tags.slot,
                         rotation=out.rotation, state=out.state, boxes=boxes)


def _full(garment: Garment, result: tag.Tagged, photos: list[Photo]) -> tuple[ItemTags, Optional[PatternSpec], int]:
    tags, photo = result.tags, photos[result.best]
    tags.best_view_index = photo.idx
    boxes = [tag.unit_box(p.box) for p in result.pattern.placements] if result.pattern else []
    try:
        cut = _cut(garment, tags, photo, result.photos[result.best], boxes)
        tags.clean_image = cut.ref
        if cut.problem and tags.usable_for_3d:
            tags.usable_for_3d, tags.unusable_reason = False, cut.problem
        boxes = cut.boxes
    except Exception:
        log.exception("cutout %s", garment.id)
        tags.usable_for_3d, tags.unusable_reason = False, tags.unusable_reason or "cutout_failed"
        boxes = []
    return tags, _spec(result.pattern, boxes), photo.id


def _join(garment: Garment, result: Optional[tag.Tagged], photos: list[Photo]) -> tuple[Optional[ItemTags], Optional[PatternSpec], Optional[int]]:
    """Only the 3D source can change on a garment that is already tagged."""
    tags = garment.tags
    if result is None or not tag.qualifies(result.photos[result.best]):
        return None, None, None
    photo = photos[result.best]
    if tags.usable_for_3d and garment.best_photo and rank(photo) <= rank(garment.best_photo):
        return None, None, None
    log.info("recut %s on photo %s", garment.id, photo.id)
    tags.garment_box = result.tags.garment_box
    try:
        cut = _cut(garment, tags, photo, result.photos[result.best], [])
    except Exception:
        log.exception("cutout %s", garment.id)
        return None, None, None
    tags.clean_image, tags.best_view_index = cut.ref, photo.idx
    tags.usable_for_3d, tags.unusable_reason = result.tags.usable_for_3d, result.tags.unusable_reason
    if cut.problem and tags.usable_for_3d:
        tags.usable_for_3d, tags.unusable_reason = False, cut.problem
    # placement boxes point into the old cutout
    spec = garment.pattern_spec.model_copy(update={"placements": []}) if garment.pattern_spec else None
    return tags, spec, photo.id


def tag_one(garment_id: str, retag: bool = False) -> bool:
    """Tag, cut out and condition-check one garment; True when it was processed. Thread-safe."""
    with db.pool().connection() as conn:
        garment = db.get_garment(conn, garment_id)
    if garment is None:
        return False
    active = [o for o in garment.listings if o.status == ListingStatus.active]
    if not active:
        return False
    full = garment.tags is None or retag
    photos = _photo_set(active, unknown_only=not full)
    result = tag.tag(garment, photos) if photos else None
    if full and result is None:
        return False
    for photo, out in zip(photos, result.photos if result else []):
        photo.view, photo.rotation, photo.state, photo.wrinkle = out.view, out.rotation, out.state, out.wrinkle
    conditions = _conditions(active if full else [o for o in active if o.assessed_condition == Condition.unknown])
    tags, spec, best_photo_id = _full(garment, result, photos) if full else _join(garment, result, photos)
    with db.pool().connection() as conn:
        for photo in photos if result else []:
            db.save_photo_tags(conn, photo.id, view=photo.view, rotation=photo.rotation, state=photo.state, wrinkle=photo.wrinkle)
        if tags is not None:
            db.save_garment_tags(conn, garment.id, tags, spec, best_photo_id)
        for listing_id, condition in conditions.items():
            db.save_assessed_condition(conn, listing_id, condition)
    return True
