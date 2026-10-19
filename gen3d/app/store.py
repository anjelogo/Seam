import logging
from datetime import datetime

import psycopg
from seam_shared import db
from seam_shared.models import Asset3D, Item

log = logging.getLogger(__name__)


def load() -> list[Asset3D]:
    with db.pool().connection() as conn:
        return db.load_assets(conn)


def stamped() -> dict[str, tuple[Asset3D, datetime]]:
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT item_id, json, updated_at FROM assets").fetchall()
    return {r["item_id"]: (Asset3D.model_validate(r["json"]), r["updated_at"]) for r in rows}


def usable(categories: list[str]) -> list[str]:
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT id FROM items WHERE category = ANY(%s) AND usable_3d AND status = 'active'", (categories,))
        return [r["id"] for r in rows]


def get(item_id: str) -> Asset3D | None:
    try:
        with db.pool().connection() as conn:
            return db.get_asset(conn, item_id)
    except psycopg.Error:
        log.exception("could not read asset %s", item_id)
        return None


def item(item_id: str) -> Item | None:
    with db.pool().connection() as conn:
        return db.get_item(conn, item_id)


def upsert(asset: Asset3D) -> None:
    try:
        with db.pool().connection() as conn:
            db.upsert_asset(conn, asset)
    except psycopg.Error:
        # the in-memory asset stays authoritative; only restart recovery loses this update
        log.exception("could not save asset %s", asset.item_id)
