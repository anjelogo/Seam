from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query
from seam_shared import db
from seam_shared.models import Category, Item, ItemsResponse, Slot

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
    filters = dict(slot=slot, category=category, q=q, max_cents=max_cents)
    with db.pool().connection() as conn:
        if include_unusable:
            hits, total = db.get_items(conn, **filters, limit=limit, offset=offset)
            return ItemsResponse(items=hits, total=total)
        # shortcut: usable filter runs in Python over every match; push into db.get_items once it takes usable_3d
        hits, _ = db.get_items(conn, **filters, limit=None)
    usable = [i for i in hits if i.tags and i.tags.usable_for_3d]
    return ItemsResponse(items=usable[offset : offset + limit], total=len(usable))


@router.get("/items/{item_id}", response_model=Item)
def get_item(item_id: str) -> Item:
    with db.pool().connection() as conn:
        item = db.get_item(conn, item_id)
    if item is None:
        raise HTTPException(404, f"no item {item_id}")
    return item
