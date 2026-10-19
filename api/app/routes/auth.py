from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from seam_shared import db

from app.auth import passwords, ratelimit, sessions
from app.auth.deps import User, current_user

router = APIRouter()


class FieldError(HTTPException):
    """Auth-only error; the app's handler adds `field` to the ApiError body."""

    def __init__(self, status: int, detail: str, field: str | None = None):
        super().__init__(status, detail)
        self.field = field


class SignupBody(BaseModel):
    name: str = Field(max_length=1024)
    email: str = Field(max_length=1024)
    password: str = Field(max_length=1024)


class LoginBody(BaseModel):
    email: str = Field(max_length=1024)
    password: str = Field(max_length=1024)


def _limit(action: str, request: Request, email: str) -> None:
    ip = request.client.host if request.client else "unknown"
    with db.pool().connection() as conn:
        if ratelimit.blocked(conn, [f"{action}:ip:{ip}", f"{action}:email:{email.strip().lower()}"]):
            raise FieldError(429, "too many tries. wait a few minutes.", "email")


def _email(raw: str) -> str:
    if not raw.strip():
        raise FieldError(422, "fill this in.", "email")
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise FieldError(422, "that email doesn't look right.", "email")


def _start(conn, user_id, response: Response) -> None:
    sessions.set_cookie(response, sessions.create(conn, user_id))


@router.post("/auth/signup", status_code=201, response_model=User)
def signup(body: SignupBody, request: Request, response: Response) -> User:
    _limit("signup", request, body.email)
    name = body.name.strip()
    if not name:
        raise FieldError(422, "fill this in.", "name")
    if len(name) > 80:
        raise FieldError(422, "80 characters max.", "name")
    email = _email(body.email)
    if len(body.password) < 8:
        raise FieldError(422, "8 or more characters.", "password")
    if len(body.password) > 256:
        raise FieldError(422, "256 characters max.", "password")
    password_hash = passwords.hash_password(body.password)
    with db.pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s) ON CONFLICT (email) DO NOTHING RETURNING id",
            (email, name, password_hash),
        ).fetchone()
        if not row:
            raise FieldError(409, "that email already has an account.", "email")
        _start(conn, row["id"], response)
    return User(id=row["id"], email=email, name=name)


@router.post("/auth/login", response_model=User)
def login(body: LoginBody, request: Request, response: Response) -> User:
    _limit("login", request, body.email)
    with db.pool().connection() as conn:
        row = conn.execute("SELECT id, email, name, password_hash FROM users WHERE email = %s", (body.email.strip(),)).fetchone()
    if not passwords.verify(row["password_hash"] if row else None, body.password):
        raise FieldError(401, "wrong email or password.", "password")
    rehash = passwords.hash_password(body.password) if passwords.needs_rehash(row["password_hash"]) else None
    with db.pool().connection() as conn:
        if rehash:
            conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (rehash, row["id"]))
        _start(conn, row["id"], response)
    return User(id=row["id"], email=row["email"], name=row["name"])


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    if token := request.cookies.get(sessions.COOKIE):
        with db.pool().connection() as conn:
            sessions.delete(conn, token)
    sessions.clear_cookie(response)


@router.get("/auth/me", response_model=User)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/auth/check", status_code=204)
def check(request: Request, response: Response) -> None:
    token = request.cookies.get(sessions.COOKIE)
    user_id = None
    if token:
        with db.pool().connection() as conn:
            user_id = sessions.user_id(conn, token)
    if user_id is None:
        raise HTTPException(401, "log in first.")
    response.headers["X-User-Id"] = str(user_id)
