import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.plan import Plan, PlanSession, sync
from app.syllabus import Session, Transcript
from tests.test_syllabus import EXTRACTION, completion


def session(label: str, number: int | None = None) -> Session:
    return Session(
        label=label,
        number=number,
        date=None,
        topic=f"Topic of {label}",
        subtopics=[],
        required_readings=[],
        optional_readings=[],
    )


def transcript(*sessions: Session, path: str = "1/syllabus/s.pdf") -> Transcript:
    return Transcript(
        language="en",
        learning_materials=[],
        sessions=list(sessions),
        notes=None,
        source_path=path,
        source_sha256="x",
        model="test/model",
        created_at="2026-09-29T00:00:00+00:00",
    )


def put(root: Path, path: str, data: bytes = b"%PDF") -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)


def put_transcript(root: Path, t: Transcript) -> None:
    put(root, t.source_path)
    (root / f"{t.source_path}.transcript.json").write_text(t.model_dump_json())


def put_plan(root: Path, course: str, plan: Plan) -> None:
    (root / course).mkdir(parents=True, exist_ok=True)
    (root / course / "plan.json").write_text(plan.model_dump_json())


# sync


def test_sync_assigns_ids_and_is_idempotent() -> None:
    plan = Plan()
    t = transcript(session("Week 1", 1), session("Week 2", 2))

    assert sync(plan, t) is True
    ids = [s.id for s in plan.sessions]
    assert len(set(ids)) == 2

    assert sync(plan, t) is False
    assert [s.id for s in plan.sessions] == ids


def test_sync_keeps_files_by_label_then_number_and_frees_leftovers() -> None:
    plan = Plan(
        sessions=[
            PlanSession(id="a", label="Week 1", number=1, files=["1/reading/a.pdf"]),
            PlanSession(id="b", label="Week 2", number=2, files=["1/reading/b.pdf"]),
            PlanSession(id="c", label="Week 3", number=3, files=["1/reading/c.pdf"]),
        ]
    )
    t = transcript(session("week  2", 2), session("Lecture 1", 1), session("Week 4", 4))

    assert sync(plan, t) is True
    by_label = {s.label: s for s in plan.sessions}
    assert by_label["week  2"].id == "b"  # same label, whitespace and case ignored
    assert by_label["Lecture 1"].id == "a"  # renamed, matched by number
    assert by_label["Week 4"].files == []
    assert plan.unassigned == ["1/reading/c.pdf"]


def test_sync_duplicate_labels_match_in_order() -> None:
    plan = Plan(
        sessions=[
            PlanSession(id="a", label="Seminar", number=None, files=["1/reading/a.pdf"]),
            PlanSession(id="b", label="Seminar", number=None, files=["1/reading/b.pdf"]),
        ]
    )
    sync(plan, transcript(session("Seminar"), session("Seminar")))
    assert [s.id for s in plan.sessions] == ["a", "b"]


# API


def test_first_transcript_becomes_primary_plan(mock_openrouter, tmp_uploads) -> None:
    put(tmp_uploads, "1/syllabus/first.pdf")
    put(tmp_uploads, "1/syllabus/second.pdf")
    client = mock_openrouter(lambda _: completion(json.dumps(EXTRACTION)))

    client.post("/syllabus/transcribe", json={"path": "1/syllabus/first.pdf"})
    client.post("/syllabus/transcribe", json={"path": "1/syllabus/second.pdf"})

    plan = client.get("/plans/1").json()
    assert plan["primary"] == "1/syllabus/first.pdf"
    assert [s["session"]["label"] for s in plan["sessions"]] == ["Week 1"]

    switched = client.put("/plans/1/primary", json={"path": "1/syllabus/second.pdf"}).json()
    assert switched["primary"] == "1/syllabus/second.pdf"


def test_empty_plan(tmp_uploads) -> None:
    response = TestClient(app).get("/plans/local")
    assert response.status_code == 200
    assert response.json() == {
        "course": "local",
        "primary": None,
        "transcript": None,
        "sessions": [],
        "unassigned": [],
        "books": [],
        "mapped": False,
    }
    assert TestClient(app).get("/plans/..").status_code in (400, 404)
    assert TestClient(app).get("/plans/abc").status_code == 400


def test_primary_requires_transcript(tmp_uploads) -> None:
    put(tmp_uploads, "1/syllabus/s.pdf")
    response = TestClient(app).put("/plans/1/primary", json={"path": "1/syllabus/s.pdf"})
    assert response.status_code == 409

    put_transcript(tmp_uploads, transcript(session("Week 1"), path="2/syllabus/s.pdf"))
    response = TestClient(app).put("/plans/1/primary", json={"path": "2/syllabus/s.pdf"})
    assert response.status_code == 400


