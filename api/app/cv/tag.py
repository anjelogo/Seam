import base64
import io
import json
import os
from pathlib import Path
from typing import Literal, NamedTuple, Optional

from PIL import Image, ImageOps
from perceptron import Client, image, json_schema_format
from pydantic import BaseModel, Field
from seam_shared.models import (
    Category,
    Color,
    Condition,
    Fit,
    Garment,
    ImageView,
    ItemTags,
    ListingStatus,
    Money,
    PatternKind,
    Photo,
    PhotoState,
    Slot,
    StripeSet,
    Trim,
    Wrinkle,
)

from app.cv import sizes
from app.settings import DATA_DIR
from app.sources.fetch import api_client as http

MAX_IMAGES = 8
GEMINI_MODEL = "gemini-3.8-flash"
# providers reject the keywords pydantic emits for gt/le bounds
DROP = ("exclusiveMinimum", "exclusiveMaximum", "prefixItems")


class PhotoOut(BaseModel):
    view: ImageView
    rotation: Literal[0, 90, 180, 270]
    state: PhotoState
    wrinkle: Wrinkle


class PlacementOut(BaseModel):
    kind: Literal["logo", "print", "patch", "pocket", "text", "other"]
    box: list[int] = Field(min_length=4, max_length=4)
    panel: Literal["front", "back", "left_front", "right_front", "left_back", "right_back", "left_sleeve", "right_sleeve", "hood", "other"] = "front"


class PatternOut(BaseModel):
    kind: PatternKind
    base_color: Optional[str]
    repeats: list[StripeSet] = []
    trims: list[Trim] = []
    placements: list[PlacementOut] = []
    confidence: float = Field(ge=0, le=1)


class TagOut(BaseModel):
    photos: list[PhotoOut]
    best_view_index: int
    garment_box: list[int] = Field(min_length=4, max_length=4)
    slot: Slot
    category: Category
    colors: list[Color]
    pattern: Optional[str]
    material: Optional[str]
    fit: Fit
    style_tags: list[str]
    era: Optional[str]
    size_normalized: Optional[str]
    est_retail_usd: Optional[int]
    confidence: float = Field(ge=0, le=1)
    usable_for_3d: bool
    unusable_reason: Optional[str]
    pattern_spec: Optional[PatternOut]


class Tagged(NamedTuple):
    tags: ItemTags
    photos: list[PhotoOut]
    pattern: Optional[PatternOut]
    best: int


