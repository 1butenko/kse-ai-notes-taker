"""The team SQL against a real PostgreSQL: set TEST_DATABASE_URL to run (it resets the public
schema of that database, so never point it at Aurora). For example, with Docker:
    docker run -d -p 5433:5432 -e POSTGRES_PASSWORD=pg postgres:16
    TEST_DATABASE_URL=postgresql://postgres:pg@localhost:5433/postgres uv run pytest -m database
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import auth, db, storage, team, users
from app.config import Settings, get_settings
from app.main import app
from app.routers import course_info
from app.routers.agent import ensure_course

URL = os.environ.get("TEST_DATABASE_URL")
SECRET = "test-secret"

pytestmark = [
    pytest.mark.database,
    pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set"),
]


def connect() -> psycopg.Connection[dict[str, Any]]:
    assert URL
    return psycopg.connect(URL, row_factory=dict_row)


@pytest.fixture(autouse=True)
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A fresh schema; S3 manifests are not written."""
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setattr(db, "connect", connect)
    monkeypatch.setattr(storage, "write_manifest", lambda course: None)
    db.apply_schema()
    yield


def sign_in(email: str, first: str = "", last: str = "") -> UUID:
    return users.upsert_from_google(f"g-{email}", email, first, last, None)["id"]


def new_course(key: str = "101", owner: UUID | None = None) -> UUID:
    with db.transaction() as conn:
        return ensure_course(conn, key, f"Course {key}", int(key), owner)["id"]


def settings(tmp_path: Path, **values: Any) -> Settings:
    return Settings(uploads_dir=tmp_path, api_auth_secret=SECRET, **values)


def members(course_uuid: UUID) -> list[tuple[str, str]]:
    with db.transaction() as conn:
        return [(m["email"], m["role"]) for m in team.members(conn, course_uuid)]


def test_schema_upgrade_makes_owners_lecturers_and_logs_old_runs_once() -> None:
    owner = sign_in("owner@kse.org.ua")
    course = new_course("101", owner)
    with db.transaction() as conn:
        # As before this change: an owner, no members, a run that was never logged.
        conn.execute("DELETE FROM course_members")
        conn.execute("DELETE FROM course_events")
        conn.execute("INSERT INTO sync_runs (course_id) VALUES (%s)", (course,))

    db.apply_schema()
    db.apply_schema()  # safe to run again

    assert members(course) == [("owner@kse.org.ua", "lecturer")]
    with db.transaction() as conn:
        logged = team.events(conn, course, 10)
    assert [(e["kind"], e["email"]) for e in logged] == [("moodle_synced", None)]


def test_upgrade_leaves_a_course_with_members_alone() -> None:
    owner = sign_in("owner@kse.org.ua")
    course = new_course("101", owner)
    db.apply_schema()  # the owner becomes the lecturer
    with db.transaction() as conn:
        team.set_lecturer(conn, course, "next@kse.org.ua", owner)
        team.remove_member(conn, course, "owner@kse.org.ua")

    db.apply_schema()  # and does not come back

    assert members(course) == [("next@kse.org.ua", "lecturer")]


def test_first_to_set_up_a_course_becomes_its_lecturer(tmp_path: Path) -> None:
    ada = sign_in("ada@kse.org.ua", "Ada", "Lovelace")
    grace = sign_in("grace@kse.org.ua")

    course_info.claim("101", "Micro", ada, settings(tmp_path))
    with pytest.raises(HTTPException) as error:
        course_info.claim("101", "Renamed by Grace", grace, settings(tmp_path))

    assert error.value.status_code == 409
    assert "already set up by Ada Lovelace" in error.value.detail
    with db.transaction() as conn:
        row = conn.execute("SELECT id, title FROM courses WHERE course_key = '101'").fetchone()
    assert row["title"] == "Micro"  # Grace's rename rolled back
    assert members(row["id"]) == [("ada@kse.org.ua", "lecturer")]


def test_members_and_admins_may_rename(tmp_path: Path) -> None:
    ada = sign_in("ada@kse.org.ua")
    ta = sign_in("ta@kse.org.ua")
    boss = sign_in("boss@kse.org.ua")
    course_info.claim("101", "Micro", ada, settings(tmp_path))
    course = new_course("101")
    with db.transaction() as conn:
        team.add_member(conn, course, "ta@kse.org.ua", "ta", ada)

    course_info.claim("101", "Micro by TA", ta, settings(tmp_path))
    course_info.claim(
        "101", "Micro by admin", boss, settings(tmp_path, platform_admins=["Boss@kse.org.ua"])
    )

    assert members(course) == [("ada@kse.org.ua", "lecturer"), ("ta@kse.org.ua", "ta")]


def test_one_lecturer_and_hand_over() -> None:
    course = new_course()
    with db.transaction() as conn:
        team.set_lecturer(conn, course, "ada@kse.org.ua", None)
        team.add_member(conn, course, "TA@kse.org.ua", "ta", None)
        with pytest.raises(team.TeamError, match="already has a lecturer"):
            team.add_member(conn, course, "x@kse.org.ua", "lecturer", None)
        with pytest.raises(team.TeamError, match="already on this course"):
            team.add_member(conn, course, "ta@kse.org.ua", "ta", None)
        with pytest.raises(team.TeamError, match="Hand the lecturer role"):
            team.remove_member(conn, course, "ada@kse.org.ua")

        previous = team.set_lecturer(conn, course, "ta@kse.org.ua", None)

    assert previous == "ada@kse.org.ua"
    assert members(course) == [("ta@kse.org.ua", "lecturer"), ("ada@kse.org.ua", "ta")]


