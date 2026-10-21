from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query
from psycopg import Connection
from seam_shared import db
from seam_shared.models import Category, Garment, GarmentsResponse, Slot, Source

router = APIRouter()


def resolve(conn: Connection, ref: str) -> Garment | None:
    """ref is a garment id, or a listing id to follow to its garment."""
    if not ref.startswith("g_"):
        ref = db.garments_for_listings(conn, [ref]).get(ref, "")
    return db.get_garment(conn, ref) if ref else None


@router.get("/garments", response_model=GarmentsResponse)
def list_garments(
    slot: Optional[Slot] = None,
    category: Optional[Category] = None,
    q: Optional[str] = None,
    max_cents: Optional[int] = None,
    sources: Annotated[Optional[list[Source]], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_unusable: bool = False,
) -> GarmentsResponse:
    usable_3d = None if include_unusable else True
    with db.pool().connection() as conn:
        hits, total = db.get_garments(conn, slot=slot, category=category, q=q, max_cents=max_cents, sources=sources or None,
                                      usable_3d=usable_3d, limit=limit, offset=offset)
    return GarmentsResponse(garments=hits, total=total)


@router.get("/garments/{garment_id}", response_model=Garment)
def get_garment(garment_id: str) -> Garment:
    with db.pool().connection() as conn:
        garment = resolve(conn, garment_id)
    if garment is None:
        raise HTTPException(404, f"no garment {garment_id}")
    return garment
