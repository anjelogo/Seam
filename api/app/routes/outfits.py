import anthropic
from fastapi import APIRouter, Depends, HTTPException
from seam_shared.models import OutfitResponse, StyleQuery

from app.auth.deps import User, current_user
from app.llm import curate

router = APIRouter()


@router.post("/outfits", response_model=OutfitResponse)
def post_outfits(query: StyleQuery, include_unusable: bool = False, user: User = Depends(current_user)) -> OutfitResponse:
    try:
        return curate.build(query, user_id=user.id, include_unusable=include_unusable)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except anthropic.AnthropicError as e:
        raise HTTPException(502, f"outfit llm: {e}")
