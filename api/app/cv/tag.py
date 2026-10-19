import base64
import io
import json
import os
from pathlib import Path
from typing import Optional

from PIL import Image
from perceptron import Client, image, json_schema_format
from pydantic import BaseModel, Field
from seam_shared.models import Category, Color, Condition, Fit, ImageView, ItemTags, Listing, Money, Slot

from app.cv import sizes
from app.sources import client as http

MAX_IMAGES = 8
GEMINI_MODEL = "gemini-3.8-flash"


class TagOut(BaseModel):
    views: list[ImageView]
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


def _inline(schema: dict) -> dict:
    defs = schema.pop("$defs", {})

    def walk(o):
        if isinstance(o, dict):
            return walk(defs[o["$ref"].split("/")[-1]]) if "$ref" in o else {k: walk(v) for k, v in o.items()}
        return [walk(v) for v in o] if isinstance(o, list) else o

    return walk(schema)


SCHEMA = _inline(TagOut.model_json_schema())


def _prompt(listing: Listing, n: int, box_order: str) -> str:
    return f"""You tag secondhand clothing listings. You get {n} photos of ONE listing, numbered 0..{n - 1} in order.
Title: {listing.title}
Brand: {listing.brand or "unknown"} · Size as listed: {listing.size_raw or "unknown"}
Description: {(listing.description or "")[:600]}

Return JSON matching the schema. Use these exact enum values:
- views (one per photo, in order): {", ".join(v.value for v in ImageView)}
- slot: {", ".join(s.value for s in Slot)} (onepiece = dress/jumpsuit, outer = layered over a top)
- category: {", ".join(c.value for c in Category)}
- fit: {", ".join(f.value for f in Fit)}

Rules:
- slot/category: trust the title when it names the garment. Sleeveless tops are tank (slot top); vest is only an outer layer (puffer, denim, suit vest).
- best_view_index: the photo to turn into 3D. Prefer flat_lay > hanger > mannequin > on_model. Never pick a detail shot.
- garment_box: box around the main garment in the best view, integers on a 0-1000 grid, ordered {box_order}.
- colors: 1-3 dominant garment colors, name like "washed black", hex like "#2b2b2b", ratio = share of garment area.
- style_tags: 2-6 lowercase vibe words (grunge, y2k, emo, gorpcore, streetwear, preppy...). era like "90s" or "2000s" if clear.
- size_normalized: "M" style for tops, "W32" for bottoms, "US10" for shoes, null if unclear.
- est_retail_usd: rough new-retail price in whole dollars, null if no idea.
- usable_for_3d = true only if the best photo shows ONE garment, front-facing, not cropped, not heavily blocked by a body.
  Otherwise false with unusable_reason one of: on_model_occluded, multiple_items, detail_shot, cropped.
- confidence: 0-1, how sure you are about slot and category."""


def _jpeg(path: str) -> bytes:
    img = Image.open(path).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def unit_box(box: list[int], order: str = "xyxy") -> tuple[float, float, float, float]:
    """0-1000 grid -> 0-1 [x0, y0, x1, y1]. Perceptron is xyxy, Gemini is yxyx."""
    x0, y0, x1, y1 = box if order == "xyxy" else (box[1], box[0], box[3], box[2])
    x0, x1, y0, y1 = sorted((x0, x1)) + sorted((y0, y1))
    return tuple(min(max(v / 1000, 0.0), 1.0) for v in (x0, y0, x1, y1))


def _perceptron(listing: Listing, images: list[bytes]) -> str:
    with Client() as c:
        out = c.chat.completions.create(
            model="perceptron-mk1.5",
            messages=[{"role": "user", "content": [*map(image, images), _prompt(listing, len(images), "[x0, y0, x1, y1]")]}],
            response_format=json_schema_format(SCHEMA, name="item_tags"),
        )
    return out.text


def _gemini(listing: Listing, images: list[bytes]) -> str:
    prompt = _prompt(listing, len(images), "[ymin, xmin, ymax, xmax]") + f"\n\nJSON schema:\n{json.dumps(SCHEMA)}"
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}} for b in images]
    r = http.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [*parts, {"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def tag(listing: Listing) -> Optional[tuple[ItemTags, list[ImageView]]]:
    """Mk1.5 twice, then Gemini once. None if every attempt fails."""
    imgs = listing.images[:MAX_IMAGES]
    jpegs = [_jpeg(i.local_path) for i in imgs]
    attempts = [("perceptron-mk1.5", _perceptron, "xyxy")] * 2 + [(GEMINI_MODEL, _gemini, "yxyx")]
    for tagger, call, order in attempts:
        if tagger == GEMINI_MODEL and not os.getenv("GEMINI_API_KEY"):
            break
        try:
            out = TagOut.model_validate_json(call(listing, jpegs))
            if not 0 <= out.best_view_index < len(imgs) or len(out.views) != len(imgs):
                raise ValueError(f"best_view_index {out.best_view_index} / {len(out.views)} views for {len(imgs)} images")
        except Exception as e:
            print(f"tag {listing.source_id} via {tagger}: {e!r}")
            continue
        tags = ItemTags(
            **out.model_dump(include={"slot", "category", "colors", "pattern", "material", "fit", "style_tags", "era",
                                      "confidence", "best_view_index", "usable_for_3d", "unusable_reason"}),
            est_retail=Money(cents=out.est_retail_usd * 100) if out.est_retail_usd and out.est_retail_usd > 0 else None,
            tagger=tagger,
            size_normalized=sizes.ladder(out.slot, out.size_normalized, listing.size_raw),
            garment_box=unit_box(out.garment_box, order),
        )
        return tags, out.views
    return None


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
