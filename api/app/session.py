import asyncio
import re
import secrets
import shutil
import time
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

HEADER = "x-session"
SESSION = re.compile(r"^[A-Za-z0-9-]{8,64}$")

current_session: ContextVar[str | None] = ContextVar("session", default=None)
last_seen: dict[str, float] = {}


def session_dir(root: Path) -> Path:
    session = current_session.get()
    return root / session if session else root


def read_session(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name.decode() == HEADER:
            return value.decode()
    values = parse_qs(scope.get("query_string", b"").decode()).get("session")
    return values[0] if values else None


class SessionMiddleware:
    """Scopes every request to one browser tab's throwaway workspace (demo mode)."""

    def __init__(self, app: ASGIApp, enabled: bool) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        session = read_session(scope)
        if not session or not SESSION.match(session):
            session = secrets.token_hex(16)
        last_seen[session] = time.time()
        token = current_session.set(session)
        try:
            await self.app(scope, receive, send)
        finally:
            current_session.reset(token)


def end_session(root: Path, session: str) -> None:
    if SESSION.match(session):
        shutil.rmtree(root / session, ignore_errors=True)
    last_seen.pop(session, None)


def sweep(root: Path, ttl: float) -> None:
    now = time.time()
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        seen = last_seen.get(directory.name) or directory.stat().st_mtime
        if now - seen > ttl:
            end_session(root, directory.name)


async def sweep_forever(root: Path, ttl: float) -> None:
    while True:
        await asyncio.to_thread(sweep, root, ttl)
        await asyncio.sleep(600)
