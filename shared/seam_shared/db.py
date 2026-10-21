import os
import re
import secrets
import threading
import time
from collections import defaultdict
from datetime import timedelta
from typing import Literal
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from seam_shared.models import (
    Asset3D,
    Condition,
    Garment,
    ImageRef,
    ImageView,
    Item,
    ItemTags,
    Listing,
    ListingOffer,
    ListingStatus,
    Money,
    Outfit,
    PatternSpec,
    Photo,
    PhotoState,
    Wrinkle,
)

# best = the garment's cheapest listing of the wanted status: the price and source filters apply to it
GARMENT_BEST = """
JOIN LATERAL (
    SELECT l.id, l.source, l.price_cents + coalesce(l.ship_cents, 0) AS total
    FROM listings l WHERE l.garment_id = garments.id{status}
    ORDER BY total, l.id LIMIT 1
) best ON true
LEFT JOIN assets ON assets.garment_id = garments.id
"""
GARMENT_ORDERS = {"id": "garments.id", "price": "best.total, garments.id", "newest": "garments.created_at DESC, garments.id"}
UPSERT_LISTING = """
INSERT INTO listings (id, source, source_id, url, title, price_cents, ship_cents, currency, brand, size_raw, condition, listing, seller, brand_raw, stated_condition)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    url = excluded.url, title = excluded.title, price_cents = excluded.price_cents, ship_cents = excluded.ship_cents,
    currency = excluded.currency, brand = excluded.brand, size_raw = excluded.size_raw, condition = excluded.condition,
    listing = excluded.listing, seller = excluded.seller, brand_raw = excluded.brand_raw, stated_condition = excluded.stated_condition,
    status = 'active', last_seen = now()
RETURNING xmax = 0 AS added
"""
UPSERT_PHOTO = """
INSERT INTO photos (listing_id, idx, path, width, height, phash, b0, b1, b2, b3, b4, b5, b6, b7, exif_rotated)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (listing_id, idx) DO UPDATE SET
    path = excluded.path, width = excluded.width, height = excluded.height, phash = excluded.phash,
    b0 = excluded.b0, b1 = excluded.b1, b2 = excluded.b2, b3 = excluded.b3, b4 = excluded.b4, b5 = excluded.b5, b6 = excluded.b6, b7 = excluded.b7,
    exif_rotated = photos.exif_rotated OR excluded.exif_rotated
RETURNING id
"""
GARMENT_LISTINGS = """
SELECT id, garment_id, source, url, title, price_cents, ship_cents, currency, size_raw, status, first_seen, last_seen,
    coalesce(brand_raw, brand) AS brand_raw, coalesce(stated_condition, condition) AS stated_condition, assessed_condition,
    listing->>'description' AS description, listing->>'seller' AS seller
FROM listings WHERE garment_id = ANY(%s)
ORDER BY status <> 'active', price_cents + coalesce(ship_cents, 0), id
"""
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_lock = threading.Lock()
_pool: ConnectionPool | None = None
_apool: AsyncConnectionPool | None = None


def url() -> str:
    return os.getenv("DATABASE_URL") or "postgresql://seam:seam@localhost:5432/seam"


def pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(url(), kwargs={"row_factory": dict_row}, min_size=1, max_size=10, open=True)
    return _pool


def apool() -> AsyncConnectionPool:
    """`await db.apool().open()` before first use in an event loop; it is a no-op once open."""
    global _apool
    if _apool is None:
        _apool = AsyncConnectionPool(url(), kwargs={"row_factory": dict_row}, min_size=1, max_size=10, open=False)
    return _apool


def norm_seller(name: str | None) -> str | None:
    return (re.sub(r"[^a-z0-9]", "", name.lower()) or None) if name else None


def _listing_params(listing: Listing) -> tuple:
    return (
        Item.make_id(listing.source, listing.source_id), listing.source.value, listing.source_id, listing.url, listing.title,
        listing.price.cents, listing.shipping.cents if listing.shipping else None, listing.price.currency,
        listing.brand, listing.size_raw, listing.condition.value, listing.model_dump_json(),
        norm_seller(listing.seller), listing.brand, listing.condition.value,
    )


