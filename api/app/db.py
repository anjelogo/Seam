import os
import sqlite3
from pathlib import Path

from seam_shared.models import Item, ItemTags, Listing

DATA_DIR = Path(os.getenv("DATA_DIR", "../data")).resolve()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DATA_DIR / "seam.db")
    conn.execute("CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, source TEXT NOT NULL, listing TEXT NOT NULL, tags TEXT)")
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
