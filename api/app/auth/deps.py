from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel
from seam_shared import db

from app.auth import sessions


class User(BaseModel):
    id: UUID
    email: str
    name: str


def optional_user(request: Request, response: Response) -> User | None:
    token = request.cookies.get(sessions.COOKIE)
    if not token:
        return None
    with db.pool().connection() as conn:
        row = sessions.lookup(conn, token)
    if not row:
        return None
    if row["slid"]:
        sessions.set_cookie(response, token)
    return User(id=row["id"], email=row["email"], name=row["name"])


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "log in first.")
    return user
