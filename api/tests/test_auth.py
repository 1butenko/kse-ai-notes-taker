import base64
import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth, team, users
from app.config import Settings, get_settings
from app.main import app
from app.routers import course_info

SECRET = "test-secret"
OWNER = UUID("00000000-0000-4000-8000-000000000001")
OTHER = UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def real_auth(tmp_path: Path) -> Iterator[TestClient]:
    """The real token check, with API_AUTH_SECRET set (the autouse fixture signs everyone in)."""
    app.dependency_overrides.pop(auth.current_principal, None)
    settings = Settings(uploads_dir=tmp_path, api_auth_secret=SECRET)
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(get_settings, None)


def bearer(subject: str, secret: str = SECRET, seconds: int = 60) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.sign_token(secret, subject, seconds)}"}


def forged(claims: dict, alg: str = "HS256") -> str:
    def b64(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{b64({'alg': alg, 'typ': 'JWT'})}.{b64(claims)}.c2ln"


def test_signed_token_round_trips() -> None:
    assert auth.verify_token(SECRET, auth.sign_token(SECRET, "worker")) == "worker"


@pytest.mark.parametrize(
    ("token", "message"),
    [
        (auth.sign_token("other-secret", "worker"), "signature"),
        (auth.sign_token(SECRET, "worker", seconds=-120), "expired"),
        ("not-a-token", "Malformed"),
        (forged({"sub": "worker"}, alg="none"), "algorithm"),
    ],
)
def test_bad_tokens_are_refused(token: str, message: str) -> None:
    with pytest.raises(auth.InvalidToken, match=message):
        auth.verify_token(SECRET, token)


def test_token_for_another_audience_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "AUDIENCE", "someone-else")
    token = auth.sign_token(SECRET, "worker")
    monkeypatch.setattr(auth, "AUDIENCE", "kse-api")
    with pytest.raises(auth.InvalidToken, match="not for this API"):
        auth.verify_token(SECRET, token)