def upsert_listing(conn: Connection, listing: Listing) -> Literal["added", "updated"]:
    row = conn.execute(UPSERT_LISTING, _listing_params(listing)).fetchone()
    return "added" if row["added"] else "updated"


def save_assessed_condition(conn: Connection, listing_id: str, condition: Condition) -> None:
    conn.execute("UPDATE listings SET assessed_condition = %s WHERE id = %s", (condition.value, listing_id))


def bands(phash: int) -> list[int]:
    u = phash & 0xFFFF_FFFF_FFFF_FFFF
    return [(u >> (8 * i)) & 0xFF for i in range(8)]


def upsert_photo(conn: Connection, listing_id: str, idx: int, *, path: str, width: int | None, height: int | None,
                 phash: int, exif_rotated: bool) -> int:
    params = (listing_id, idx, path, width, height, phash, *bands(phash), exif_rotated)
    return conn.execute(UPSERT_PHOTO, params).fetchone()["id"]


def photo_idxs(conn: Connection, listing_id: str) -> set[int]:
    return {r["idx"] for r in conn.execute("SELECT idx FROM photos WHERE listing_id = %s", (listing_id,))}


def save_photo_tags(conn: Connection, photo_id: int, *, view: ImageView, rotation: int, state: PhotoState, wrinkle: Wrinkle) -> None:
    conn.execute(
        "UPDATE photos SET view = %s, rotation = %s, state = %s, wrinkle = %s WHERE id = %s",
        (view.value, rotation, state.value, wrinkle.value, photo_id),
    )


def new_garment_id() -> str:
    n = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    return "g_" + "".join(CROCKFORD[(n >> (5 * i)) & 31] for i in reversed(range(26)))


def create_garment(conn: Connection, *, brand: str | None = None, garment_id: str | None = None) -> str:
    garment_id = garment_id or new_garment_id()
    conn.execute("INSERT INTO garments (id, brand) VALUES (%s, %s)", (garment_id, brand))
    return garment_id


def log_link(conn: Connection, listing_id: str, from_garment: str | None, to_garment: str | None, reason: str,
             score: float | None = None) -> None:
    conn.execute(
        "INSERT INTO garment_links_log (listing_id, from_garment, to_garment, reason, score) VALUES (%s, %s, %s, %s, %s)",
        (listing_id, from_garment, to_garment, reason, score),
    )


def garment_for_listing(conn: Connection, listing_id: str) -> str | None:
    row = conn.execute("SELECT garment_id FROM listings WHERE id = %s", (listing_id,)).fetchone()
    return row["garment_id"] if row else None


def garments_for_listings(conn: Connection, listing_ids: list[str]) -> dict[str, str]:
    rows = conn.execute("SELECT id, garment_id FROM listings WHERE id = ANY(%s) AND garment_id IS NOT NULL", (list(listing_ids),))
    return {r["id"]: r["garment_id"] for r in rows}


def assign_listing(conn: Connection, listing_id: str, garment_id: str, reason: str, score: float | None = None) -> None:
    previous = garment_for_listing(conn, listing_id)
    conn.execute(
        "UPDATE listings SET garment_id = %s, link_reason = %s, link_score = %s WHERE id = %s", (garment_id, reason, score, listing_id)
    )
    log_link(conn, listing_id, previous, garment_id, reason, score)


def _photo(row: dict) -> Photo:
    return Photo(
        id=row["id"], listing_id=row["listing_id"], idx=row["idx"], url=f"/static/{row['path']}", width=row["width"], height=row["height"],
        view=row["view"] or ImageView.unknown, rotation=row["rotation"], state=row["state"] or PhotoState.unknown,
        wrinkle=row["wrinkle"] or Wrinkle.unknown,
    )


def _offer(row: dict, photos: list[Photo]) -> ListingOffer:
    currency = row["currency"] or "USD"
    return ListingOffer(
        id=row["id"], source=row["source"], url=row["url"], title=row["title"], description=row["description"],
        price=Money(cents=row["price_cents"], currency=currency),
        shipping=Money(cents=row["ship_cents"], currency=currency) if row["ship_cents"] is not None else None,
        seller=row["seller"], size_raw=row["size_raw"], brand_raw=row["brand_raw"],
        stated_condition=row["stated_condition"] or Condition.unknown, assessed_condition=row["assessed_condition"] or Condition.unknown,
        status=row["status"], photos=photos, **{k: row[k] for k in ("first_seen", "last_seen") if row[k]},
    )


