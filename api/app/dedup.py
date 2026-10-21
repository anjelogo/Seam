import os
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import imagehash
from PIL import Image, ImageOps
from psycopg import Connection
from seam_shared import db
from seam_shared.models import Slot

from app.cv.sizes import ladder
from app.settings import DATA_DIR

MAX_HAMMING = 6
MAX_CANDIDATES = 500
EXIF_ORIENTATION = 0x0112
HAMMING = "bit_count((p.own # p.other)::bit(64))"
PROBE = "SELECT o.listing_id, m.phash AS own, o.phash AS other FROM photos m JOIN photos o ON o.b{i} = m.b{i} WHERE m.listing_id = %s AND o.listing_id <> %s"
# one probe per photos_bN index: an OR chain over the eight bands plans as a seq scan
CANDIDATES = f"""
WITH probes AS ({" UNION ALL ".join(PROBE.format(i=i) for i in range(8))})
SELECT p.listing_id, min({HAMMING}) AS hamming
FROM probes p JOIN listings l ON l.id = p.listing_id AND l.status = 'active'
GROUP BY p.listing_id
HAVING min({HAMMING}) <= {MAX_HAMMING}
ORDER BY hamming
LIMIT {MAX_CANDIDATES}
"""
FACTS = """
SELECT l.id, l.garment_id, l.title, l.seller, l.size_raw, coalesce(l.brand_raw, l.brand) AS brand,
    l.price_cents + coalesce(l.ship_cents, 0) AS total_cents, l.first_seen,
    g.slot, g.category, g.size_norm, g.tags IS NOT NULL AS tagged
FROM listings l LEFT JOIN garments g ON g.id = l.garment_id
WHERE l.id = ANY(%s)
"""
STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "with", "in", "on", "to", "by", "size", "sz", "mens", "men", "womens", "women",
    "unisex", "new", "nwt", "nwot", "euc", "vtg", "vintage", "retro", "rare", "y2k", "90s", "80s", "70s", "00s", "2000s",
    "aesthetic", "style", "cute", "cool", "gently", "used", "preowned", "authentic", "genuine",
}
SIZE_WORDS = {"xxs", "xs", "s", "m", "l", "xl", "xxl", "xxxl", "2xl", "3xl", "4xl", "os", "osfa"}
SIZE_SHAPES = (re.compile(r"\d+x\d+"), re.compile(r"[wl]\d{2}"))
UNKNOWN_BRANDS = {"other", "unbranded", "nobrand", "none", "na", "unknown", "generic", "vintage", "custom", "handmade"}


@dataclass
class Pair:
    listing_id: str
    garment_id: str | None
    hamming: int
    reason: str
    score: float | None


@dataclass
class Decision:
    link: Pair | None
    stock: list[Pair]
    vetoed: list[Pair]


@dataclass
class PhotoMeta:
    path: str
    width: int
    height: int
    phash: int
    exif_rotated: bool


def upright(content: bytes) -> tuple[Image.Image, bool]:
    img = Image.open(BytesIO(content))
    orientation = img.getexif().get(EXIF_ORIENTATION, 1)
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white, img.convert("RGBA"))
    return img.convert("RGB"), orientation not in (None, 1)


def phash(img: Image.Image) -> int:
    u = int(str(imagehash.phash(img, hash_size=8)), 16)
    return u - (1 << 64) if u >= 1 << 63 else u


def _save(img: Image.Image, path: Path) -> None:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        fmt = "JPEG"
    else:
        Image.init()
        fmt = Image.registered_extensions().get(ext, "JPEG")
    tmp = path.with_name(f"{path.name}.tmp")
    img.save(tmp, format=fmt, **({"quality": 92} if fmt in ("JPEG", "WEBP") else {}))
    os.replace(tmp, path)


def store_photo(path: Path, content: bytes | None = None) -> PhotoMeta:
    fresh = content is not None
    img, rotated = upright(content if fresh else path.read_bytes())
    if fresh or rotated:
        _save(img, path)
    return PhotoMeta(
        path=str(path.relative_to(DATA_DIR)), width=img.width, height=img.height, phash=phash(img), exif_rotated=rotated
    )


