from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class Health(BaseModel):
    ok: bool = True
    gpu: Optional[str] = None


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health()