def _inline(schema: dict) -> dict:
    defs = schema.pop("$defs", {})

    def walk(o):
        if isinstance(o, dict):
            if "$ref" in o:
                return walk(defs[o["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in o.items() if k not in DROP}
        return [walk(v) for v in o] if isinstance(o, list) else o

    return walk(schema)


SCHEMA = _inline(TagOut.model_json_schema())


def photo_file(photo: Photo) -> Path:
    return DATA_DIR / photo.url.removeprefix("/static/")


def qualifies(photo: Photo | PhotoOut) -> bool:
    """A 3D source photo shows the whole garment in its natural shape."""
    return photo.state == PhotoState.spread and photo.wrinkle != Wrinkle.high


def _prompt(garment: Garment, n: int, box_order: str) -> str:
    best = garment.best_listing()
    others = [o.title for o in garment.listings if o.status == ListingStatus.active and o.id != best.id][:4]
    also = f"\nAlso listed as: {' | '.join(others)}" if others else ""
    return f"""You tag secondhand clothing. You get {n} photos of ONE garment, numbered 0..{n - 1} in order, possibly taken from several store listings of the same piece.
Title: {best.title}
Brand: {best.brand_raw or "unknown"} · Size as listed: {best.size_raw or "unknown"}
Description: {(best.description or "")[:600]}{also}

Return JSON matching the schema, with exactly one `photos` entry per photo, in order. Use these exact enum values:
- photos[].view: {", ".join(v.value for v in ImageView)}
- photos[].rotation: clockwise degrees that make the garment upright (collar and neck up for tops and outer, waistband up for bottoms, opening up for shoes). 0 when it already is.
- photos[].state: spread = the whole garment is shown in its natural shape (laid flat, hung, on a mannequin or worn); folded = folded over itself; bunched = crumpled, heaped or rolled; unknown = the garment is not visible, e.g. a tag close-up.
- photos[].wrinkle: {", ".join(w.value for w in Wrinkle)}
- slot: {", ".join(s.value for s in Slot)} (onepiece = dress/jumpsuit, outer = layered over a top)
- category: {", ".join(c.value for c in Category)}
- fit: {", ".join(f.value for f in Fit)}
- pattern_spec.kind: {", ".join(k.value for k in PatternKind)}

Rules:
- slot/category: trust the title when it names the garment. Sleeveless tops are tank (slot top); vest is only an outer layer (puffer, denim, suit vest).
- best_view_index: the photo we turn into 3D. It MUST have state spread and wrinkle other than high. Prefer flat_lay > hanger > mannequin > on_model. Never pick a detail shot.
- garment_box: box around the garment in the best photo AS IF that photo were rotated by its rotation, integers on a 0-1000 grid, ordered {box_order}.
- colors: 1-3 dominant garment colors, name like "washed black", hex like "#2b2b2b", ratio = share of garment area.
- style_tags: 2-6 lowercase vibe words (grunge, y2k, emo, gorpcore, streetwear, preppy...). era like "90s" or "2000s" if clear.
- size_normalized: "M" style for tops, "W32" for bottoms, "US10" for shoes, null if unclear.
- est_retail_usd: rough new-retail price in whole dollars, null if no idea.
- usable_for_3d = true only if the best photo shows ONE garment, front-facing, not cropped, not heavily blocked by a body.
  Otherwise false with unusable_reason one of: on_model_occluded, multiple_items, detail_shot, cropped, folded, wrinkled, stock_photo.
- confidence: 0-1, how sure you are about slot and category.

pattern_spec is always required and describes the fabric so we can re-texture the garment. All sizes in centimetres, scaled from the listed size (a W32 flat-lay waist is ~40.6 cm wide, an adult M tee ~51 cm across the chest):
- kind and base_color: the ground fabric, hex.
- repeats: regular stripe or pinstripe repeats; direction grain = along the garment's up/down, cross = across it. Plaid and check = exactly two entries, one grain and one cross.
- trims: bands that follow a seam or edge, e.g. track-pant side stripes (kind side_stripe, placement outseam), piping, waistbands, cuff and hem bands. colors outermost first, widths_cm the same length as colors.
- placements: one-off logos, prints, patches, pockets or text, each with its box on the same 0-1000 grid and the same rotated frame as garment_box, and the panel it sits on.
- Leave repeats, trims and placements empty when the garment has none; a solid garment needs only kind and base_color."""


def _jpeg(path: str | Path) -> bytes:
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def unit_box(box: list[int], order: str = "xyxy") -> tuple[float, float, float, float]:
    """0-1000 grid -> 0-1 [x0, y0, x1, y1]. Perceptron is xyxy, Gemini is yxyx."""
    x0, y0, x1, y1 = box if order == "xyxy" else (box[1], box[0], box[3], box[2])
    x0, x1, y0, y1 = sorted((x0, x1)) + sorted((y0, y1))
    return tuple(min(max(v / 1000, 0.0), 1.0) for v in (x0, y0, x1, y1))


def _perceptron(garment: Garment, images: list[bytes]) -> str:
    with Client() as c:
        out = c.chat.completions.create(
            model="perceptron-mk1.5",
            messages=[{"role": "user", "content": [*map(image, images), _prompt(garment, len(images), "[x0, y0, x1, y1]")]}],
            response_format=json_schema_format(SCHEMA, name="item_tags"),
        )
    return out.text


def _gemini(garment: Garment, images: list[bytes]) -> str:
    prompt = _prompt(garment, len(images), "[ymin, xmin, ymax, xmax]") + f"\n\nJSON schema:\n{json.dumps(SCHEMA)}"
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}} for b in images]
    r = http.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [*parts, {"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _parse(text: str) -> TagOut:
    raw = json.loads(text)
    spec = raw.pop("pattern_spec", None)
    # pattern_spec is required in the schema so the model always estimates it, and validated apart so a bad estimate costs nothing
    out = TagOut.model_validate(raw | {"pattern_spec": None})
    if spec is not None:
        try:
            out.pattern_spec = PatternOut.model_validate(spec)
        except Exception as e:
            print(f"pattern_spec dropped: {e!r}")
    return out


def _tagged(garment: Garment, out: TagOut, tagger: str, order: str) -> Tagged:
    best = out.photos[out.best_view_index]
    tags = ItemTags(
        **out.model_dump(include={"slot", "category", "colors", "pattern", "material", "fit", "style_tags", "era",
                                  "confidence", "usable_for_3d", "unusable_reason"}),
        best_view_index=out.best_view_index,
        est_retail=Money(cents=out.est_retail_usd * 100) if out.est_retail_usd and out.est_retail_usd > 0 else None,
        tagger=tagger,
        size_normalized=sizes.ladder(out.slot, out.size_normalized, garment.best_listing().size_raw),
        garment_box=unit_box(out.garment_box, order),
    )
    if not qualifies(best):
        tags.usable_for_3d = False
        tags.unusable_reason = "folded" if best.state != PhotoState.spread else "wrinkled"
    if out.pattern_spec:
        # placement boxes come back in the provider's order; hand them on as xyxy
        for p in out.pattern_spec.placements:
            p.box = [p.box[1], p.box[0], p.box[3], p.box[2]] if order == "yxyx" else p.box
    return Tagged(tags, out.photos, out.pattern_spec, out.best_view_index)


def tag(garment: Garment, photos: list[Photo]) -> Optional[Tagged]:
    """Mk1.5 twice, then Gemini once. None if every attempt fails."""
    jpegs = [_jpeg(photo_file(p)) for p in photos]
    attempts = [("perceptron-mk1.5", _perceptron, "xyxy")] * 2 + [(GEMINI_MODEL, _gemini, "yxyx")]
    last = None
    for tagger, call, order in attempts:
        if tagger == GEMINI_MODEL and not os.getenv("GEMINI_API_KEY"):
            break
        try:
            out = _parse(call(garment, jpegs))
            if not 0 <= out.best_view_index < len(photos) or len(out.photos) != len(photos):
                raise ValueError(f"best_view_index {out.best_view_index} / {len(out.photos)} photos for {len(photos)} images")
        except Exception as e:
            print(f"tag {garment.id} via {tagger}: {e!r}")
            continue
        last = (out, tagger, order)
        if qualifies(out.photos[out.best_view_index]) or not any(map(qualifies, out.photos)):
            return _tagged(garment, out, tagger, order)
        print(f"tag {garment.id} via {tagger}: best photo {out.best_view_index} is not a 3D source")
    return _tagged(garment, *last) if last else None


def condition(path: str) -> Condition:
    # isaac-0.1 is only served via fal; without FAL_KEY use Mk1.5
    fal = bool(os.getenv("FAL_KEY"))
    with Client(provider="fal") if fal else Client() as c:
        out = c.chat.completions.create(
            model="isaac-0.1" if fal else "perceptron-mk1.5",
            messages=[{"role": "user", "content": [image(_jpeg(path)), "Rate this secondhand garment's condition. Answer with exactly one of: new_with_tags, like_new, good, fair."]}],
        )
    word = out.text.strip().lower()
    return next((c for c in Condition if c != Condition.unknown and c.value in word), Condition.unknown)
