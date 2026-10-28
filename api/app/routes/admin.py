import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from seam_shared import db

from app.auth import ratelimit
from app.auth.deps import User, admin_user

router = APIRouter(prefix="/admin")

# items only, by name: user, session and look tables never leave through here
EXPORT_SQL = (
    "SELECT id, source, source_id, url, title, price_cents, ship_cents, currency, brand, size_raw, condition, slot, category, "
    "usable_3d, status, listing, tags, first_seen, last_seen, tagged_at FROM items ORDER BY id"
)


class Stats(BaseModel):
    items: int
    tagged: int
    active: int


@router.get("/stats", response_model=Stats)
def stats(_: User = Depends(admin_user)) -> Stats:
    with db.pool().connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS items, count(tags) AS tagged, count(*) FILTER (WHERE status = 'active') AS active FROM items"
        ).fetchone()
    return Stats(**row)


@router.get("/export/items")
def export_items(user: User = Depends(admin_user)) -> StreamingResponse:
    with db.pool().connection() as conn:
        if ratelimit.blocked(conn, [f"export:{user.id}"]):
            raise HTTPException(429, "too many exports, try again later.")
    print(f"admin export: items by {user.email}")

    def rows():
        with db.pool().connection() as conn, conn.cursor(name="export_items") as cur:
            cur.execute(EXPORT_SQL)
            for row in cur:
                yield json.dumps(row, default=str) + "\n"

    name = f"items-{date.today()}.jsonl"
    headers = {"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"}
    return StreamingResponse(rows(), media_type="application/x-ndjson", headers=headers)
