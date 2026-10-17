import time
from pathlib import Path

from fastapi import APIRouter
from seam_shared.models import OutfitResponse, StyleQuery

router = APIRouter()

FIXTURE = OutfitResponse.model_validate_json(
    (Path(__file__).resolve().parents[3] / "shared/schema/fixtures/outfit_response.json").read_bytes()
)


@router.post("/outfits", response_model=OutfitResponse)
async def post_outfits(query: StyleQuery) -> OutfitResponse:
    start = time.perf_counter()
    # TODO(caden): replace fixture with llm outfits
    return FIXTURE.model_copy(update={"query": query, "took_ms": int((time.perf_counter() - start) * 1000)})
