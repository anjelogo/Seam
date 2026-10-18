import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from seam_shared.models import Asset3D, Item, ItemTags, Listing

from app import settings

log = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DATA_DIR / "seam.db", timeout=5)
    conn.execute("CREATE TABLE IF NOT EXISTS assets (item_id TEXT PRIMARY KEY, json TEXT, updated_at TEXT)")
    return conn


def _has_items(conn: sqlite3.Connection) -> bool:
    # the api creates the items table on its first ingest
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'items'").fetchone() is not None


def load() -> list[Asset3D]:
    with closing(_connect()) as conn:
        return [Asset3D.model_validate_json(row[0]) for row in conn.execute("SELECT json FROM assets")]


def stamped() -> dict[str, tuple[Asset3D, datetime]]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT item_id, json, updated_at FROM assets").fetchall()
    return {item_id: (Asset3D.model_validate_json(js), datetime.fromisoformat(at)) for item_id, js, at in rows}


def usable(categories: list[str]) -> list[str]:
    with closing(_connect()) as conn:
        if not _has_items(conn):
            return []
        marks = ", ".join("?" * len(categories))
        rows = conn.execute(
            f"SELECT id FROM items WHERE json_extract(tags, '$.category') IN ({marks}) AND json_extract(tags, '$.usable_for_3d')",
            categories,
        )
        return [row[0] for row in rows]


def get(item_id: str) -> Asset3D | None:
    try:
        with closing(_connect()) as conn:
            row = conn.execute("SELECT json FROM assets WHERE item_id = ?", (item_id,)).fetchone()
    except sqlite3.Error:
        log.exception("could not read asset %s", item_id)
        return None
    return Asset3D.model_validate_json(row[0]) if row else None


def item(item_id: str) -> Item | None:
    with closing(_connect()) as conn:
        if not _has_items(conn):
            return None
        row = conn.execute("SELECT listing, tags FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return None
    listing, tags = row
    tags = ItemTags.model_validate_json(tags) if tags else None
    return Item(id=item_id, listing=Listing.model_validate_json(listing), tags=tags)


def upsert(asset: Asset3D) -> None:
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT INTO assets (item_id, json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at",
                (asset.item_id, asset.model_dump_json(), datetime.now(timezone.utc).isoformat()),
            )
    except sqlite3.Error:
        # the in-memory asset stays authoritative; only restart recovery loses this update
        log.exception("could not save asset %s", asset.item_id)
