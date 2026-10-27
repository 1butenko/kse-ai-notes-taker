import json

from fastapi.testclient import TestClient

from app.main import app
from tests.test_plans import put


def test_put_creates_then_updates_and_keeps_created_at(tmp_uploads) -> None:
    client = TestClient(app)

    created = client.put("/course-info/7", json={"name": "  Linear Algebra  "})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["course"] == "7" and body["name"] == "Linear Algebra"
    assert body["created_at"]
    assert json.loads((tmp_uploads / "7/course.json").read_text()) == body

    updated = client.put("/course-info/7", json={"name": "Linear Algebra II"}).json()
    assert updated == {**body, "name": "Linear Algebra II"}
    assert client.get("/course-info/7").json() == updated


def test_put_validates_the_name(tmp_uploads) -> None:
    client = TestClient(app)

    for name in ("", "   ", "x" * 201):
        assert client.put("/course-info/7", json={"name": name}).status_code == 422, name
    assert client.put("/course-info/7", json={}).status_code == 422
    assert client.put("/course-info/7", json={"name": "x" * 200}).status_code == 200


def test_get_one_and_list_newest_first(tmp_uploads) -> None:
    client = TestClient(app)
    assert client.get("/course-info").json() == []
    assert client.get("/course-info/7").status_code == 404

    for course, name, created in (
        ("1", "Old", "2026-01-01T00:00:00+00:00"),
        ("local", "New", "2026-03-01T00:00:00+00:00"),
        ("2", "Middle", "2026-02-01T00:00:00+00:00"),
    ):
        put(
            tmp_uploads,
            f"{course}/course.json",
            json.dumps({"course": course, "name": name, "created_at": created}).encode(),
        )
    # Course directories without course.json, or with an unreadable one, are not listed.
    put(tmp_uploads, "3/plan.json", b"{}")
    put(tmp_uploads, "4/course.json", b"{not json")
    put(tmp_uploads, "other/course.json", b'{"course": "other", "name": "x", "created_at": "z"}')

    listed = client.get("/course-info").json()
    assert [(c["course"], c["name"]) for c in listed] == [
        ("local", "New"),
        ("2", "Middle"),
        ("1", "Old"),
    ]
    assert client.get("/course-info/2").json() == listed[1]
    assert client.get("/course-info/3").status_code == 404
    assert client.get("/course-info/4").status_code == 404


def test_invalid_course_keys_are_rejected(tmp_uploads) -> None:
    client = TestClient(app)

    assert client.get("/course-info/abc").status_code == 400
    assert client.put("/course-info/abc", json={"name": "X"}).status_code == 400
    assert client.delete("/course-info/abc").status_code == 400
    assert client.put("/course-info/..", json={"name": "X"}).status_code in (400, 404, 405)
    assert not (tmp_uploads / "abc").exists()


def test_delete_moves_the_whole_course_directory_to_the_trash(tmp_uploads) -> None:
    client = TestClient(app)
    client.put("/course-info/7", json={"name": "Linear Algebra"})
    for path in (
        "7/syllabus/s.pdf",
        "7/syllabus/s.pdf.transcript.json",
        "7/reading/book.pdf",
        "7/plan.json",
        "7/notes/20261001-000000-abcd/run.json",
    ):
        put(tmp_uploads, path)
    put(tmp_uploads, "8/plan.json")

    assert client.delete("/course-info/7").status_code == 204
    assert not (tmp_uploads / "7").exists()
    assert (tmp_uploads / "8/plan.json").is_file()
    # Start over can be undone by hand: the folder waits in the trash, whole.
    (trashed,) = (tmp_uploads / ".trash").iterdir()
    assert trashed.name.startswith("7-")
    assert (trashed / "reading/book.pdf").is_file()
    assert (trashed / "notes/20261001-000000-abcd/run.json").is_file()
    assert client.get("/course-info/7").status_code == 404
    assert client.get("/course-info").json() == []
    # Deleting again is harmless.
    assert client.delete("/course-info/7").status_code == 204


def run_json(run: str, status: str) -> bytes:
    return json.dumps(
        {
            "id": run,
            "course": "7",
            "status": status,
            "stage": status,
            "created_at": "2026-10-01T00:00:00+00:00",
            "updated_at": "2026-10-01T00:00:00+00:00",
            "models": {},
        }
    ).encode()


def test_delete_is_refused_while_notes_are_generating(tmp_uploads) -> None:
    client = TestClient(app)
    client.put("/course-info/7", json={"name": "Linear Algebra"})
    put(
        tmp_uploads,
        "7/notes/20261001-000000-aaaa/run.json",
        run_json("20261001-000000-aaaa", "done"),
    )

    for status in ("queued", "running"):
        put(
            tmp_uploads,
            "7/notes/20261002-000000-bbbb/run.json",
            run_json("20261002-000000-bbbb", status),
        )
        refused = client.delete("/course-info/7")
        assert refused.status_code == 409, status
        assert "generat" in refused.json()["detail"].lower()
        assert (tmp_uploads / "7/course.json").is_file()
        assert not (tmp_uploads / ".trash").exists()

    put(
        tmp_uploads,
        "7/notes/20261002-000000-bbbb/run.json",
        run_json("20261002-000000-bbbb", "failed"),
    )
    assert client.delete("/course-info/7").status_code == 204