def get_garments_by_id(conn: Connection, ids: list[str]) -> dict[str, Garment]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    rows = {
        r["id"]: r
        for r in conn.execute("SELECT garments.*, assets.json AS asset FROM garments LEFT JOIN assets ON assets.garment_id = garments.id WHERE garments.id = ANY(%s)", (ids,))
    }
    listings = conn.execute(GARMENT_LISTINGS, (ids,)).fetchall()
    photos = defaultdict(list)
    for r in conn.execute(
        "SELECT id, listing_id, idx, path, width, height, view, rotation, state, wrinkle FROM photos WHERE listing_id = ANY(%s) ORDER BY listing_id, idx",
        ([r["id"] for r in listings],),
    ):
        photos[r["listing_id"]].append(_photo(r))
    by_photo = {p.id: p for ps in photos.values() for p in ps}
    offers = defaultdict(list)
    for r in listings:
        offers[r["garment_id"]].append(_offer(r, photos[r["id"]]))
    garments = {}
    for garment_id in ids:
        row, listed = rows.get(garment_id), offers.get(garment_id)
        if not (row and listed):
            continue
        best = next((o for o in listed if o.status == ListingStatus.active), listed[0])
        garments[garment_id] = Garment(
            id=garment_id,
            tags=ItemTags.model_validate(row["tags"]) if row["tags"] else None,
            pattern_spec=PatternSpec.model_validate(row["pattern_spec"]) if row["pattern_spec"] else None,
            best_photo=by_photo.get(row["best_photo_id"]),
            listings=listed,
            best_listing_id=best.id,
            asset=Asset3D.model_validate(row["asset"]) if row["asset"] else None,
        )
    return garments


def get_garment(conn: Connection, garment_id: str) -> Garment | None:
    return get_garments_by_id(conn, [garment_id]).get(garment_id)


def save_garment_tags(conn: Connection, garment_id: str, tags: ItemTags, pattern_spec: PatternSpec | None, best_photo_id: int | None) -> None:
    conn.execute(
        "UPDATE garments SET tags = %s::jsonb, pattern_spec = %s::jsonb, slot = %s, category = %s, size_norm = %s, usable_3d = %s, "
        "best_photo_id = %s, tagged_at = now() WHERE id = %s",
        (
            tags.model_dump_json(), pattern_spec.model_dump_json() if pattern_spec else None, tags.slot.value, tags.category.value,
            tags.size_normalized, tags.usable_for_3d, best_photo_id, garment_id,
        ),
    )


def untagged_garment_ids(conn: Connection, limit: int) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM garments WHERE tags IS NULL AND EXISTS "
        "(SELECT 1 FROM listings WHERE listings.garment_id = garments.id AND listings.status = 'active') ORDER BY created_at LIMIT %s",
        (limit,),
    )
    return [r["id"] for r in rows]


def _garments_sql(*, ids=None, slot=None, category=None, q=None, max_cents=None, sources=None, require_3d_ready=False,
                  usable_3d=None, status="active", order="id", limit=50, offset=0) -> tuple[str, list, str, list]:
    status_and = "" if status is None else " AND l.status = %s"
    frm = f"FROM garments {GARMENT_BEST.format(status=status_and)}"
    params = [] if status is None else [status]
    filters = [
        ("garments.id = ANY(%s)", None if ids is None else list(ids)),
        ("garments.slot = %s", slot),
        ("garments.category = %s", category),
        ("garments.usable_3d = %s", usable_3d),
        ("best.total <= %s", max_cents),
        ("best.source = ANY(%s)", list(sources) if sources else None),
    ]
    used = [(clause, value) for clause, value in filters if value is not None]
    clauses = [clause for clause, _ in used]
    params += [value for _, value in used]
    if q:
        clauses.append(f"EXISTS (SELECT 1 FROM listings l WHERE l.garment_id = garments.id{status_and} AND l.title ILIKE %s)")
        params += ([] if status is None else [status]) + [f"%{q}%"]
    if require_3d_ready:
        clauses.append("assets.json->>'status' = 'ready'")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    count = f"SELECT count(*) AS n {frm}{where}"
    page = f"SELECT garments.id {frm}{where} ORDER BY {GARMENT_ORDERS[order]} LIMIT %s OFFSET %s"
    return count, params, page, [*params, limit, offset]


