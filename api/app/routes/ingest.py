from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from seam_shared.models import Source

from app import ingest

router = APIRouter()


class IngestRun(BaseModel):
    queries: list[str]
    sources: list[Source] = []


class IngestResult(BaseModel):
    added: int


@router.post("/ingest/run", response_model=IngestResult)
def run_ingest(body: IngestRun) -> IngestResult:
    sources = body.sources or list(ingest.ADAPTERS)
    unsupported = [s.value for s in sources if s not in ingest.ADAPTERS]
    if unsupported:
        raise HTTPException(400, f"no adapter for {', '.join(unsupported)}")
    return IngestResult(added=ingest.run(body.queries, sources))
