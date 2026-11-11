"""The lecture-notes routes: start a run on the worker, poll it, cancel it, serve its page.

Postgres and S3 are replaced by the router's seams (`begin`, `get_run`, `list_runs`,
`storage.get_object`) and the worker's `runs.execute_run` by a recorder.
"""

# ruff: noqa: F811

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.course import CourseInfo, save_info
from app.main import app
from app.note_taker.lecture_notes import runs
from app.routers import lecture_notes
from app.worker import main as worker_main
from app.worker.config import WorkerSettings, get_worker_settings
from app.worker.main import app as worker_app
from tests.courses import course as make_course

NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


@pytest.fixture
def course(tmp_uploads: Path) -> str:
    make_course(tmp_uploads)
    save_info(tmp_uploads / "1", CourseInfo(course="1", name="Algebra", created_at=NOW.isoformat()))
    return "1"


@pytest.fixture
def worker_key(tmp_uploads: Path) -> None:
    settings = WorkerSettings(uploads_dir=tmp_uploads, openrouter_api_key="or-key")
    worker_app.dependency_overrides[get_worker_settings] = lambda: settings


def run_row(status: str = "running", **extra: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "course_id": uuid4(),
        "session_id": "s1",
        "session_label": "Week 1: Linear systems",
        "status": status,
        "step": None,
        "todos": [],
        "actions": [],
        "report": None,
        "error": None,
        "s3_prefix": None,
        "files": [],
        "readings_fingerprint": "",
        "model": None,
        "prompt_versions": {},
        "langfuse_trace_id": None,
        "renders": 0,
        "started_at": NOW,
        "finished_at": None,
        **extra,
    }