def test_attach_detach_and_share_file(tmp_uploads) -> None:
    put_transcript(tmp_uploads, transcript(session("Week 1", 1), session("Week 2", 2)))
    put_plan(tmp_uploads, "1", Plan(primary="1/syllabus/s.pdf"))
    put(tmp_uploads, "1/reading/book.pdf", b"book")
    client = TestClient(app)

    week1, week2 = [s["id"] for s in client.get("/plans/1").json()["sessions"]]
    body = {"path": "1/reading/book.pdf"}
    client.post(f"/plans/1/sessions/{week1}/files", json=body)
    plan = client.post(f"/plans/1/sessions/{week2}/files", json=body).json()

    assert [f["path"] for s in plan["sessions"] for f in s["files"]] == [
        "1/reading/book.pdf",
        "1/reading/book.pdf",
    ]
    assert plan["sessions"][0]["files"][0]["size"] == 4

    plan = client.delete(
        f"/plans/1/sessions/{week1}/files", params={"path": "1/reading/book.pdf"}
    ).json()
    assert plan["sessions"][0]["files"] == []
    assert len(plan["sessions"][1]["files"]) == 1
    assert (tmp_uploads / "1/reading/book.pdf").exists()


def test_attach_rejects_foreign_files_and_unknown_session(tmp_uploads) -> None:
    put_transcript(tmp_uploads, transcript(session("Week 1", 1)))
    put_plan(tmp_uploads, "1", Plan(primary="1/syllabus/s.pdf"))
    put(tmp_uploads, "2/reading/other.pdf")
    client = TestClient(app)
    week1 = client.get("/plans/1").json()["sessions"][0]["id"]

    def attach(session_id: str, path: str) -> int:
        url = f"/plans/1/sessions/{session_id}/files"
        return client.post(url, json={"path": path}).status_code

    assert attach(week1, "2/reading/other.pdf") == 400
    assert attach(week1, "1/syllabus/s.pdf") == 400
    assert attach(week1, "../../etc/passwd") == 400
    assert attach(week1, "1/reading/missing.pdf") == 404
    assert attach("nope", "1/reading/missing.pdf") == 404


def test_retranscription_moves_orphaned_files_to_unassigned(tmp_uploads) -> None:
    put_transcript(tmp_uploads, transcript(session("Week 1", 1), session("Week 2", 2)))
    put_plan(tmp_uploads, "1", Plan(primary="1/syllabus/s.pdf"))
    put(tmp_uploads, "1/reading/b.pdf")
    client = TestClient(app)
    week2 = client.get("/plans/1").json()["sessions"][1]["id"]
    client.post(f"/plans/1/sessions/{week2}/files", json={"path": "1/reading/b.pdf"})

    put_transcript(tmp_uploads, transcript(session("Week 1", 1)))
    plan = client.get("/plans/1").json()
    assert [f["path"] for f in plan["unassigned"]] == ["1/reading/b.pdf"]

    week1 = plan["sessions"][0]["id"]
    plan = client.post(f"/plans/1/sessions/{week1}/files", json={"path": "1/reading/b.pdf"}).json()
    assert plan["unassigned"] == []

    put_transcript(tmp_uploads, transcript(session("Other")))
    client.get("/plans/1")
    plan = client.delete("/plans/1/unassigned", params={"path": "1/reading/b.pdf"}).json()
    assert plan["unassigned"] == []


def test_list_course_files_skips_transcripts(tmp_uploads) -> None:
    put_transcript(tmp_uploads, transcript(session("Week 1")))
    put(tmp_uploads, "1/reading/a.pdf", b"aa")

    response = TestClient(app).get("/uploads/1")

    assert response.json() == {
        "syllabus": [{"path": "1/syllabus/s.pdf", "size": 4}],
        "reading": [{"path": "1/reading/a.pdf", "size": 2}],
    }
    assert TestClient(app).get("/uploads/9").json() == {"syllabus": [], "reading": []}


def test_delete_syllabus_removes_file_and_transcript(tmp_uploads) -> None:
    put_transcript(tmp_uploads, transcript(session("Week 1"), path="1/syllabus/other.pdf"))
    put(tmp_uploads, "1/syllabus/old.doc")
    client = TestClient(app)

    assert client.delete("/syllabus", params={"path": "1/syllabus/old.doc"}).status_code == 204
    assert client.delete("/syllabus", params={"path": "1/syllabus/other.pdf"}).status_code == 204
    assert not any((tmp_uploads / "1/syllabus").iterdir())

    assert client.delete("/syllabus", params={"path": "1/syllabus/gone.pdf"}).status_code == 404
    assert client.delete("/syllabus", params={"path": "../../etc/passwd"}).status_code == 400
    put(tmp_uploads, "1/reading/book.pdf")
    assert client.delete("/syllabus", params={"path": "1/reading/book.pdf"}).status_code == 400


def test_delete_primary_syllabus_frees_its_files(tmp_uploads) -> None:
    put_transcript(tmp_uploads, transcript(session("Week 1", 1)))
    put_plan(tmp_uploads, "1", Plan(primary="1/syllabus/s.pdf"))
    put(tmp_uploads, "1/reading/book.pdf")
    client = TestClient(app)
    week1 = client.get("/plans/1").json()["sessions"][0]["id"]
    client.post(f"/plans/1/sessions/{week1}/files", json={"path": "1/reading/book.pdf"})

    assert client.delete("/syllabus", params={"path": "1/syllabus/s.pdf"}).status_code == 204

    plan = client.get("/plans/1").json()
    assert plan["primary"] is None
    assert plan["sessions"] == []
    assert [f["path"] for f in plan["unassigned"]] == ["1/reading/book.pdf"]
    assert (tmp_uploads / "1/reading/book.pdf").exists()
