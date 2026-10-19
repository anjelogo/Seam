from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query
from seam_shared.models import Category, Item, ItemsResponse, Slot

from app import db

router = APIRouter()


@router.get("/items", response_model=ItemsResponse)
def list_items(
    slot: Optional[Slot] = None,
    category: Optional[Category] = None,
    q: Optional[str] = None,
    max_cents: Optional[int] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_unusable: bool = False,
) -> ItemsResponse:
    filters = {
        "json_extract(tags, '$.slot') = ?": slot and slot.value,
        "json_extract(tags, '$.category') = ?": category and category.value,
        "json_extract(listing, '$.title') LIKE ?": q and f"%{q}%",
        "json_extract(listing, '$.price.cents') <= ?": max_cents,
    }
    clauses = [k for k, v in filters.items() if v is not None]
    params = tuple(v for v in filters.values() if v is not None)
    if not include_unusable:
        clauses.append("json_extract(tags, '$.usable_for_3d') = 1")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    conn = db.connect()
    total = conn.execute(f"SELECT count(*) FROM items {where}", params).fetchone()[0]
    hits = db.items(conn, f"{where} ORDER BY items.id LIMIT ? OFFSET ?", (*params, limit, offset))
    conn.close()
    return ItemsResponse(items=hits, total=total)


@router.get("/items/{item_id}", response_model=Item)
def get_item(item_id: str) -> Item:
    conn = db.connect()
    hits = db.items(conn, "WHERE items.id = ?", (item_id,))
    conn.close()
    if not hits:
        raise HTTPException(404, f"no item {item_id}")
    return hits[0]
