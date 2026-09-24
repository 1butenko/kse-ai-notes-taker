from collections.abc import AsyncIterator, Callable, Iterator

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.moodle import MoodleClient, get_moodle_client

SITE_INFO = {
    "userid": 42,
    "username": "lecturer",
    "fullname": "Test Lecturer",
    "sitename": "KSE Teaching",
    "siteurl": "https://teaching.kse.org.ua",
    "release": "4.5",
    "downloadfiles": 1,
    "functions": [{"name": "core_course_get_contents", "version": "2024100700"}],
}


@pytest.fixture
def mock_moodle() -> Iterator[Callable[[Callable[[httpx2.Request], httpx2.Response]], TestClient]]:
    def install(handler: Callable[[httpx2.Request], httpx2.Response]) -> TestClient:
        async def override() -> AsyncIterator[MoodleClient]:
            async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
                yield MoodleClient("https://moodle.test", http)

        app.dependency_overrides[get_moodle_client] = override
        return TestClient(app)

    yield install
    app.dependency_overrides.clear()


def test_connect_returns_site_info(mock_moodle) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx2.Response(200, json=SITE_INFO)

    response = mock_moodle(handler).post("/courses/connect", json={"token": "abc123"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "connected",
        "fullname": "Test Lecturer",
        "username": "lecturer",
        "sitename": "KSE Teaching",
        "release": "4.5",
        "downloadfiles": True,
        "missing_functions": [],
    }
    assert seen["url"] == "https://moodle.test/webservice/rest/server.php"
    assert "wstoken=abc123" in seen["body"]
    assert "wsfunction=core_webservice_get_site_info" in seen["body"]
    assert "moodlewsrestformat=json" in seen["body"]


def test_connect_reports_missing_functions(mock_moodle) -> None:
    info = {**SITE_INFO, "downloadfiles": 0, "functions": []}
    client = mock_moodle(lambda _: httpx2.Response(200, json=info))

    body = client.post("/courses/connect", json={"token": "abc123"}).json()

    assert body["downloadfiles"] is False
    assert body["missing_functions"] == ["core_course_get_contents"]


def test_connect_rejects_invalid_token(mock_moodle) -> None:
    error = {"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "x"}
    client = mock_moodle(lambda _: httpx2.Response(200, json=error))

    response = client.post("/courses/connect", json={"token": "bad"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid Moodle token"}


def test_connect_reports_other_moodle_errors(mock_moodle) -> None:
    error = {"exception": "moodle_exception", "errorcode": "accessexception", "message": "x"}
    client = mock_moodle(lambda _: httpx2.Response(200, json=error))

    response = client.post("/courses/connect", json={"token": "abc123"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Moodle error: accessexception"}


def test_connect_reports_unreachable_moodle(mock_moodle) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom", request=request)

    response = mock_moodle(handler).post("/courses/connect", json={"token": "abc123"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Moodle is unreachable"}


def test_connect_rejects_empty_token() -> None:
    response = TestClient(app).post("/courses/connect", json={"token": ""})
    assert response.status_code == 422


def test_connect_allows_web_origin() -> None:
    response = TestClient(app).options(
        "/courses/connect",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
