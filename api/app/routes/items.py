from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query
from seam_shared.models import Category, Item, ItemsResponse, Slot

from app.routes.outfits import FIXTURE

router = APIRouter()


@router.get("/items", response_model=ItemsResponse)
async def list_items(
    slot: Optional[Slot] = None,
    category: Optional[Category] = None,
    q: Optional[str] = None,
    max_cents: Optional[int] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ItemsResponse:
    # TODO(caden): query sqlite store instead
    hits = [
        i
        for i in FIXTURE.items.values()
        if (not slot or (i.tags and i.tags.slot == slot))
        and (not category or (i.tags and i.tags.category == category))
        and (not q or q.lower() in i.listing.title.lower())
        and (max_cents is None or i.listing.price.cents <= max_cents)
    ]
    return ItemsResponse(items=hits[offset : offset + limit], total=len(hits))


@router.get("/items/{item_id}", response_model=Item)
async def get_item(item_id: str) -> Item:
    if item_id not in FIXTURE.items:
        raise HTTPException(404, f"no item {item_id}")
    return FIXTURE.items[item_id]
