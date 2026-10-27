"""Lecture notes: one run per lecture, scoped to that session's readings."""

# ruff: noqa: F401, F811

import json
from pathlib import Path

import httpx2
import pytest

from app.config import Settings
from app.notes import Inputs
from app.plan import UnknownSession, load_plan, scope_to_session, session_fingerprint
from app.routers.plans import reading_paths
from app.syllabus import Transcript
from tests.test_notes import PLAN, course, model_stub, no_quarto, topic

LECTURE_PLAN = {
    "title": "Vector spaces",
    "sections": [
        {
            "title": "Vector spaces",
            "topics": [topic("T1", "Vector spaces", [0], [0], ["vector", "space", "basis"])],
        }
    ],
    "notation": [{"symbol": "$V$", "meaning": "a vector space"}],
    "terminology": [{"term": "basis", "definition": "independent spanning set"}],
    "conventions": [],
}


def lecture_stub(plan: dict | None = None):
    """The notes stub, planning one lecture's section; records every prompt by schema."""
    stub, calls = model_stub()
    prompts: list[tuple[str, str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        name = body["response_format"]["json_schema"]["name"]
        prompt = json.dumps(body["messages"], ensure_ascii=False)
        prompts.append((name, prompt))
        if name == "course_plan":
            answer = plan or (LECTURE_PLAN if "one lecture" in prompt else PLAN)
            return httpx2.Response(
                200,
                json={
                    "model": body["model"],
                    "choices": [{"message": {"content": json.dumps(answer)}}],
                },
            )
        return stub(request)

    return handler, calls, prompts


def transcript_of(root: Path) -> Transcript:
    return Transcript.model_validate_json((root / "1/syllabus/s.pdf.transcript.json").read_text())


# Scope


def test_scope_keeps_one_session_and_what_its_excerpts_need(tmp_path: Path) -> None:
    course(tmp_path)
    plan, transcript = load_plan(tmp_path / "1"), transcript_of(tmp_path)

    one, syllabus = scope_to_session(plan, transcript, "s1")

    assert [s.id for s in one.sessions] == ["s1"]
    assert [s.label for s in syllabus.sessions] == ["Week 1"]
    assert [p.id for p in one.proposals] == ["p1"]
    assert [b.file for b in one.books] == ["1/reading/book.pdf"]
    assert one.unassigned == [] and one.primary == plan.primary
    assert syllabus.language == "en"

    two, syllabus = scope_to_session(plan, transcript, "s2")
    assert [s.files for s in two.sessions] == [["1/reading/handout.md"]]
    assert two.proposals == [] and two.books == []
    assert [s.topic for s in syllabus.sessions] == ["Vector spaces"]

    with pytest.raises(UnknownSession):
        scope_to_session(plan, transcript, "nope")


def test_session_fingerprint_follows_files_and_excerpt_pages(tmp_path: Path) -> None:
    course(tmp_path)
    plan = load_plan(tmp_path / "1")
    before = session_fingerprint(plan, "s1")
    other = session_fingerprint(plan, "s2")

    # The excerpt is cut again from other pages under the same file name.
    plan.proposals[0].pdf_end = 3
    assert session_fingerprint(plan, "s1") != before
    assert session_fingerprint(plan, "s2") == other

    plan.proposals[0].pdf_end = 2
    plan.sessions[0].files.append("1/reading/extra.md")
    assert session_fingerprint(plan, "s1") != before
    plan.sessions[0].files.pop()
    assert session_fingerprint(plan, "s1") == before


# Lecture runs


def test_lecture_run_reads_only_its_own_sources(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    handler, _, prompts = lecture_stub()
    client = mock_openrouter(handler)
    view = client.get("/plans/1").json()

    response = client.post("/plans/1/sessions/s2/notes")

    assert response.status_code == 202, response.text
    body = response.json()
    run = body["run"]
    assert run["status"] == "done", run
    assert (run["session_id"], run["session_label"]) == ("s2", "Week 2")
    assert run["materials"] == view["sessions"][1]["materials"]
    assert run["materials"] != view["materials"]
    folder = no_quarto / "1/notes" / run["id"]
    inputs = Inputs.model_validate_json((folder / "inputs.json").read_text())
    assert [s.file for s in inputs.sources] == ["1/reading/handout.md"]
    assert [s.sessions for s in inputs.sources] == [[0]]
    assert all(c.file == "1/reading/handout.md" for c in inputs.chunks)
    assert body["topic_sessions"] == {"T1": [0]}
    assert body["document"]["title"] == "Vector spaces"

    # The planner sees this lecture alone, with the rule for its sections.
    planner = next(p for name, p in prompts if name == "course_plan")
    assert "1 to 4 topics" in planner
    assert "Vector spaces" in planner and "Linear systems" not in planner
    assert "Gaussian elimination" not in json.dumps([p for _, p in prompts])


def test_lecture_plan_over_four_topics_is_sent_back(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    many = json.loads(json.dumps(LECTURE_PLAN))
    many["sections"][0]["topics"] = [
        topic(f"T{i}", f"Part {i}", [0], [0], ["vector"]) for i in range(1, 6)
    ]
    handler, _, prompts = lecture_stub(many)
    run = mock_openrouter(handler).post("/plans/1/sessions/s2/notes").json()["run"]

    assert [name for name, _ in prompts].count("course_plan") == 3
    assert any("blocking issues after 3 rounds" in w for w in run["warnings"])
    review = json.loads((no_quarto / "1/notes" / run["id"] / "plan/review-1.json").read_text())
    assert any("1 to 4 topics" in i["detail"] for i in review["issues"])


def test_whole_course_runs_are_planned_without_the_lecture_rule(
    mock_openrouter, no_quarto: Path
) -> None:
    course(no_quarto)
    handler, _, prompts = lecture_stub()
    run = mock_openrouter(handler).post("/plans/1/notes").json()["run"]

    assert run["status"] == "done"
    assert run["session_id"] is None and run["session_label"] is None
    assert all("1 to 4 topics" not in p for name, p in prompts if name == "course_plan")


def test_lecture_run_preconditions(mock_openrouter, no_quarto: Path) -> None:
    handler, _, _ = lecture_stub()
    client = mock_openrouter(handler)
    assert client.post("/plans/1/sessions/s2/notes").status_code == 409

    course(no_quarto)
    assert client.post("/plans/1/sessions/nope/notes").status_code == 404
    plan = json.loads((no_quarto / "1/plan.json").read_text())
    plan["sessions"][1]["files"] = []
    (no_quarto / "1/plan.json").write_text(json.dumps(plan))
    response = client.post("/plans/1/sessions/s2/notes")
    assert response.status_code == 409
    assert "readings" in response.json()["detail"]


def test_lecture_run_resumes_only_from_its_lecture(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    handler, calls, _ = lecture_stub()
    client = mock_openrouter(handler)
    run = client.post("/plans/1/sessions/s2/notes").json()["run"]
    folder = no_quarto / "1/notes" / run["id"]
    stored = json.loads((folder / "run.json").read_text())
    (folder / "run.json").write_text(json.dumps(stored | {"status": "failed"}))

    other = client.post("/plans/1/sessions/s1/notes", json={"resume": run["id"]})
    assert other.status_code == 409
    legacy = client.post("/plans/1/notes", json={"resume": run["id"]})
    assert legacy.status_code == 409

    calls.clear()
    again = client.post("/plans/1/sessions/s2/notes", json={"resume": run["id"]}).json()["run"]
    assert again["id"] == run["id"] and again["status"] == "done"
    assert again["session_id"] == "s2"
    assert "course_plan" not in [c[0] for c in calls]


# Lecture-only files


def upload_lecture_file(client, session_id: str, name: str, data: bytes):
    return client.post(
        f"/plans/1/sessions/{session_id}/lecture-files",
        files=[("files", (name, data, "text/markdown"))],
    )


def test_lecture_file_is_stored_attached_and_flagged(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])

    response = upload_lecture_file(client, "s2", "slides.md", b"# Slides\nInner products.")

    assert response.status_code == 200, response.text
    sessions = {s["id"]: s for s in response.json()["sessions"]}
    files = {f["path"]: f["lecture_only"] for f in sessions["s2"]["files"]}
    assert files == {"1/reading/handout.md": False, "1/lecture/s2/slides.md": True}
    assert (no_quarto / "1/lecture/s2/slides.md").read_bytes() == b"# Slides\nInner products."
    assert all(not f["lecture_only"] for f in sessions["s1"]["files"])
    assert upload_lecture_file(client, "nope", "x.md", b"x").status_code == 404


def test_lecture_file_stays_out_of_readings_matching_and_other_lectures(
    mock_openrouter, no_quarto: Path
) -> None:
    course(no_quarto)
    handler, _, _ = lecture_stub()
    client = mock_openrouter(handler)
    upload_lecture_file(client, "s2", "slides.md", b"# Slides\nInner products are bilinear.")
    path = "1/lecture/s2/slides.md"

    assert path not in [f["path"] for f in client.get("/uploads/1").json()["reading"]]
    assert path not in reading_paths(Settings(uploads_dir=no_quarto), "1")
    assert client.post("/plans/1/sessions/s1/files", json={"path": path}).status_code == 400

    other = client.post("/plans/1/sessions/s1/notes").json()["run"]
    inputs = Inputs.model_validate_json(
        (no_quarto / "1/notes" / other["id"] / "inputs.json").read_text()
    )
    assert path not in [s.file for s in inputs.sources]

    own = client.post("/plans/1/sessions/s2/notes").json()["run"]
    inputs = Inputs.model_validate_json(
        (no_quarto / "1/notes" / own["id"] / "inputs.json").read_text()
    )
    assert [s.file for s in inputs.sources] == ["1/reading/handout.md", path]


def test_detaching_a_lecture_file_deletes_it(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])
    before = client.get("/plans/1").json()["sessions"][1]["materials"]
    after = upload_lecture_file(client, "s2", "slides.md", b"x").json()["sessions"][1]
    assert after["materials"] != before

    path = after["files"][1]["path"]
    response = client.delete("/plans/1/sessions/s2/files", params={"path": path})

    assert response.status_code == 200
    assert [f["path"] for f in response.json()["sessions"][1]["files"]] == ["1/reading/handout.md"]
    assert response.json()["sessions"][1]["materials"] == before
    assert not (no_quarto / "1/lecture/s2/slides.md").exists()
    assert (no_quarto / "1/reading/handout.md").is_file()


def test_lecture_file_opens_in_the_viewer(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])
    upload_lecture_file(client, "s2", "slides.md", b"# Slides")

    response = client.get("/files", params={"path": "1/lecture/s2/slides.md"})

    assert response.status_code == 200 and response.content == b"# Slides"
