import os

os.environ.setdefault("MOODLE_URL", "https://moodle.test")
os.environ.setdefault("MOODLE_TOKEN", "test-token")

from collections.abc import AsyncIterator, Callable, Iterator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx2  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.moodle import MoodleClient, get_moodle_client  # noqa: E402
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

    async def override() -> AsyncIterator[WorkerClient]:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=worker_app)) as http:
            yield WorkerClient("http://worker.test", http)

    app.dependency_overrides[get_worker_client] = override
    # No model unless a test installs one: the real key in .env must never be used.
    worker_app.dependency_overrides[get_openrouter_opener] = lambda: None
    yield
    app.dependency_overrides.pop(get_worker_client, None)
    worker_app.dependency_overrides.clear()


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