def test_start_records_a_run_and_the_worker_executes_it(
    course: str, worker_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = run_row()
    course_id = uuid4()
    began, executed = {}, []

    def begin(course_key, title, session_id, label, fingerprint):
        began.update(course=course_key, title=title, session=session_id, label=label)
        return {"id": course_id}, run

    monkeypatch.setattr(lecture_notes, "begin", begin)
    monkeypatch.setattr(runs, "execute_run", lambda *args: executed.append(args))

    response = TestClient(app).post(f"/lecture-notes/{course}/s1/runs")

    assert response.status_code == 202, response.text
    assert response.json()["id"] == str(run["id"])
    assert began == {
        "course": "1",
        "title": "Algebra",
        "session": "s1",
        "label": "Week 1: Linear systems",
    }
    assert executed == [(run["id"], course_id, "1", "s1")]
    assert worker_main.LECTURE_NOTES == set()


def test_start_refuses_unknown_lectures_and_live_runs(
    course: str, worker_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(app)
    assert client.post(f"/lecture-notes/{course}/nope/runs").status_code == 404
    assert client.post("/lecture-notes/9/s1/runs").status_code == 404

    monkeypatch.setattr(lecture_notes, "begin", lambda *args: ({"id": uuid4()}, None))
    response = client.post(f"/lecture-notes/{course}/s1/runs")
    assert response.status_code == 409 and "being written" in response.json()["detail"]


def test_start_without_readings(course: str, tmp_uploads: Path) -> None:
    from app.plan import load_plan, save_plan

    plan = load_plan(tmp_uploads / "1")
    plan.sessions[1].files = []
    save_plan(tmp_uploads / "1", plan)
    response = TestClient(app).post(f"/lecture-notes/{course}/s2/runs")
    assert response.status_code == 409 and "readings" in response.json()["detail"]


def test_worker_failure_is_recorded(course: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # No OpenRouter key on the worker: it answers 503, and the run is marked failed.
    worker_app.dependency_overrides[get_worker_settings] = lambda: WorkerSettings(
        openrouter_api_key=None
    )
    run = run_row()
    finished = {}
    monkeypatch.setattr(lecture_notes, "begin", lambda *args: ({"id": uuid4()}, run))
    monkeypatch.setattr(
        runs, "finish_run", lambda run_id, status, **kw: finished.update(status=status, **kw)
    )

    response = TestClient(app).post(f"/lecture-notes/{course}/s1/runs")

    assert response.status_code == 503
    assert finished["status"] == "failed" and "OPENROUTER_API_KEY" in finished["error"]


def test_list_flags_runs_whose_readings_changed(
    course: str, tmp_uploads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.plan import load_plan, session_fingerprint

    current = session_fingerprint(load_plan(tmp_uploads / "1"), "s1")
    rows = [
        run_row(readings_fingerprint="old"),
        run_row(readings_fingerprint=current),
        run_row(readings_fingerprint=""),
    ]
    monkeypatch.setattr(lecture_notes, "list_runs", lambda course, session: rows)

    response = TestClient(app).get(f"/lecture-notes/{course}/s1/runs")

    assert response.status_code == 200
    assert [r["readings_changed"] for r in response.json()] == [True, False, False]


def test_cancel_reaches_the_worker_or_marks_a_lost_run(
    worker_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    row = run_row()
    monkeypatch.setattr(lecture_notes, "get_run", lambda run_id: row)
    event = threading.Event()
    monkeypatch.setitem(runs.CANCEL, row["id"], event)

    assert TestClient(app).post(f"/lecture-notes/runs/{row['id']}/cancel").status_code == 200
    assert event.is_set()

    lost = run_row()
    finished = {}
    monkeypatch.setattr(lecture_notes, "get_run", lambda run_id: lost)
    monkeypatch.setattr(
        runs, "finish_run", lambda run_id, status, **kw: finished.update(status=status)
    )
    TestClient(app).post(f"/lecture-notes/runs/{lost['id']}/cancel")
    assert finished == {"status": "cancelled"}


class Body:
    def __init__(self, data: bytes) -> None:
        self.stream = io.BytesIO(data)

    def iter_chunks(self):
        yield self.stream.read()


def test_site_serves_only_published_files_in_a_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = run_row(
        "succeeded", s3_prefix="courses/x/lecture-notes/s1/r/", files=["index.html", "a.js"]
    )
    monkeypatch.setattr(lecture_notes, "get_run", lambda run_id: row)
    keys = []

    def get_object(key: str) -> dict:
        keys.append(key)
        kind = "text/html" if key.endswith(".html") else "text/javascript"
        return {"Body": Body(b"<html>notes</html>"), "ContentType": kind}

    monkeypatch.setattr("app.storage.get_object", get_object)
    client = TestClient(app)

    page = client.get(f"/lecture-notes/runs/{row['id']}/site/index.html")
    assert page.status_code == 200 and page.text == "<html>notes</html>"
    policy = page.headers["content-security-policy"]
    assert policy.startswith("sandbox allow-scripts") and "'unsafe-eval'" in policy
    assert "default-src 'none'" in policy and "https://cdn.jsdelivr.net/npm/" in policy
    assert page.headers["access-control-allow-origin"] == "*"
    assert "x-book-published" not in page.headers
    assert keys == ["courses/x/lecture-notes/s1/r/index.html"]

    script = client.get(f"/lecture-notes/runs/{row['id']}/site/a.js")
    assert "content-security-policy" not in script.headers

    assert client.get(f"/lecture-notes/runs/{row['id']}/site/secret.txt").status_code == 404
    assert client.get(f"/lecture-notes/runs/{row['id']}/site/../x").status_code == 404


def test_site_of_an_unfinished_run_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    row = run_row("running", files=["index.html"])
    monkeypatch.setattr(lecture_notes, "get_run", lambda run_id: row)
    assert (
        TestClient(app).get(f"/lecture-notes/runs/{row['id']}/site/index.html").status_code == 404
    )


def test_site_missing_object_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    row = run_row("succeeded", s3_prefix="p/", files=["index.html"])
    monkeypatch.setattr(lecture_notes, "get_run", lambda run_id: row)

    def missing(key: str) -> dict:
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr("app.storage.get_object", missing)
    assert (
        TestClient(app).get(f"/lecture-notes/runs/{row['id']}/site/index.html").status_code == 404
    )


def test_course_status_gives_each_lecture_its_latest_and_published_run(
    course: str, tmp_uploads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.plan import load_plan, session_fingerprint

    current = session_fingerprint(load_plan(tmp_uploads / "1"), "s1")
    failed = run_row("failed", readings_fingerprint=current)
    ready = run_row("succeeded", readings_fingerprint="old")
    writing = run_row("running", session_id="s2")
    monkeypatch.setattr(lecture_notes, "latest_runs", lambda course: ([failed, writing], [ready]))

    response = TestClient(app).get(f"/lecture-notes/{course}/runs")

    assert response.status_code == 200
    by_session = {item["session_id"]: item for item in response.json()}
    assert by_session["s1"]["latest"]["status"] == "failed"
    assert by_session["s1"]["published"]["id"] == str(ready["id"])
    assert by_session["s1"]["published"]["readings_changed"] is True
    assert by_session["s2"]["published"] is None
    assert TestClient(app).get("/lecture-notes/9/runs").status_code == 404
