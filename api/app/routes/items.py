from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query
from seam_shared import db
from seam_shared.models import Category, Item, ItemsResponse, Slot

from app.routes.garments import resolve

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
        hits, total = db.get_garments(conn, slot=slot, category=category, q=q, max_cents=max_cents, usable_3d=usable_3d,
                                      limit=limit, offset=offset)
    return ItemsResponse(items=[db.compat_item(g) for g in hits], total=total)


@router.get("/items/{item_id}", response_model=Item)
def get_item(item_id: str) -> Item:
    with db.pool().connection() as conn:
        garment = resolve(conn, item_id)
    if garment is None:
        raise HTTPException(404, f"no item {item_id}")
    return db.compat_item(garment, None if item_id.startswith("g_") else item_id)
