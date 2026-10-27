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


# Course notation sheet

FIRST_LECTURE_PLAN = {
    **LECTURE_PLAN,
    "title": "Linear systems",
    "sections": [
        {
            "title": "Linear systems",
            "topics": [topic("T1", "Linear systems", [0], [0], ["Gaussian", "elimination"])],
        }
    ],
    "notation": [
        {"symbol": "$V$", "meaning": "the vector of unknowns"},
        {"symbol": "$A$", "meaning": "the coefficient matrix"},
    ],
    "terminology": [
        {"term": "Basis", "definition": "a set of pivots"},
        {"term": "pivot", "definition": "leading entry of a row"},
    ],
}


def sheet(root: Path) -> dict:
    return json.loads((root / "1/notation.json").read_text())


def test_first_lecture_run_seeds_the_notation_sheet(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])
    assert client.get("/course-info/1/notation").json() == {"notation": [], "terminology": []}

    client.post("/plans/1/notes")  # A whole-course run never touches the sheet.
    assert not (no_quarto / "1/notation.json").exists()

    client.post("/plans/1/sessions/s2/notes")

    expected = {
        "notation": [{"symbol": "$V$", "meaning": "a vector space"}],
        "terminology": [{"term": "basis", "definition": "independent spanning set"}],
    }
    assert sheet(no_quarto) == expected
    assert client.get("/course-info/1/notation").json() == expected


def test_later_lecture_gets_the_sheet_and_only_appends(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])
    client.post("/plans/1/sessions/s2/notes")

    handler, _, prompts = lecture_stub(FIRST_LECTURE_PLAN)
    run = mock_openrouter(handler).post("/plans/1/sessions/s1/notes").json()["run"]

    planner = next(p for name, p in prompts if name == "course_plan")
    assert "Course notation" in planner and "a vector space" in planner
    assert sheet(no_quarto) == {
        "notation": [
            {"symbol": "$V$", "meaning": "a vector space"},
            {"symbol": "$A$", "meaning": "the coefficient matrix"},
        ],
        "terminology": [
            {"term": "basis", "definition": "independent spanning set"},
            {"term": "pivot", "definition": "leading entry of a row"},
        ],
    }
    # The lecture itself follows the sheet where they disagree.
    planned = json.loads((no_quarto / "1/notes" / run["id"] / "plan.json").read_text())
    assert planned["notation"][0] == {"symbol": "$V$", "meaning": "a vector space"}
    assert planned["terminology"][0] == {"term": "basis", "definition": "independent spanning set"}