def get_garments(conn: Connection, **filters) -> tuple[list[Garment], int]:
    count, params, page, page_params = _garments_sql(**filters)
    total = conn.execute(count, params).fetchone()["n"]
    ids = [r["id"] for r in conn.execute(page, page_params)]
    found = get_garments_by_id(conn, ids)
    return [found[i] for i in ids if i in found], total


def compat_item(garment: Garment, listing_id: str | None = None) -> Item:
    """The v2 Item shape for one of a garment's listings, keyed by the garment id."""
    offer = next((o for o in garment.listings if o.id == listing_id), garment.best_listing())
    tags = garment.tags
    if tags:
        best = garment.best_photo
        tags = tags.model_copy(update={"best_view_index": best.idx if best and best.listing_id == offer.id else 0})
    condition = offer.assessed_condition if offer.assessed_condition != Condition.unknown else offer.stated_condition
    return Item(
        id=garment.id,
        listing=Listing(
            source=offer.source, source_id=offer.id.split(":", 1)[1], url=offer.url, title=offer.title, description=offer.description,
            price=offer.price, shipping=offer.shipping, condition=condition, brand=offer.brand_raw, size_raw=offer.size_raw,
            images=[ImageRef(url=p.url, width=p.width, height=p.height, view=p.view) for p in offer.photos],
            seller=offer.seller, scraped_at=offer.last_seen,
        ),
        tags=tags,
        asset=garment.asset,
    )


def save_outfits(conn: Connection, outfits: list[Outfit], user_id: UUID | None = None) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO outfits (id, user_id, outfit) VALUES (%s, %s, %s::jsonb)", [(o.id, user_id, o.model_dump_json()) for o in outfits]
        )


def get_outfits(conn: Connection, ids: list[str], user_id: UUID | None = None) -> list[Outfit]:
    rows = conn.execute("SELECT outfit FROM outfits WHERE id = ANY(%s) AND user_id IS NOT DISTINCT FROM %s", (list(ids), user_id))
    return [Outfit.model_validate(r["outfit"]) for r in rows]


def load_assets(conn: Connection) -> list[Asset3D]:
    return [Asset3D.model_validate(r["json"]) for r in conn.execute("SELECT json FROM assets WHERE garment_id IS NOT NULL")]


def get_asset(conn: Connection, garment_id: str) -> Asset3D | None:
    row = conn.execute("SELECT json FROM assets WHERE garment_id = %s", (garment_id,)).fetchone()
    return Asset3D.model_validate(row["json"]) if row else None


def upsert_asset(conn: Connection, asset: Asset3D) -> None:
    conn.execute(
        "INSERT INTO assets (item_id, garment_id, json, updated_at) VALUES (%s, %s, %s::jsonb, now()) "
        "ON CONFLICT (garment_id) DO UPDATE SET item_id = excluded.item_id, json = excluded.json, updated_at = excluded.updated_at",
        (asset.item_id, asset.item_id, asset.model_dump_json()),
    )


def expire_stale(conn: Connection, hours: float) -> int:
    cur = conn.execute("UPDATE listings SET status = 'gone' WHERE status = 'active' AND last_seen < now() - %s", (timedelta(hours=hours),))
    return cur.rowcount


def start_run(conn: Connection, source, query: str, slot) -> int:
    return conn.execute("INSERT INTO scrape_runs (source, query, slot) VALUES (%s, %s, %s) RETURNING id", (source, query, slot)).fetchone()["id"]


def finish_run(conn: Connection, run_id: int, *, fetched: int, added: int, updated: int, errors: int, last_error: str | None = None) -> None:
    conn.execute(
        "UPDATE scrape_runs SET finished_at = now(), fetched = %s, added = %s, updated = %s, errors = %s, last_error = %s WHERE id = %s",
        (fetched, added, updated, errors, last_error, run_id),
    )
