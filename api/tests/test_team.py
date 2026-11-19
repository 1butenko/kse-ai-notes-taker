"""Who may do what on a course: members (lecturer, TA), admins, everyone on a test server.

The database is stubbed here (conftest); tests/test_team_db.py runs the SQL for real."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import auth, team, users
from app.config import Settings, get_settings
from app.main import app
from app.routers import team as team_router

SECRET = "test-secret"
ME = UUID("00000000-0000-4000-8000-000000000001")
MY_EMAIL = "me@kse.org.ua"
# The real one: the fixture stubs it.
REAL_CHANGE = team_router.change


def bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.sign_token(SECRET, str(ME))}"}


def write_course(root: Path, key: str, name: str) -> None:
    (root / key).mkdir()
    (root / key / "course.json").write_text(
        json.dumps({"course": key, "name": name, "created_at": "2026-11-01T00:00:00+00:00"})
    )


@pytest.fixture
def as_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """`as_role(role)`: a client signed in with real tokens, whose role on course 101 is one of
    lecturer, ta, admin (in PLATFORM_ADMINS, not a member), open (OPEN_COURSE_ACCESS) or
    outsider."""
    app.dependency_overrides.pop(auth.current_principal, None)
    write_course(tmp_path, "101", "Micro")
    # The team's rows: changes are accepted, reads return nobody.
    monkeypatch.setattr(team_router, "change", lambda settings, course, apply: None)
    monkeypatch.setattr(
        team_router,
        "read_team",
        lambda settings, course, role: team_router.Team(my_role=role, members=[]),
    )

    def install(role: str) -> TestClient:
        settings = Settings(
            uploads_dir=tmp_path,
            api_auth_secret=SECRET,
            platform_admins=[MY_EMAIL] if role == "admin" else [],
            open_course_access=role == "open",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        member = role if role in ("lecturer", "ta") else None
        monkeypatch.setattr(auth, "course_access", lambda course, user_id: (MY_EMAIL, member))
        return TestClient(app)

    yield install
    app.dependency_overrides.pop(get_settings, None)


def work(client: TestClient) -> int:
    return client.get("/course-info/101", headers=bearer()).status_code


def see_team(client: TestClient) -> int:
    return client.get("/team/101", headers=bearer()).status_code


def add_ta(client: TestClient) -> int:
    body = {"email": "ta@kse.org.ua"}
    return client.post("/team/101/members", json=body, headers=bearer()).status_code


def remove_ta(client: TestClient) -> int:
    params = {"email": "ta@kse.org.ua"}
    return client.delete("/team/101/members", params=params, headers=bearer()).status_code


def hand_over(client: TestClient) -> int:
    body = {"email": "next@kse.org.ua"}
    return client.put("/team/101/lecturer", json=body, headers=bearer()).status_code


def start_over(client: TestClient) -> int:
    return client.delete("/course-info/101", headers=bearer()).status_code


ACTIONS = [work, see_team, add_ta, remove_ta, hand_over, start_over]
ALLOWED = {work: 200, see_team: 200, add_ta: 201, remove_ta: 200, hand_over: 200, start_over: 204}
LECTURER_ONLY = {add_ta, remove_ta, hand_over, start_over}


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.__name__)
@pytest.mark.parametrize("role", ["lecturer", "admin", "open", "ta", "outsider"])
def test_role_permissions(as_role: Any, role: str, action: Any) -> None:
    client = as_role(role)

    status = action(client)

    if role == "outsider":
        assert status == 404  # someone else's course is not shown to exist
    elif role == "ta" and action in LECTURER_ONLY:
        assert status == 403
    else:
        assert status == ALLOWED[action]


@pytest.mark.parametrize("role", ["lecturer", "admin", "open", "ta"])
def test_my_role_is_reported(as_role: Any, role: str) -> None:
    expected = "admin" if role in ("admin", "open") else role

    assert as_role(role).get("/team/101", headers=bearer()).json()["my_role"] == expected


def test_admin_who_lectures_a_course_is_its_lecturer(as_role: Any) -> None:
    client = as_role("admin")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(auth, "course_access", lambda course, user_id: (MY_EMAIL, "lecturer"))
        assert client.get("/team/101", headers=bearer()).json()["my_role"] == "lecturer"


@pytest.mark.parametrize("email", ["someone@gmail.com", "kse.org.ua", "@kse.org.ua"])
def test_members_need_a_kse_email(as_role: Any, email: str) -> None:
    client = as_role("lecturer")

    response = client.post("/team/101/members", json={"email": email}, headers=bearer())

    assert response.status_code == 422


def test_member_emails_are_lowercased(as_role: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client = as_role("lecturer")
    added: list[str] = []

    class Conn:
        def execute(self, sql: str, params: tuple) -> Any:
            if sql.startswith("INSERT INTO course_members"):
                added.append(params[1])
            return self

        def fetchone(self) -> None:
            return None

    monkeypatch.setattr(
        team_router, "change", lambda settings, course, apply: apply(Conn(), UUID(int=1))
    )

    response = client.post("/team/101/members", json={"email": " TA@KSE.org.ua "}, headers=bearer())

    assert response.status_code == 201
    assert added == ["ta@kse.org.ua"]


class Transaction:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


def test_team_rule_errors_are_conflicts(as_role: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client = as_role("lecturer")
    monkeypatch.setattr(team_router, "change", REAL_CHANGE)
    monkeypatch.setattr(team_router.db, "transaction", Transaction)
    monkeypatch.setattr(team, "course_id", lambda conn, course: UUID(int=9))

    def already_there(*args: object) -> None:
        raise team.TeamError("ta@kse.org.ua is already on this course")

    monkeypatch.setattr(team, "add_member", already_there)

    response = client.post("/team/101/members", json={"email": "ta@kse.org.ua"}, headers=bearer())

    assert response.status_code == 409
    assert response.json()["detail"] == "ta@kse.org.ua is already on this course"


def test_admin_sees_every_course(
    as_role: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_course(tmp_path, "202", "Macro")
    client = as_role("admin")
    monkeypatch.setattr(users, "get_user", lambda user_id: {"email": MY_EMAIL})
    monkeypatch.setattr(team, "member_courses", lambda email: {"202": "ta"})

    listed = client.get("/course-info", headers=bearer()).json()

    assert sorted((c["course"], c["role"]) for c in listed) == [("101", "admin"), ("202", "ta")]


def test_open_access_shows_every_course(
    as_role: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_course(tmp_path, "202", "Macro")
    client = as_role("open")
    monkeypatch.setattr(users, "get_user", lambda user_id: {"email": MY_EMAIL})
    monkeypatch.setattr(team, "member_courses", lambda email: {})

    listed = client.get("/course-info", headers=bearer()).json()

    assert sorted(c["course"] for c in listed) == ["101", "202"]


def test_member_sees_only_their_courses(
    as_role: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_course(tmp_path, "202", "Macro")
    client = as_role("ta")
    monkeypatch.setattr(users, "get_user", lambda user_id: {"email": MY_EMAIL})
    monkeypatch.setattr(team, "member_courses", lambda email: {"101": "ta"})

    listed = client.get("/course-info", headers=bearer()).json()

    assert [(c["course"], c["role"]) for c in listed] == [("101", "ta")]


def test_actions_are_logged_with_who_did_them(
    as_role: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = as_role("ta")
    logged: list[tuple] = []
    monkeypatch.setattr(
        team,
        "record",
        lambda course, actor, kind, details=None: logged.append((course, actor, kind)),
    )

    assert client.post("/course-info/101/readings-approval", headers=bearer()).status_code == 200
    assert client.delete("/course-info/101/readings-approval", headers=bearer()).status_code == 200

    assert logged == [
        ("101", ME, "readings_approved"),
        ("101", ME, "readings_approval_revoked"),
    ]


def test_activity_lists_events_newest_first(as_role: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client = as_role("ta")
    at = datetime(2026, 11, 20, tzinfo=UTC)
    rows = [
        {
            "id": UUID(int=2),
            "kind": "member_added",
            "details": {"email": "ta@kse.org.ua"},
            "created_at": at,
            "email": "lead@kse.org.ua",
            "first_name": "Ada",
            "last_name": "L",
        },
        {
            "id": UUID(int=1),
            "kind": "moodle_synced",
            "details": {},
            "created_at": at,
            "email": None,
            "first_name": None,
            "last_name": None,
        },
    ]

    monkeypatch.setattr(team_router.db, "transaction", Transaction)
    monkeypatch.setattr(team, "course_id", lambda conn, course: UUID(int=9))
    monkeypatch.setattr(team, "events", lambda conn, course_uuid, limit: rows)

    events = client.get("/team/101/activity", headers=bearer()).json()

    assert [(e["kind"], e["actor_name"]) for e in events] == [
        ("member_added", "Ada L"),
        ("moodle_synced", None),
    ]