def test_failed_lecture_run_leaves_the_sheet_alone(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    handler, _, _ = lecture_stub()

    def failing(request: httpx2.Request) -> httpx2.Response:
        if b'"consistency_edits"' in request.content:
            return httpx2.Response(500, json={"error": {"message": "boom"}})
        return handler(request)

    run = mock_openrouter(failing).post("/plans/1/sessions/s2/notes").json()["run"]

    assert run["status"] == "failed"
    assert not (no_quarto / "1/notation.json").exists()


def test_unreadable_notation_sheet_reads_as_empty(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    (no_quarto / "1/notation.json").write_text("{not json")
    client = mock_openrouter(lecture_stub()[0])

    assert client.get("/course-info/1/notation").json() == {"notation": [], "terminology": []}


# Queue and stop


def lecture_titles(prompts: list[tuple[str, str]]) -> list[str]:
    """Which lecture each planning request was for, in order."""
    found = []
    for name, prompt in prompts:
        if name == "course_plan":
            found.append("Week 1" if "S0: Week 1" in prompt else "Week 2")
    return found


def test_generate_all_queues_lectures_in_order_and_skips_ones_without_readings(
    mock_openrouter, no_quarto: Path
) -> None:
    course(no_quarto)
    handler, _, prompts = lecture_stub()
    client = mock_openrouter(handler)

    response = client.post("/plans/1/notes/queue")

    assert response.status_code == 202, response.text
    assert response.json()["skipped"] == []
    assert lecture_titles(prompts) == ["Week 1", "Week 2"]
    runs = client.get("/plans/1/notes").json()
    assert sorted((r["session_id"], r["status"]) for r in runs) == [("s1", "done"), ("s2", "done")]
    idle = client.get("/plans/1/notes/queue").json()
    assert idle == {"waiting": [], "active": None, "active_session": None, "skipped": []}
    assert not (no_quarto / "1/queue.json").exists()

    # Every lecture has its note now: nothing to queue.
    again = client.post("/plans/1/notes/queue")
    assert again.status_code == 409


def test_generate_all_skips_lectures_without_readings(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    plan = json.loads((no_quarto / "1/plan.json").read_text())
    plan["sessions"][0]["files"] = []
    (no_quarto / "1/plan.json").write_text(json.dumps(plan))
    handler, _, prompts = lecture_stub()
    client = mock_openrouter(handler)

    body = client.post("/plans/1/notes/queue").json()

    assert body["skipped"] == [{"session_id": "s1", "reason": "No readings"}]
    assert lecture_titles(prompts) == ["Week 2"]
    assert [r["session_id"] for r in client.get("/plans/1/notes").json()] == ["s2"]


def test_generate_all_resumes_an_unfinished_lecture(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    handler, calls, prompts = lecture_stub()
    client = mock_openrouter(handler)
    first = client.post("/plans/1/sessions/s2/notes").json()["run"]
    folder = no_quarto / "1/notes" / first["id"]
    stored = json.loads((folder / "run.json").read_text())
    (folder / "run.json").write_text(json.dumps(stored | {"status": "failed"}))
    prompts.clear()

    client.post("/plans/1/notes/queue")

    assert lecture_titles(prompts) == ["Week 1"]  # Week 2 reused its plan
    runs = client.get("/plans/1/notes").json()
    assert sorted((r["session_id"], r["status"]) for r in runs) == [("s1", "done"), ("s2", "done")]
    assert first["id"] in [r["id"] for r in runs]


def test_generate_all_renews_a_lecture_whose_readings_changed(
    mock_openrouter, no_quarto: Path
) -> None:
    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])
    first = client.post("/plans/1/sessions/s2/notes").json()["run"]
    folder = no_quarto / "1/notes" / first["id"]
    stored = json.loads((folder / "run.json").read_text())
    (folder / "run.json").write_text(json.dumps(stored | {"status": "failed"}))
    upload_lecture_file(client, "s2", "slides.md", b"# Slides\nMore on bases.")

    client.post("/plans/1/notes/queue")

    runs = {r["id"]: r["status"] for r in client.get("/plans/1/notes").json()}
    assert runs.pop(first["id"]) == "failed"
    assert sorted(runs.values()) == ["done", "done"]  # A new run of Week 2, and Week 1


def test_next_lecture_starts_when_one_fails(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    handler, _, _ = lecture_stub()

    def failing(request: httpx2.Request) -> httpx2.Response:
        if b"S0: Week 1" in request.content:
            return httpx2.Response(500, json={"error": {"message": "boom"}})
        return handler(request)

    client = mock_openrouter(failing)
    client.post("/plans/1/notes/queue")

    runs = {r["session_id"]: r["status"] for r in client.get("/plans/1/notes").json()}
    assert runs == {"s1": "failed", "s2": "done"}


def test_one_job_per_course(mock_openrouter, no_quarto: Path) -> None:
    from app.worker.notes import ACTIVE

    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])
    ACTIVE.add("1")
    try:
        assert client.post("/plans/1/notes/queue").status_code == 409
        assert client.post("/plans/1/sessions/s2/notes").status_code == 409
        assert client.post("/plans/1/notes").status_code == 409
    finally:
        ACTIVE.discard("1")
    assert client.get("/plans/1/notes").json() == []


TWO_TOPICS = {
    **LECTURE_PLAN,
    "sections": [
        {
            "title": "Vector spaces",
            "topics": [
                topic("T1", "Vector spaces", [0], [0], ["vector", "space"]),
                topic("T2", "Bases", [0], [0], ["basis"]),
            ],
        }
    ],
}


@pytest.mark.anyio
async def test_stop_cancels_the_lecture_clears_the_queue_and_resume_reuses_topics(
    mock_openrouter, no_quarto: Path
) -> None:
    import asyncio

    from app.worker.main import app as worker_app

    course(no_quarto)
    stub, calls, _ = lecture_stub(TWO_TOPICS)
    blocked = asyncio.Event()

    async def handler(request: httpx2.Request) -> httpx2.Response:
        hold = b"Topic T2: Bases" in request.content and b"evidence_selection" in request.content
        if hold and not blocked.is_set():
            blocked.set()
            await asyncio.Event().wait()  # Never answers: only Stop ends it.
        return stub(request)

    client = mock_openrouter(handler)
    items = [{"session_id": "s2"}, {"session_id": "s1"}]
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=worker_app), base_url="http://worker.test"
    ) as worker:
        started = asyncio.create_task(
            worker.post("/notes/lectures", json={"course": "1", "items": items})
        )
        await asyncio.wait_for(blocked.wait(), 10)
        run_id = json.loads((no_quarto / "1/queue.json").read_text())["active"]
        t1 = no_quarto / "1/notes" / run_id / "topics/T1/note.json"
        for _ in range(200):
            if t1.is_file():
                break
            await asyncio.sleep(0.01)
        waiting = json.loads((no_quarto / "1/queue.json").read_text())
        assert [i["session_id"] for i in waiting["waiting"]] == ["s1"]

        stopped = await worker.post("/notes/stop", json={"course": "1"})
        assert stopped.status_code == 200, stopped.text
        await asyncio.wait_for(started, 10)

    run = json.loads((no_quarto / "1/notes" / run_id / "run.json").read_text())
    assert run["status"] == "failed" and run["error"].startswith("Stopped")
    assert not (no_quarto / "1/queue.json").exists()
    assert [r["session_id"] for r in client.get("/plans/1/notes").json()] == ["s2"]
    finished = t1.read_bytes()

    calls.clear()
    response = await asyncio.to_thread(
        client.post, "/plans/1/sessions/s2/notes", json={"resume": run_id}
    )
    resumed = response.json()["run"]
    assert resumed["id"] == run_id and resumed["status"] == "done"
    assert t1.read_bytes() == finished
    names = [c[0] for c in calls]
    assert "course_plan" not in names and names.count("evidence_selection") == 1


