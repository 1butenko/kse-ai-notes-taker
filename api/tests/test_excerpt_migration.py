"""Excerpts cut as PDF files before they became references: the one-off migration."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.excerpt_migration import Busy, main, migrate
from app.main import app
from app.notes import NotesRun, run_dir
from app.notes_revisions import RevisionConflict
from app.plan import load_plan, scope_to_session, session_fingerprint
from app.syllabus import Transcript
from app.worker.artifacts import RunStore
from app.worker.config import WorkerSettings
from app.worker.models import NotesModels
from app.worker.notes import mark_stopped, open_run
from tests.test_notes import course
from tests.test_plans import put

LEGACY = "1/excerpts/s1/book - Ch. 1.pdf"
RUN = "20261029-120000-abcd"


def transcript_of(root: Path) -> Transcript:
    return Transcript.model_validate_json((root / "1/syllabus/s.pdf.transcript.json").read_text())


def admit(root: Path) -> RunStore:
    """Open (or resume) lecture s1's run from the plan on disk, as the worker's queue does."""
    scoped, syllabus = scope_to_session(load_plan(root / "1"), transcript_of(root), "s1")
    models = NotesModels.from_settings(WorkerSettings(uploads_dir=root))
    return open_run(root / "1", "1", RUN, models, scoped, syllabus, "s1")


def run_of(root: Path) -> NotesRun:
    return NotesRun.model_validate_json((run_dir(root / "1", RUN) / "run.json").read_text())


def test_old_runs_stay_resumable_and_current(tmp_uploads: Path) -> None:
    course(tmp_uploads)
    mark_stopped(admit(tmp_uploads))
    inputs = (run_dir(tmp_uploads / "1", RUN) / "inputs.json").read_bytes()

    assert [r.renamed for r in migrate(tmp_uploads)] == [1]

    plan = load_plan(tmp_uploads / "1")
    assert plan.sessions[0].files == ["1/excerpts/p1"]
    assert plan.proposals[0].excerpt == "1/excerpts/p1"
    assert not (tmp_uploads / "1/excerpts").exists()
    # The lecture's note isn't flagged "readings changed", and the stopped run resumes.
    assert run_of(tmp_uploads).materials == session_fingerprint(plan, "s1")
    assert admit(tmp_uploads).run.status == "queued"
    assert (run_dir(tmp_uploads / "1", RUN) / "inputs.json").read_bytes() == inputs


def test_without_the_run_rewrite_resume_would_be_refused(tmp_uploads: Path) -> None:
    course(tmp_uploads)
    mark_stopped(admit(tmp_uploads))
    plan_file = tmp_uploads / "1/plan.json"
    plan_file.write_text(plan_file.read_text().replace(LEGACY, "1/excerpts/p1"))

    with pytest.raises(RevisionConflict):
        admit(tmp_uploads)


def test_a_run_that_was_already_stale_stays_stale(tmp_uploads: Path) -> None:
    course(tmp_uploads)
    mark_stopped(admit(tmp_uploads))
    book = tmp_uploads / "1/reading/book.pdf"
    book.write_bytes(book.read_bytes() + b"\n% edited")

    migrate(tmp_uploads)

    with pytest.raises(RevisionConflict):
        admit(tmp_uploads)


def test_excerpts_are_served_from_the_book_after_migration(tmp_uploads: Path) -> None:
    course(tmp_uploads)
    migrate(tmp_uploads)
    client = TestClient(app)

    [file] = client.get("/plans/1").json()["sessions"][0]["files"]
    assert file["path"] == "1/excerpts/p1" and file["size"] is None
    assert (file["excerpt"]["pdf_start"], file["excerpt"]["pdf_end"]) == (1, 2)
    response = client.get("/files", params={"path": file["path"]})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert len(PdfReader(io.BytesIO(response.content)).pages) == 2
    assert client.get("/files", params={"path": "1/excerpts/nope"}).status_code == 404


def test_legacy_excerpts_work_before_migration(tmp_uploads: Path) -> None:
    course(tmp_uploads)
    (tmp_uploads / LEGACY).unlink()
    client = TestClient(app)

    [file] = client.get("/plans/1").json()["sessions"][0]["files"]
    assert file["path"] == LEGACY and file["excerpt"] is not None
    response = client.get("/files", params={"path": LEGACY})
    assert len(PdfReader(io.BytesIO(response.content)).pages) == 2


def test_files_without_a_proposal_are_kept(tmp_uploads: Path) -> None:
    course(tmp_uploads)
    orphan = "1/excerpts/s2/orphan.pdf"
    put(tmp_uploads, orphan)
    put(tmp_uploads, "1/excerpts/old/stray.pdf")
    plan_file = tmp_uploads / "1/plan.json"
    plan_file.write_text(plan_file.read_text().replace('"1/reading/handout.md"', f'"{orphan}"'))

    [report] = migrate(tmp_uploads)

    assert report.kept == [orphan]
    assert report.deleted == ["1/excerpts/old/stray.pdf", LEGACY]
    excerpts = (tmp_uploads / "1/excerpts").rglob("*")
    left = sorted(p.relative_to(tmp_uploads).as_posix() for p in excerpts)
    assert left == ["1/excerpts/s2", orphan]
    assert load_plan(tmp_uploads / "1").sessions[1].files == [orphan]


def test_dry_run_changes_nothing_and_a_second_run_is_a_no_op(tmp_uploads: Path, capsys) -> None:
    course(tmp_uploads)
    mark_stopped(admit(tmp_uploads))
    before = {p: p.read_bytes() for p in tmp_uploads.rglob("*") if p.is_file()}

    assert main(["--uploads", str(tmp_uploads), "--dry-run"]) == 0
    assert "Would delete 1 excerpt files" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in tmp_uploads.rglob("*") if p.is_file()} == before

    migrate(tmp_uploads)
    after = {p: p.read_bytes() for p in tmp_uploads.rglob("*") if p.is_file()}
    [report] = migrate(tmp_uploads)
    assert (report.renamed, report.runs, report.deleted) == (0, [], [])
    assert {p: p.read_bytes() for p in tmp_uploads.rglob("*") if p.is_file()} == after


def test_refuses_while_notes_are_generating(tmp_uploads: Path) -> None:
    course(tmp_uploads)
    admit(tmp_uploads)

    with pytest.raises(Busy):
        migrate(tmp_uploads)
    assert (tmp_uploads / LEGACY).is_file()
