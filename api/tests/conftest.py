import os

os.environ.setdefault("MOODLE_URL", "https://moodle.test")
os.environ.setdefault("MOODLE_TOKEN", "test-token")

from collections.abc import AsyncIterator, Callable, Iterator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402
from uuid import UUID  # noqa: E402

import httpx2  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db, prompts, team, users  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.moodle import MoodleClient, get_moodle_client  # noqa: E402
from app.routers import course_info  # noqa: E402
from app.worker.config import WorkerSettings, get_worker_settings  # noqa: E402
from app.worker.main import app as worker_app  # noqa: E402
from app.worker.openrouter import (  # noqa: E402
    OpenRouterClient,
    get_openrouter_client,
    get_openrouter_opener,
)
from app.worker_client import WorkerClient, get_worker_client  # noqa: E402

Handler = Callable[[httpx2.Request], httpx2.Response]


@pytest.fixture(autouse=True)
def in_process_worker() -> Iterator[None]:
    """The API reaches the worker over ASGI, inside the test process."""

    async def override(principal: auth.CurrentPrincipal) -> AsyncIterator[WorkerClient]:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=worker_app)) as http:
            yield WorkerClient("http://worker.test", http, principal.id)

    app.dependency_overrides[get_worker_client] = override
    # No model unless a test installs one: the real key in .env must never be used.
    worker_app.dependency_overrides[get_openrouter_opener] = lambda: None
    yield
    app.dependency_overrides.pop(get_worker_client, None)
    worker_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_database(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never reach the real Aurora, even when DB_HOST is set (as in the Docker containers): the
    worker's startup would mark live runs failed. Tests replace the routers' seams instead;
    tests marked `database` use TEST_DATABASE_URL (tests/test_team_db.py)."""
    if request.node.get_closest_marker("database"):
        return

    def refuse():
        raise db.DatabaseNotConfigured("Tests do not use the database")

    monkeypatch.setattr(db, "connect", refuse)


TEST_USER = UUID("00000000-0000-4000-8000-000000000001")
TEST_EMAIL = "teacher@kse.org.ua"


@pytest.fixture(autouse=True)
def signed_in(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Calls come from a signed-in teacher who lectures every course; tests/test_auth.py and
    tests/test_team.py check the real tokens and roles. The database seams stand in for Aurora."""
    if request.node.get_closest_marker("database"):
        yield
        return
    app.dependency_overrides[auth.current_principal] = lambda: auth.Principal(
        kind="user", id=str(TEST_USER)
    )
    monkeypatch.setattr(auth, "course_access", lambda course, user_id: (TEST_EMAIL, "lecturer"))
    monkeypatch.setattr(auth, "run_course", lambda run_id: "local")
    monkeypatch.setattr(course_info, "claim", lambda course, name, user_id, settings: None)
    monkeypatch.setattr(course_info, "release", lambda course, user_id: None)
    monkeypatch.setattr(users, "get_user", lambda user_id: {"id": user_id, "email": TEST_EMAIL})

    def every_course(email: str) -> dict[str, str]:
        root = app.dependency_overrides.get(get_settings, get_settings)().uploads_dir
        return {d.name: "lecturer" for d in root.iterdir() if d.is_dir()} if root.is_dir() else {}

    monkeypatch.setattr(team, "member_courses", every_course)
    yield
    app.dependency_overrides.pop(auth.current_principal, None)


@pytest.fixture(autouse=True)
def no_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load prompts from the local Markdown files, even when Langfuse keys are in .env."""
    monkeypatch.setattr(prompts, "langfuse_client", lambda: None)


@pytest.fixture
def mock_moodle() -> Iterator[Callable[[Handler], TestClient]]:
    def install(handler: Handler) -> TestClient:
        async def override() -> AsyncIterator[MoodleClient]:
            async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
                yield MoodleClient("https://moodle.test", http)

        app.dependency_overrides[get_moodle_client] = override
        return TestClient(app)

    yield install
    app.dependency_overrides.clear()


@pytest.fixture
def mock_openrouter() -> Iterator[Callable[[Handler], TestClient]]:
    def install(handler: Handler) -> TestClient:
        @asynccontextmanager
        async def opener() -> AsyncIterator[OpenRouterClient]:
            async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
                yield OpenRouterClient(
                    "https://openrouter.test/api/v1", "or-key", "test/model", http
                )

        async def override() -> AsyncIterator[OpenRouterClient]:
            async with opener() as client:
                yield client

        worker_app.dependency_overrides[get_openrouter_client] = override
        worker_app.dependency_overrides[get_openrouter_opener] = lambda: opener
        return TestClient(app)

    yield install


@pytest.fixture
def tmp_uploads(tmp_path: Path) -> Iterator[Path]:
    settings = Settings(uploads_dir=tmp_path)
    worker_settings = WorkerSettings(uploads_dir=tmp_path)
    app.dependency_overrides[get_settings] = lambda: settings
    worker_app.dependency_overrides[get_worker_settings] = lambda: worker_settings
    yield tmp_path
    app.dependency_overrides.pop(get_settings, None)
    worker_app.dependency_overrides.pop(get_worker_settings, None)