def test_calls_without_a_token_are_refused(real_auth: TestClient) -> None:
    assert real_auth.get("/course-info").status_code == 401
    assert real_auth.get("/plans/local").status_code == 401
    assert real_auth.get("/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_health_needs_no_token(real_auth: TestClient) -> None:
    assert real_auth.get("/health").status_code == 200


def test_missing_secret_is_a_configuration_error(tmp_path: Path) -> None:
    app.dependency_overrides.pop(auth.current_principal, None)
    app.dependency_overrides[get_settings] = lambda: Settings(uploads_dir=tmp_path)
    try:
        response = TestClient(app).get("/course-info", headers=bearer(str(OWNER)))
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert response.status_code == 503


def test_teacher_sees_only_their_courses(
    real_auth: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for key, name in (("101", "Mine"), ("202", "Theirs")):
        (tmp_path / key).mkdir()
        (tmp_path / key / "course.json").write_text(
            json.dumps({"course": key, "name": name, "created_at": "2026-11-01T00:00:00+00:00"})
        )
    monkeypatch.setattr(
        users, "get_user", lambda user_id: {"email": "me@kse.org.ua" if user_id == OWNER else "x"}
    )
    monkeypatch.setattr(
        team, "member_courses", lambda email: {"101": "ta"} if email == "me@kse.org.ua" else {}
    )

    response = real_auth.get("/course-info", headers=bearer(str(OWNER)))

    assert response.status_code == 200
    assert [(c["name"], c["role"]) for c in response.json()] == [("Mine", "ta")]


def test_someone_elses_course_is_not_found(
    real_auth: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "course_access", lambda course, user_id: ("me@kse.org.ua", None))

    assert real_auth.get("/plans/101", headers=bearer(str(OWNER))).status_code == 404
    assert real_auth.get("/course-info/101", headers=bearer(str(OWNER))).status_code == 404
    assert real_auth.get("/team/101", headers=bearer(str(OWNER))).status_code == 404
    response = real_auth.get(
        "/files", params={"path": "101/reading/a.pdf"}, headers=bearer(str(OWNER))
    )
    assert response.status_code == 404


def test_unknown_user_has_no_course() -> None:
    principal = auth.Principal(kind="user", id=str(OWNER))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(auth, "course_access", lambda course, user_id: (None, None))
        with pytest.raises(HTTPException) as error:
            auth.authorize_course(principal, "101", Settings(uploads_dir=Path(".")))
    assert error.value.status_code == 404


def test_worker_may_touch_every_course(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_lookup(course: str, user_id: UUID) -> tuple:
        raise AssertionError("services skip the membership lookup")

    monkeypatch.setattr(auth, "course_access", no_lookup)
    role = auth.authorize_course(
        auth.Principal(kind="service", id="worker"), "101", Settings(uploads_dir=Path("."))
    )
    assert role == "admin"


def test_run_of_someone_elses_course_is_not_found(
    real_auth: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "run_course", lambda run_id: "101")
    monkeypatch.setattr(auth, "course_access", lambda course, user_id: ("me@kse.org.ua", None))

    response = real_auth.get(f"/lecture-notes/runs/{uuid4()}", headers=bearer(str(OWNER)))

    assert response.status_code == 404


def test_course_set_up_by_another_teacher_conflicts(
    real_auth: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def taken(course: str, name: str, user_id: UUID, settings: Settings) -> None:
        raise HTTPException(409, "This course is already set up by Ada Lovelace.")

    monkeypatch.setattr(course_info, "claim", taken)

    response = real_auth.put("/course-info/101", json={"name": "Micro"}, headers=bearer(str(OWNER)))

    assert response.status_code == 409
    assert "Ada Lovelace" in response.json()["detail"]
    assert not (tmp_path / "101").exists()


def user_row(user_id: UUID, first: str = "Ada", last: str = "Lovelace") -> dict:
    return {
        "id": user_id,
        "email": "ada@kse.org.ua",
        "first_name": first,
        "last_name": last,
        "avatar_url": None,
        "created_at": datetime(2026, 11, 1, tzinfo=UTC),
    }


def test_sync_is_for_the_web_only(real_auth: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users, "upsert_from_google", lambda *args: user_row(OWNER))
    body = {"google_sub": "g-1", "email": "ada@kse.org.ua", "first_name": "Ada"}

    assert real_auth.post("/auth/sync", json=body, headers=bearer(str(OWNER))).status_code == 403
    response = real_auth.post("/auth/sync", json=body, headers=bearer("web"))
    assert response.status_code == 200
    assert response.json()["id"] == str(OWNER)


def test_me_and_name_edits(real_auth: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    saved: dict = {}

    def update(user_id: UUID, first: str, last: str) -> dict:
        saved.update(first=first, last=last)
        return user_row(user_id, first, last)

    monkeypatch.setattr(users, "get_user", lambda user_id: user_row(user_id))
    monkeypatch.setattr(users, "update_names", update)
    headers = bearer(str(OWNER))

    assert real_auth.get("/me", headers=headers).json()["first_name"] == "Ada"
    response = real_auth.patch(
        "/me", json={"first_name": "  Grace ", "last_name": "Hopper"}, headers=headers
    )
    assert response.status_code == 200
    assert saved == {"first": "Grace", "last": "Hopper"}
    blank = real_auth.patch("/me", json={"first_name": " ", "last_name": "Hopper"}, headers=headers)
    assert blank.status_code == 422


def test_me_is_for_teachers_only(real_auth: TestClient) -> None:
    assert real_auth.get("/me", headers=bearer("worker")).status_code == 403


def test_published_notes_page_needs_no_token(
    real_auth: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.routers import lecture_notes

    monkeypatch.setattr(lecture_notes, "current_run", lambda run_id: None)

    response = real_auth.get(f"/lecture-notes/runs/{uuid4()}/site/index.html")

    assert response.status_code == 404  # reached the route: no 401


def test_worker_signs_its_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.note_taker.project import WorkerAuth

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler), auth=WorkerAuth(SECRET))
    client.get("http://api.test/plans/101")

    token = seen["auth"].removeprefix("Bearer ")
    assert auth.verify_token(SECRET, token) == "worker"
    assert time.time() < json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))["exp"]