def test_stop_without_a_job_is_harmless(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])

    response = client.post("/plans/1/notes/stop")

    assert response.status_code == 200
    assert response.json()["waiting"] == [] and response.json()["active"] is None


def test_restart_fails_the_active_lecture_and_drops_the_queue(
    mock_openrouter, no_quarto: Path
) -> None:
    from app.worker.lectures import drop_queues
    from app.worker.notes import fail_interrupted

    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])
    run = client.post("/plans/1/sessions/s2/notes").json()["run"]
    target = no_quarto / "1/notes" / run["id"] / "run.json"
    target.write_text(json.dumps(json.loads(target.read_text()) | {"status": "running"}))
    (no_quarto / "1/queue.json").write_text(
        json.dumps({"waiting": [{"session_id": "s1"}], "active": run["id"], "active_session": "s2"})
    )

    fail_interrupted(no_quarto)
    assert drop_queues(no_quarto) == ["1"]

    after = client.get(f"/plans/1/notes/{run['id']}").json()["run"]
    assert after["status"] == "failed" and "worker restart" in after["error"]
    assert any("1 queued lecture" in w for w in after["warnings"])
    assert not (no_quarto / "1/queue.json").exists()
    assert client.get("/plans/1/notes/queue").json()["waiting"] == []


def test_start_over_waits_for_the_queue(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    client = mock_openrouter(lecture_stub()[0])
    (no_quarto / "1/queue.json").write_text(json.dumps({"waiting": [{"session_id": "s1"}]}))

    assert client.delete("/course-info/1").status_code == 409
    (no_quarto / "1/queue.json").unlink()
    assert client.delete("/course-info/1").status_code == 204


@pytest.mark.anyio
async def test_stop_during_rendering_kills_quarto_and_publishes_nothing(
    mock_openrouter, tmp_uploads: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    import asyncio
    import os

    from app.worker.config import WorkerSettings, get_worker_settings
    from app.worker.main import app as worker_app

    bin_dir = tmp_path_factory.mktemp("bin")
    pids = bin_dir / "pids"
    script = bin_dir / "quarto"
    script.write_text(f'#!/bin/sh\necho $$ >> "{pids}"\nexec sleep 30\n')
    script.chmod(0o755)
    settings = WorkerSettings(uploads_dir=tmp_uploads, quarto_bin=str(script))
    worker_app.dependency_overrides[get_worker_settings] = lambda: settings
    course(tmp_uploads)
    client = mock_openrouter(lecture_stub()[0])

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=worker_app), base_url="http://worker.test"
    ) as worker:
        started = asyncio.create_task(
            worker.post("/notes/lectures", json={"course": "1", "items": [{"session_id": "s2"}]})
        )
        for _ in range(500):
            if pids.is_file():
                break
            await asyncio.sleep(0.01)
        assert pids.is_file(), "Quarto never started"
        run_id = json.loads((tmp_uploads / "1/queue.json").read_text())["active"]
        assert (await worker.post("/notes/stop", json={"course": "1"})).status_code == 200
        await asyncio.wait_for(started, 10)

    folder = tmp_uploads / "1/notes" / run_id
    run = json.loads((folder / "run.json").read_text())
    assert run["status"] == "failed" and run["error"].startswith("Stopped")
    for pid in map(int, pids.read_text().split()):
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    assert not list(folder.rglob(".quarto-*"))
    assert not list(folder.rglob("*.html")) and not list(folder.rglob("note.pdf"))
    view = client.get(f"/plans/1/notes/{run_id}").json()
    assert view["artifacts"] == [] and view["document"] is None
    assert not (tmp_uploads / "1/notation.json").exists()

    # Resuming renders again from scratch and finishes.
    script.write_text("#!/bin/sh\nexit 1\n")
    resumed = await asyncio.to_thread(
        client.post, "/plans/1/sessions/s2/notes", json={"resume": run_id}
    )
    assert resumed.json()["run"]["status"] == "done"
    artifacts = json.loads((folder / "artifacts.json").read_text())
    assert {a["status"] for a in artifacts} == {"failed"}
