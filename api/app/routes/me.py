import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from seam_shared import db

from app.auth.deps import User, current_user

router = APIRouter(prefix="/me")

SAVED_LIMIT = 12


class ProfileBody(BaseModel):
    body: dict


class Look(BaseModel):
    prompt: str = Field(max_length=200)
    itemIds: list[str] = Field(max_length=10)


class SavedLook(Look):
    id: UUID


@router.get("/profile", response_model=ProfileBody)
def get_profile(user: User = Depends(current_user)) -> ProfileBody:
    with db.pool().connection() as conn:
        row = conn.execute("SELECT body FROM profiles WHERE user_id = %s", (user.id,)).fetchone()
    if not row:
        raise HTTPException(404, "no profile yet.")
    return ProfileBody(body=row["body"])


@router.put("/profile", response_model=ProfileBody)
def put_profile(profile: ProfileBody, user: User = Depends(current_user)) -> ProfileBody:
    if len(json.dumps(profile.body)) > 4096:
        raise HTTPException(422, "profile too large.")
    with db.pool().connection() as conn:
        conn.execute(
            "INSERT INTO profiles (user_id, body, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (user_id) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
            (user.id, Jsonb(profile.body)),
        )
    return profile


@router.get("/looks", response_model=list[SavedLook])
def get_looks(user: User = Depends(current_user)) -> list[SavedLook]:
    with db.pool().connection() as conn:
        rows = conn.execute(
            "SELECT id, look FROM saved_looks WHERE user_id = %s ORDER BY created_at DESC LIMIT %s", (user.id, SAVED_LIMIT)
        ).fetchall()
        # looks saved before v3 hold listing ids
        legacy = db.garments_for_listings(conn, [i for r in rows for i in r["look"]["itemIds"] if ":" in i])
    looks = []
    for r in rows:
        ids = [legacy[i] if ":" in i else i for i in r["look"]["itemIds"] if ":" not in i or i in legacy]
        looks.append(SavedLook(id=r["id"], prompt=r["look"]["prompt"], itemIds=list(dict.fromkeys(ids))))
    return looks


@router.post("/looks", status_code=201, response_model=SavedLook)
def post_look(look: Look, user: User = Depends(current_user)) -> SavedLook:
    # sorted ids make jsonb equality match the client's order-insensitive dedupe
    look = Look(prompt=look.prompt, itemIds=sorted(set(look.itemIds)))
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM saved_looks WHERE user_id = %s AND look = %s", (user.id, Jsonb(look.model_dump())))
        row = conn.execute(
            "INSERT INTO saved_looks (user_id, look) VALUES (%s, %s) RETURNING id", (user.id, Jsonb(look.model_dump()))
        ).fetchone()
        conn.execute(
            "DELETE FROM saved_looks WHERE user_id = %s AND id NOT IN "
            "(SELECT id FROM saved_looks WHERE user_id = %s ORDER BY created_at DESC LIMIT %s)",
            (user.id, user.id, SAVED_LIMIT),
        )
    return SavedLook(id=row["id"], **look.model_dump())


@router.delete("/looks/{look_id}", status_code=204)
def delete_look(look_id: UUID, user: User = Depends(current_user)) -> None:
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM saved_looks WHERE id = %s AND user_id = %s", (look_id, user.id))
