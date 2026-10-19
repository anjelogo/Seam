import os
import threading
from datetime import timedelta
from typing import Literal
from uuid import UUID

from psycopg import AsyncConnection, Connection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from seam_shared.models import Asset3D, Item, ItemTags, Listing, Outfit

ITEM_SELECT = "SELECT items.id, items.listing, items.tags, assets.json AS asset FROM items LEFT JOIN assets ON assets.item_id = items.id"
ORDERS = {"id": "items.id", "price": "items.price_cents + coalesce(items.ship_cents, 0), items.id", "newest": "items.first_seen DESC, items.id"}
UPSERT_LISTING = """
INSERT INTO items (id, source, source_id, url, title, price_cents, ship_cents, currency, brand, size_raw, condition, listing)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
ON CONFLICT (id) DO UPDATE SET
    url = excluded.url, title = excluded.title, price_cents = excluded.price_cents, ship_cents = excluded.ship_cents,
    currency = excluded.currency, brand = excluded.brand, size_raw = excluded.size_raw, condition = excluded.condition,
    listing = excluded.listing, status = 'active', last_seen = now()
RETURNING xmax = 0 AS added
"""

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


def _item(row: dict) -> Item:
    return Item(
        id=row["id"],
        listing=Listing.model_validate(row["listing"]),
        tags=ItemTags.model_validate(row["tags"]) if row["tags"] else None,
        asset=Asset3D.model_validate(row["asset"]) if row["asset"] else None,
    )


def _listing_params(listing: Listing) -> tuple:
    return (
        Item.make_id(listing.source, listing.source_id), listing.source.value, listing.source_id, listing.url, listing.title,
        listing.price.cents, listing.shipping.cents if listing.shipping else None, listing.price.currency,
        listing.brand, listing.size_raw, listing.condition.value, listing.model_dump_json(),
    )


def upsert_listing(conn: Connection, listing: Listing) -> Literal["added", "updated"]:
    row = conn.execute(UPSERT_LISTING, _listing_params(listing)).fetchone()
    return "added" if row["added"] else "updated"


async def aupsert_listing(conn: AsyncConnection, listing: Listing) -> Literal["added", "updated"]:
    row = await (await conn.execute(UPSERT_LISTING, _listing_params(listing))).fetchone()
    return "added" if row["added"] else "updated"


def save_tags(conn: Connection, item_id: str, listing: Listing, tags: ItemTags) -> None:
    conn.execute(
        "UPDATE items SET listing = %s::jsonb, condition = %s, tags = %s::jsonb, slot = %s, category = %s, usable_3d = %s, tagged_at = now() WHERE id = %s",
        (listing.model_dump_json(), listing.condition.value, tags.model_dump_json(), tags.slot.value, tags.category.value, tags.usable_for_3d, item_id),
    )


def untagged_ids(conn: Connection, limit: int) -> list[str]:
    rows = conn.execute("SELECT id FROM items WHERE tags IS NULL AND status = 'active' ORDER BY first_seen LIMIT %s", (limit,))
    return [r["id"] for r in rows]


def get_item(conn: Connection, item_id: str) -> Item | None:
    row = conn.execute(f"{ITEM_SELECT} WHERE items.id = %s", (item_id,)).fetchone()
    return _item(row) if row else None


def _items_sql(*, ids=None, slot=None, category=None, q=None, max_cents=None, sources=None, require_3d_ready=False,
               status="active", order="id", limit=50, offset=0) -> tuple[str, list, str, list]:
    filters = [
        ("items.id = ANY(%s)", None if ids is None else list(ids)),
        ("items.slot = %s", slot),
        ("items.category = %s", category),
        ("items.title ILIKE %s", f"%{q}%" if q else None),
        ("items.price_cents + coalesce(items.ship_cents, 0) <= %s", max_cents),
        ("items.source = ANY(%s)", list(sources) if sources else None),
        ("items.status = %s", status),
    ]
    used = [(clause, value) for clause, value in filters if value is not None]
    clauses = [clause for clause, _ in used] + (["assets.json->>'status' = 'ready'"] if require_3d_ready else [])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params = [value for _, value in used]
    count = f"SELECT count(*) AS n FROM items LEFT JOIN assets ON assets.item_id = items.id{where}"
    page = f"{ITEM_SELECT}{where} ORDER BY {ORDERS[order]} LIMIT %s OFFSET %s"
    return count, params, page, [*params, limit, offset]


def get_items(conn: Connection, **filters) -> tuple[list[Item], int]:
    count, params, page, page_params = _items_sql(**filters)
    total = conn.execute(count, params).fetchone()["n"]
    return [_item(r) for r in conn.execute(page, page_params)], total


async def aget_items(conn: AsyncConnection, **filters) -> tuple[list[Item], int]:
    count, params, page, page_params = _items_sql(**filters)
    total = (await (await conn.execute(count, params)).fetchone())["n"]
    rows = await (await conn.execute(page, page_params)).fetchall()
    return [_item(r) for r in rows], total


def save_outfits(conn: Connection, outfits: list[Outfit], user_id: UUID | None = None) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO outfits (id, user_id, outfit) VALUES (%s, %s, %s::jsonb)", [(o.id, user_id, o.model_dump_json()) for o in outfits]
        )


def get_outfits(conn: Connection, ids: list[str], user_id: UUID | None = None) -> list[Outfit]:
    rows = conn.execute("SELECT outfit FROM outfits WHERE id = ANY(%s) AND user_id IS NOT DISTINCT FROM %s", (list(ids), user_id))
    return [Outfit.model_validate(r["outfit"]) for r in rows]


def load_assets(conn: Connection) -> list[Asset3D]:
    return [Asset3D.model_validate(r["json"]) for r in conn.execute("SELECT json FROM assets")]


def get_asset(conn: Connection, item_id: str) -> Asset3D | None:
    row = conn.execute("SELECT json FROM assets WHERE item_id = %s", (item_id,)).fetchone()
    return Asset3D.model_validate(row["json"]) if row else None


def upsert_asset(conn: Connection, asset: Asset3D) -> None:
    conn.execute(
        "INSERT INTO assets (item_id, json, updated_at) VALUES (%s, %s::jsonb, now()) "
        "ON CONFLICT (item_id) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at",
        (asset.item_id, asset.model_dump_json()),
    )


def expire_stale(conn: Connection, hours: float) -> int:
    cur = conn.execute("UPDATE items SET status = 'gone' WHERE status = 'active' AND last_seen < now() - %s", (timedelta(hours=hours),))
    return cur.rowcount


def start_run(conn: Connection, source, query: str, slot) -> int:
    return conn.execute("INSERT INTO scrape_runs (source, query, slot) VALUES (%s, %s, %s) RETURNING id", (source, query, slot)).fetchone()["id"]


def finish_run(conn: Connection, run_id: int, *, fetched: int, added: int, updated: int, errors: int, last_error: str | None = None) -> None:
    conn.execute(
        "UPDATE scrape_runs SET finished_at = now(), fetched = %s, added = %s, updated = %s, errors = %s, last_error = %s WHERE id = %s",
        (fetched, added, updated, errors, last_error, run_id),
    )
