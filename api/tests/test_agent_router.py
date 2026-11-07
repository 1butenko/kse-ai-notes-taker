"""The AI Note Taker routes: the API records a run and the worker executes it.

Postgres and S3 are replaced by the router's own seams (`begin_run`, `course_detail`), and the
worker's `sync.execute_run` by a recorder, so no AWS, database or model is touched.
"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import db
from app.course import CourseInfo, save_info
from app.main import app
from app.note_taker import sync
from app.routers import agent
from app.worker.config import WorkerSettings, get_worker_settings
from app.worker.main import app as worker_app

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


@pytest.fixture
def course(tmp_uploads: Path) -> str:
    save_info(
        tmp_uploads / "4510",
        CourseInfo(course="4510", name="Linear Algebra", created_at=NOW.isoformat()),
    )
    return "4510"


@pytest.fixture
def worker_key(tmp_uploads: Path) -> None:
    settings = WorkerSettings(uploads_dir=tmp_uploads, openrouter_api_key="or-key")
    worker_app.dependency_overrides[get_worker_settings] = lambda: settings


def run_row(course_id, status="running", **extra):
    return {
        "id": uuid4(),
        "course_id": course_id,
        "focus": None,
        "status": status,
        "report": None,
        "error": None,
        "started_at": NOW,
        "finished_at": None,
        **extra,
    }


def test_sync_records_a_run_and_the_worker_executes_it(
    course: str, worker_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = uuid4()
    run = run_row(course_id, focus="eigenvalues")
    linked = {}
    executed = []

    def begin_run(course_key, title, moodle_id, focus):
        linked.update(course_key=course_key, title=title, moodle_id=moodle_id, focus=focus)
        return {"id": course_id, "title": title, "created_at": NOW, "inserted": True}, run

    monkeypatch.setattr(agent, "begin_run", begin_run)
    monkeypatch.setattr(sync, "execute_run", lambda *args: executed.append(args))

    response = TestClient(app).post(f"/agent/courses/{course}/sync", json={"focus": "eigenvalues"})

    assert response.status_code == 202
    assert response.json()["id"] == str(run["id"])
    assert linked == {
        "course_key": "4510",
        "title": "Linear Algebra",
        "moodle_id": 4510,
        "focus": "eigenvalues",
    }
    assert executed == [(run["id"], course_id, 4510, "eigenvalues")]


def test_worker_without_openrouter_fails_the_run(
    course: str, tmp_uploads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = WorkerSettings(uploads_dir=tmp_uploads, openrouter_api_key=None)
    worker_app.dependency_overrides[get_worker_settings] = lambda: settings
    course_id = uuid4()
    run = run_row(course_id)
    finished = []
    monkeypatch.setattr(agent, "begin_run", lambda *_: ({"id": course_id, "inserted": False}, run))
    monkeypatch.setattr(sync, "finish_run", lambda run_id, **kw: finished.append((run_id, kw)))

    response = TestClient(app).post(f"/agent/courses/{course}/sync", json={})

    assert response.status_code == 503
    error = "Worker: OPENROUTER_API_KEY is not set on the worker"
    assert finished == [(run["id"], {"error": error})]


def test_a_live_run_is_a_conflict(course: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "begin_run", lambda *_: ({"id": uuid4()}, None))
    response = TestClient(app).post(f"/agent/courses/{course}/sync", json={})
    assert response.status_code == 409


def test_sync_needs_a_moodle_course_and_its_info(tmp_uploads: Path) -> None:
    client = TestClient(app)
    assert client.post("/agent/courses/local/sync", json={}).status_code == 409
    assert client.post("/agent/courses/999/sync", json={}).status_code == 404


def test_missing_database_is_a_503(course: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def not_configured(*_):
        raise db.DatabaseNotConfigured("DB_HOST is not set; see .env.example")

    monkeypatch.setattr(agent, "begin_run", not_configured)
    monkeypatch.setattr(agent, "course_detail", not_configured)
    client = TestClient(app)
    for response in (
        client.post(f"/agent/courses/{course}/sync", json={}),
        client.get(f"/agent/courses/{course}"),
    ):
        assert response.status_code == 503
        assert response.json()["detail"] == "DB_HOST is not set; see .env.example"


def test_get_is_404_before_the_first_run(course: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "course_detail", lambda _: None)
    assert TestClient(app).get(f"/agent/courses/{course}").status_code == 404


def test_get_returns_topics_materials_and_the_latest_run(
    course: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = uuid4()
    material = uuid4()
    topics = agent.build_topics(
        [{"section": 1, "name": "Matrices", "summary": "Week 1"}],
        [
            {
                "id": material,
                "section": 1,
                "section_name": "Matrices",
                "name": "slides.pdf",
                "mimetype": "application/pdf",
                "size": 2048,
                "s3_key": f"courses/{course_id}/materials/x/slides.pdf",
                "reason": "Lecture slides",
            },
            {
                "id": uuid4(),
                "section": 3,
                "section_name": "Unsaved section",
                "name": "notes.pdf",
                "mimetype": "application/pdf",
                "size": 10,
                "s3_key": "k",
                "reason": "",
            },
        ],
        lambda key: f"https://s3.test/{key}",
    )
    detail = {
        "id": course_id,
        "course_key": course,
        "title": "Linear Algebra",
        "s3_prefix": f"courses/{course_id}/",
        "created_at": NOW,
        "moodle_course_id": 4510,
        "materials": 2,
        "topics": topics,
        "latest_run": run_row(course_id, status="succeeded", report="Fetched 2 files"),
    }
    monkeypatch.setattr(agent, "course_detail", lambda _: detail)

    body = TestClient(app).get(f"/agent/courses/{course}").json()

    assert [t["name"] for t in body["topics"]] == ["Matrices", "Unsaved section"]
    first = body["topics"][0]["materials"][0]
    assert first["url"] == f"https://s3.test/courses/{course_id}/materials/x/slides.pdf"
    assert body["latest_run"]["report"] == "Fetched 2 files"
