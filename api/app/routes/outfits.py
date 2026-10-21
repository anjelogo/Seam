from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from seam_shared import db
from seam_shared.models import OutfitResponse, OutfitResponseV3, StyleQuery

from app.auth.deps import User, current_user
from app.llm import curate

router = APIRouter()


@router.post("/outfits", response_model=OutfitResponseV3 | OutfitResponse)
def post_outfits(query: StyleQuery, include_unusable: bool = False, v: Optional[int] = None, user: User = Depends(current_user)):
    try:
        res = curate.build(query, user_id=user.id, include_unusable=include_unusable)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except anthropic.AnthropicError as e:
        raise HTTPException(502, f"outfit llm: {e}")
    if v == 3:
        return res
    items = {gid: db.compat_item(g) for gid, g in res.garments.items()}
    return OutfitResponse(query=res.query, outfits=res.outfits, items=items, took_ms=res.took_ms)
