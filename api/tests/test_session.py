import os
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.session import SessionMiddleware, end_session, session_dir, sweep

ROOT = Path("/uploads")


def client(enabled: bool) -> TestClient:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, enabled=enabled)

    @app.get("/dir")
    def directory() -> str:
        return session_dir(ROOT).as_posix()

    return TestClient(app)


def test_requests_are_scoped_to_their_session() -> None:
    demo = client(enabled=True)
    assert demo.get("/dir", headers={"x-session": "tab-12345678"}).json() == "/uploads/tab-12345678"
    assert demo.get("/dir?session=tab-87654321").json() == "/uploads/tab-87654321"


def test_missing_or_unsafe_sessions_get_a_fresh_workspace() -> None:
    demo = client(enabled=True)
    first, second = demo.get("/dir").json(), demo.get("/dir").json()
    assert first != second and first.startswith("/uploads/")
    assert demo.get("/dir", headers={"x-session": "../../etc"}).json() != "/uploads/../../etc"


def test_without_sessions_the_root_is_shared() -> None:
    shared = client(enabled=False).get("/dir", headers={"x-session": "tab-12345678"})
    assert shared.json() == "/uploads"


def test_ended_and_idle_sessions_are_deleted(tmp_path: Path) -> None:
    for name in ["ended-12345678", "idle-12345678", "active-12345678"]:
        (tmp_path / name / "1").mkdir(parents=True)
    end_session(tmp_path, "ended-12345678")
    old = time.time() - 3600
    os.utime(tmp_path / "idle-12345678", (old, old))
    sweep(tmp_path, ttl=600)
    assert [p.name for p in tmp_path.iterdir()] == ["active-12345678"]
