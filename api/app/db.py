import os
import sqlite3
from pathlib import Path

from seam_shared.models import Asset3D, Item, ItemTags, Listing, Outfit

DATA_DIR = Path(os.getenv("DATA_DIR", "../data")).resolve()
ITEM_SELECT = "SELECT items.id, listing, tags, assets.json FROM items LEFT JOIN assets ON assets.item_id = items.id "


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DATA_DIR / "seam.db")
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, source TEXT NOT NULL, listing TEXT NOT NULL, tags TEXT);"
        "CREATE TABLE IF NOT EXISTS assets (item_id TEXT PRIMARY KEY, json TEXT, updated_at TEXT);"
        "CREATE TABLE IF NOT EXISTS outfits (id TEXT PRIMARY KEY, outfit TEXT NOT NULL);"
    )
    return conn


def upsert_listing(conn: sqlite3.Connection, listing: Listing) -> bool:
    item_id = Item.make_id(listing.source, listing.source_id)
    new = conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None
    conn.execute(
        "INSERT INTO items (id, source, listing) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET listing = excluded.listing WHERE items.tags IS NULL",
        (item_id, listing.source.value, listing.model_dump_json()),
    )
    return new


def save_tags(conn: sqlite3.Connection, item_id: str, listing: Listing, tags: ItemTags) -> None:
    conn.execute("UPDATE items SET listing = ?, tags = ? WHERE id = ?", (listing.model_dump_json(), tags.model_dump_json(), item_id))


def items(conn: sqlite3.Connection, where: str = "", params: tuple = ()) -> list[Item]:
    return [
        Item(id=i, listing=Listing.model_validate_json(l), tags=t and ItemTags.model_validate_json(t), asset=a and Asset3D.model_validate_json(a))
        for i, l, t, a in conn.execute(ITEM_SELECT + where, params)
    ]


def save_outfits(conn: sqlite3.Connection, outfits: list[Outfit]) -> None:
    conn.executemany("INSERT INTO outfits (id, outfit) VALUES (?, ?)", [(o.id, o.model_dump_json()) for o in outfits])


def outfits(conn: sqlite3.Connection, ids: list[str]) -> list[Outfit]:
    rows = conn.execute(f"SELECT outfit FROM outfits WHERE id IN ({','.join('?' * len(ids))})", ids) if ids else []
    return [Outfit.model_validate_json(r[0]) for r in rows]
