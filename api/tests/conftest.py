import os

os.environ.setdefault("MOODLE_URL", "https://moodle.test")
os.environ.setdefault("MOODLE_TOKEN", "test-token")

from collections.abc import AsyncIterator, Callable, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx2  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.moodle import MoodleClient, get_moodle_client  # noqa: E402

Handler = Callable[[httpx2.Request], httpx2.Response]


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
def tmp_uploads(tmp_path: Path) -> Iterator[Path]:
    settings = Settings(uploads_dir=tmp_path)
    app.dependency_overrides[get_settings] = lambda: settings
    yield tmp_path
    app.dependency_overrides.clear()