def test_member_added_before_first_sign_in_gets_access() -> None:
    course = new_course()
    with db.transaction() as conn:
        team.add_member(conn, course, "new@kse.org.ua", "ta", None)

    user = sign_in("New@KSE.org.ua")

    assert team.course_access("101", user) == ("new@kse.org.ua", "ta")
    assert team.member_courses("new@kse.org.ua") == {"101": "ta"}
    assert team.course_access("202", user) == ("new@kse.org.ua", None)


def test_start_over_clears_members_and_keeps_the_log() -> None:
    ada = sign_in("ada@kse.org.ua")
    course = new_course("101", ada)
    with db.transaction() as conn:
        team.add_member(conn, course, "ta@kse.org.ua", "ta", ada)

    course_info.release("101", ada)

    assert members(course) == []
    assert team.course_access("101", ada) == ("ada@kse.org.ua", None)
    with db.transaction() as conn:
        assert [e["kind"] for e in team.events(conn, course, 10)] == ["course_started_over"]
        owner = conn.execute("SELECT owner_id FROM courses WHERE id = %s", (course,)).fetchone()
    assert owner["owner_id"] is None


def test_record_is_best_effort() -> None:
    team.record("999", None, "moodle_synced")  # no such course: nothing logged, no error
    new_course()
    team.record("101", None, "moodle_synced", {"run_id": "r1"})

    with db.transaction() as conn:
        logged = team.events(conn, team.course_id(conn, "101"), 10)
    assert [(e["kind"], e["details"]) for e in logged] == [("moodle_synced", {"run_id": "r1"})]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: settings(tmp_path)
    yield TestClient(app)
    app.dependency_overrides.pop(get_settings, None)


def bearer(user: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.sign_token(SECRET, str(user))}"}


def test_lecturer_adds_a_ta_who_then_works_on_the_course(client: TestClient) -> None:
    ada = sign_in("ada@kse.org.ua", "Ada", "Lovelace")
    response = client.put("/course-info/101", json={"name": "Micro"}, headers=bearer(ada))
    assert response.status_code == 200

    added = client.post("/team/101/members", json={"email": "ta@kse.org.ua"}, headers=bearer(ada))
    assert added.status_code == 201
    assert [(m["email"], m["role"], m["signed_in"]) for m in added.json()["members"]] == [
        ("ada@kse.org.ua", "lecturer", True),
        ("ta@kse.org.ua", "ta", False),
    ]

    ta = sign_in("ta@kse.org.ua", "Taras", "K")
    listed = client.get("/course-info", headers=bearer(ta)).json()
    assert [(c["course"], c["role"]) for c in listed] == [("101", "ta")]
    assert client.get("/team/101", headers=bearer(ta)).json()["my_role"] == "ta"
    refused = client.post("/team/101/members", json={"email": "x@kse.org.ua"}, headers=bearer(ta))
    assert refused.status_code == 403
    assert client.delete("/course-info/101", headers=bearer(ta)).status_code == 403

    handed = client.put("/team/101/lecturer", json={"email": "ta@kse.org.ua"}, headers=bearer(ada))
    assert handed.json()["my_role"] == "ta"

    activity = client.get("/team/101/activity", headers=bearer(ta)).json()
    assert [(e["kind"], e["actor_name"]) for e in activity] == [
        ("lecturer_changed", "Ada Lovelace"),
        ("member_added", "Ada Lovelace"),
    ]
    assert activity[0]["details"] == {"email": "ta@kse.org.ua", "previous": "ada@kse.org.ua"}


def test_outsider_cannot_see_the_team(client: TestClient) -> None:
    ada = sign_in("ada@kse.org.ua")
    other = sign_in("other@kse.org.ua")
    client.put("/course-info/101", json={"name": "Micro"}, headers=bearer(ada))

    assert client.get("/team/101", headers=bearer(other)).status_code == 404
    assert client.get("/team/101/activity", headers=bearer(other)).status_code == 404
    assert client.get("/course-info", headers=bearer(other)).json() == []


def test_admin_gives_an_ownerless_course_a_lecturer(client: TestClient, tmp_path: Path) -> None:
    boss = sign_in("boss@kse.org.ua")
    (tmp_path / "101").mkdir()
    (tmp_path / "101" / "course.json").write_text(
        json.dumps({"course": "101", "name": "Old", "created_at": "2026-10-01T00:00:00+00:00"})
    )
    app.dependency_overrides[get_settings] = lambda: settings(
        tmp_path, platform_admins=["boss@kse.org.ua"]
    )

    listed = client.get("/course-info", headers=bearer(boss)).json()
    assert [(c["course"], c["role"]) for c in listed] == [("101", "admin")]
    response = client.put(
        "/team/101/lecturer", json={"email": "ada@kse.org.ua"}, headers=bearer(boss)
    )

    assert response.status_code == 200
    assert [(m["email"], m["role"]) for m in response.json()["members"]] == [
        ("ada@kse.org.ua", "lecturer")
    ]
