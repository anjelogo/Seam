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
    usable_3d = None if include_unusable else True
    with db.pool().connection() as conn:
        hits, total = db.get_items(conn, slot=slot, category=category, q=q, max_cents=max_cents, usable_3d=usable_3d, limit=limit, offset=offset)
    return ItemsResponse(items=hits, total=total)


@router.get("/items/{item_id}", response_model=Item)
def get_item(item_id: str) -> Item:
    with db.pool().connection() as conn:
        item = db.get_item(conn, item_id)
    if item is None:
        raise HTTPException(404, f"no item {item_id}")
    return item
