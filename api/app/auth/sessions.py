import hashlib
import os
import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import Response
from psycopg import Connection

COOKIE = "seam_session"


def ttl() -> timedelta:
    return timedelta(days=int(os.getenv("SESSION_TTL_DAYS") or 30))


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def create(conn: Connection, user_id: UUID) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)", (_hash(token), user_id, ttl()))
    return token


def lookup(conn: Connection, token: str) -> dict | None:
    """User row plus `slid`: true when expiry was extended and the cookie should be reissued."""
    row = conn.execute(
        "SELECT users.id, users.email, users.name, sessions.expires_at < now() + %s AS slid, "
        "sessions.last_used < now() - interval '1 minute' AS stale "
        "FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = %s AND sessions.expires_at > now()",
        (ttl() / 2, _hash(token)),
    ).fetchone()
    if row and row["slid"]:
        conn.execute("UPDATE sessions SET expires_at = now() + %s, last_used = now() WHERE token_hash = %s", (ttl(), _hash(token)))
    elif row and row["stale"]:
        conn.execute("UPDATE sessions SET last_used = now() WHERE token_hash = %s", (_hash(token),))
    return row


def user_id(conn: Connection, token: str) -> UUID | None:
    row = conn.execute("SELECT user_id FROM sessions WHERE token_hash = %s AND expires_at > now()", (_hash(token),)).fetchone()
    return row["user_id"] if row else None


def delete(conn: Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_hash(token),))


def _cookie_args() -> dict:
    return {"path": "/", "httponly": True, "samesite": "lax", "secure": os.getenv("COOKIE_SECURE", "").lower() == "true"}


def set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=int(ttl().total_seconds()), **_cookie_args())


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, **_cookie_args())
