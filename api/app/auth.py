"""Who is calling, and whether they may touch a course.

Teachers sign in with Google in the web app (Auth.js, KSE accounts only). The web's
`/api/*` route handler forwards their calls here with a short-lived HS256 token signed with
`API_AUTH_SECRET`: `sub` is the user's id (`users.id`). The worker signs its own calls with the
same secret and `sub = "worker"`; so does the web when it records a user at sign-in.

Who may work on a course (`course_role`):
- its members (`course_members`, app/team.py): one lecturer and any number of TAs;
- admins (`PLATFORM_ADMINS`), with a lecturer's rights on every course;
- everyone signed in, as an admin, when `OPEN_COURSE_ACCESS` is on (test environments);
- services (the worker, the web), on every course.

TAs do everything on a course except manage its members and start it over (`require="lecturer"`).
A course the caller may not see is answered with 404, so its existence is not revealed.
"""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, Header, HTTPException, Query, status
from pydantic import BaseModel

from app import db, team
from app.config import Settings, get_settings

ISSUER = "kse-web"
AUDIENCE = "kse-api"
SERVICES = {"worker", "web"}
# Clock difference allowed between the web, the worker and the API.
LEEWAY_SECONDS = 30
TOKEN_SECONDS = 60


class Principal(BaseModel):
    kind: Literal["user", "service"]
    id: str

    @property
    def user_id(self) -> UUID:
        if self.kind != "user":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a signed-in teacher can do this")
        return UUID(self.id)


class InvalidToken(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_token(secret: str, subject: str, seconds: int = TOKEN_SECONDS) -> str:
    """An HS256 JWT for `subject`, as the web and the worker make them."""
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": subject, "iat": now, "exp": now + seconds}
    payload = _b64(json.dumps(claims).encode())
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256)
    return f"{header}.{payload}.{_b64(signature.digest())}"


def verify_token(secret: str, token: str) -> str:
    """The token's subject. Raises InvalidToken unless it is an unexpired HS256 token signed
    with `secret` for this API."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_unb64(header_b64))
        expected = hmac.new(
            secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256
        ).digest()
        signature = _unb64(signature_b64)
    except (ValueError, TypeError) as error:
        raise InvalidToken("Malformed token") from error
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise InvalidToken("Unsupported token algorithm")
    if not hmac.compare_digest(expected, signature):
        raise InvalidToken("Bad token signature")
    try:
        claims = json.loads(_unb64(payload_b64))
    except ValueError as error:
        raise InvalidToken("Malformed token") from error
    if not isinstance(claims, dict):
        raise InvalidToken("Malformed token")
    if claims.get("iss") != ISSUER or claims.get("aud") != AUDIENCE:
        raise InvalidToken("Token is not for this API")
    exp = claims.get("exp")
    if not isinstance(exp, int | float) or exp + LEEWAY_SECONDS < time.time():
        raise InvalidToken("Token expired")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise InvalidToken("Token has no subject")
    return subject


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def current_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if not settings.api_auth_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "API_AUTH_SECRET is not set; see .env.example"
        )
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized("Sign in first")
    try:
        subject = verify_token(settings.api_auth_secret, token.strip())
    except InvalidToken as error:
        raise unauthorized(str(error)) from error
    if subject in SERVICES:
        return Principal(kind="service", id=subject)
    try:
        UUID(subject)
    except ValueError as error:
        raise unauthorized("Unknown token subject") from error
    return Principal(kind="user", id=subject)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


@contextmanager
def storage_unavailable() -> Iterator[None]:
    """The ownership check needs Aurora: say so instead of a 500 when it is unreachable."""
    try:
        yield
    except db.DatabaseNotConfigured as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    except psycopg.OperationalError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The database is unreachable"
        ) from error


# The caller's role on a course: a member's role, "admin", or None (no access).
Role = Literal["lecturer", "ta", "admin"]


def course_access(course: str, user_id: UUID) -> tuple[str | None, team.MemberRole | None]:
    """The user's email and their membership role; the database seam tests replace."""
    return team.course_access(course, user_id)


def run_course(run_id: UUID) -> str | None:
    """The course key of a lecture-notes run."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT c.course_key FROM lecture_note_runs r JOIN courses c ON c.id = r.course_id"
            " WHERE r.id = %s",
            (run_id,),
        ).fetchone()
    return row["course_key"] if row else None


def course_role(principal: Principal, course: str, settings: Settings) -> Role | None:
    if principal.kind == "service" or settings.open_course_access:
        return "admin"
    with storage_unavailable():
        email, role = course_access(course, principal.user_id)
    if role == "lecturer":
        return role
    if settings.is_admin(email):
        return "admin"
    return role


def authorize_course(
    principal: Principal,
    course: str,
    settings: Settings,
    require: Literal["ta", "lecturer"] = "ta",
) -> Role:
    """The caller's role. 404 without access; 403 for a TA where a lecturer is required."""
    role = course_role(principal, course, settings)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    if require == "lecturer" and role == "ta":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the course's lecturer or an admin can do this"
        )
    return role


def path_course(path: str) -> str:
    """A stored file's path starts with its course key (`<course>/<category>/<name>`)."""
    return path.replace("\\", "/").lstrip("/").split("/")[0]


def authorize_path(principal: Principal, path: str, settings: Settings) -> None:
    authorize_course(principal, path_course(path), settings)


AppSettings = Annotated[Settings, Depends(get_settings)]


def owned_course(course: str, principal: CurrentPrincipal, settings: AppSettings) -> str:
    """Dependency for routes with a `{course}` path parameter: any member, an admin or a
    service may work on it."""
    authorize_course(principal, course, settings)
    return course


def lectured_course(course: str, principal: CurrentPrincipal, settings: AppSettings) -> str:
    """Dependency for what only the lecturer or an admin may do."""
    authorize_course(principal, course, settings, require="lecturer")
    return course


def owned_path(
    path: Annotated[str, Query()], principal: CurrentPrincipal, settings: AppSettings
) -> str:
    """Dependency for routes with a `?path=` of a stored file."""
    authorize_path(principal, path, settings)
    return path


def owned_run(run_id: UUID, principal: CurrentPrincipal, settings: AppSettings) -> UUID:
    """Dependency for routes with a `{run_id}` of a lecture-notes run."""
    if principal.kind == "service":
        return run_id
    with storage_unavailable():
        course = run_course(run_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    authorize_course(principal, course, settings)
    return run_id


def actor(principal: Principal) -> UUID | None:
    """Who the activity log names: the user, or None for a service."""
    return UUID(principal.id) if principal.kind == "user" else None


OwnedCourse = Annotated[str, Depends(owned_course)]