def _tokens(title: str) -> set[str]:
    out = set()
    for t in re.findall(r"[a-z0-9]+", (title or "").lower()):
        if t in STOPWORDS or t in SIZE_WORDS or (t.isdigit() and len(t) <= 2):
            continue
        if any(shape.fullmatch(t) for shape in SIZE_SHAPES):
            continue
        out.add(t)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _brand(raw: str | None) -> str | None:
    b = re.sub(r"[^a-z0-9]", "", (raw or "").lower())
    return None if not b or b in UNKNOWN_BRANDS else b


def _corroborate(own: dict, other: dict, own_tokens: set[str]) -> tuple[str, float] | None:
    if own["seller"] and own["seller"] == other["seller"]:
        return "phash+seller", 1.0
    jaccard = _jaccard(own_tokens, _tokens(other["title"]))
    if jaccard >= 0.5:
        return "phash+title", jaccard
    a, b = own["total_cents"], other["total_cents"]
    if a and b and abs(a - b) / max(a, b) <= 0.15:
        return "phash+price", 1 - abs(a - b) / max(a, b)
    return None


def _veto(own: dict, other: dict, slot_hint: Slot | None) -> str | None:
    slot = other["slot"] or own["slot"] or (slot_hint.value if slot_hint else None)
    if slot:
        own_size = ladder(Slot(slot), own["size_norm"], own["size_raw"])
        other_size = ladder(Slot(slot), other["size_norm"], other["size_raw"])
        if own_size and other_size and own_size != other_size:
            return "veto:size"
    if own["tagged"] and other["tagged"]:
        if own["slot"] != other["slot"]:
            return "veto:slot"
        if own["category"] != other["category"]:
            return "veto:category"
    own_brand, other_brand = _brand(own["brand"]), _brand(other["brand"])
    if own_brand and other_brand and own_brand not in other_brand and other_brand not in own_brand:
        return "veto:brand"
    return None


def decide(conn: Connection, listing_id: str, slot_hint: Slot | None = None, older_only: bool = False) -> Decision:
    rows = conn.execute(CANDIDATES, (listing_id, listing_id) * 8).fetchall()
    if not rows:
        return Decision(None, [], [])
    facts = {r["id"]: r for r in conn.execute(FACTS, ([listing_id, *(r["listing_id"] for r in rows)],))}
    own = facts.get(listing_id)
    if own is None:
        return Decision(None, [], [])
    own_tokens = _tokens(own["title"])
    links: list[Pair] = []
    stock: list[Pair] = []
    vetoed: list[Pair] = []
    for row in rows:
        other, hamming = facts.get(row["listing_id"]), row["hamming"]
        if other is None or (own["garment_id"] and other["garment_id"] == own["garment_id"]):
            continue
        if older_only and (other["first_seen"], other["id"]) >= (own["first_seen"], own["id"]):
            continue
        base = 1 - hamming / 64
        if veto := _veto(own, other, slot_hint):
            vetoed.append(Pair(other["id"], other["garment_id"], hamming, veto, base))
            continue
        corroborator = _corroborate(own, other, own_tokens)
        if corroborator is None:
            stock.append(Pair(other["id"], other["garment_id"], hamming, "stock_photo", base))
        elif other["garment_id"]:
            reason, score = corroborator
            links.append(Pair(other["id"], other["garment_id"], hamming, reason, (base + score) / 2))
    links.sort(key=lambda p: (-p.score, p.hamming, p.listing_id))
    return Decision(links[0] if links else None, stock, vetoed)


def link(conn: Connection, listing_id: str, slot_hint: Slot | None = None) -> str:
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('seam.link'))")
    existing = db.garment_for_listing(conn, listing_id)
    if existing:
        return existing
    decision = decide(conn, listing_id, slot_hint)
    if decision.link:
        garment_id = decision.link.garment_id
        db.assign_listing(conn, listing_id, garment_id, decision.link.reason, decision.link.score)
    else:
        row = conn.execute("SELECT coalesce(brand_raw, brand) AS brand FROM listings WHERE id = %s", (listing_id,)).fetchone()
        brand = row["brand"] if row else None
        garment_id = db.create_garment(conn, brand=brand if _brand(brand) else None)
        db.assign_listing(conn, listing_id, garment_id, "first", None)
    for pair in decision.stock:
        conn.execute("UPDATE listings SET stock_photo = true WHERE id = ANY(%s)", ([listing_id, pair.listing_id],))
        db.log_link(conn, listing_id, garment_id, pair.garment_id, pair.reason, pair.score)
    for pair in decision.vetoed:
        db.log_link(conn, listing_id, garment_id, pair.garment_id, pair.reason, pair.score)
    return garment_id
