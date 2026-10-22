"""Immutable snapshots through the store, HTTP and process admission seams."""

import asyncio
import json
import multiprocessing
import os
import re
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.note_assets import import_asset
from app.notes import NoteBlock, NotesRun, RenderedArtifact, VerificationIssue
from app.notes_revisions import (
    RevisionConflict,
    RevisionInfo,
    RevisionNotFound,
    RevisionStore,
    TopicPatch,
    run_lock,
)
from app.syllabus import Transcript
from app.worker.config import WorkerSettings
from app.worker.main import app as worker_app
from app.worker.models import NotesModels
from app.worker.notes import ACTIVE, open_run
from app.worker.openrouter import get_openrouter_client, get_openrouter_opener
from tests.test_notes import course
from tests.test_notes_references import cited_document, image_bytes
from tests.test_plans import put_transcript

RUN = "20261022-120000-abcd"
# Separate OS processes, not tasks: the run lock must hold across processes.
PROCESSES = multiprocessing.get_context("spawn")
CRASH = 70


def run_metadata(state="done") -> NotesRun:
    return NotesRun(
        id=RUN,
        course="1",
        status=state,
        stage=state,
        created_at="2026-10-22",
        updated_at="2026-10-22",
        models={},
    )


@pytest.fixture
def saved_run(tmp_uploads):
    directory = tmp_uploads / "1/notes" / RUN
    directory.mkdir(parents=True)
    document = cited_document()
    document.run = RUN
    first = document.sections[0].topics[0]
    first.status = "verified"
    other = first.model_copy(deep=True)
    other.topic_id = "T2"
    other.blocks[0].id = "T2.1"
    other.evidence[0].chunk_id = "c2"
    other.blocks[0].citations = ["c2"]
    first.blocks.append(
        NoteBlock(id="T1.2", kind="summary", title=None, content="In short.", citations=[])
    )
    first.verifier, first.rounds = "test/verifier", 1
    first.open_issues = [
        VerificationIssue(
            block=None, kind="citation", severity="minor", detail="Thin evidence", fix="Add"
        ),
        VerificationIssue(block=0, kind="clarity", severity="minor", detail="Wordy", fix="Trim"),
    ]
    document.sources[0].chunk_ids.append("c2")
    document.sections[0].topics.append(other)
    (directory / "notes.json").write_text(document.model_dump_json())
    (directory / "run.json").write_text(run_metadata().model_dump_json())
    return directory, document


@pytest.fixture
def model_calls(mock_openrouter) -> list[str]:
    """Every model request the worker attempts; saving and restoring must make none."""
    calls: list[str] = []

    def refuse(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        return httpx2.Response(500, json={"error": {"message": "Unexpected model call"}})

    mock_openrouter(refuse)
    return calls


@pytest.fixture
def client(model_calls) -> TestClient:
    return TestClient(app)


def blocks_of(document, topic=0) -> list[dict]:
    return [block.model_dump() for block in document.sections[0].topics[topic].blocks]


def patch_for(document, text="Edited text", base=0, topic=0):
    blocks = blocks_of(document, topic)
    blocks[0]["content"] = text
    return {"base_revision": base, "blocks": blocks}


def url(path=""):
    return f"/plans/1/notes/{RUN}{path}"


def topics(view) -> list[dict]:
    return view["document"]["sections"][0]["topics"]


def files(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


# Child processes. Spawned children import this module, so these stay at module level.


def commit_until(directory: str, point: str, patch: dict) -> None:
    """Commit, but terminate abruptly at one publication step of the transaction."""
    rename, replace = os.rename, os.replace

    def renaming(source, target):
        editorial = Path(target).name != "000000"
        if point == "before_rename" and editorial:
            os._exit(CRASH)
        rename(source, target)
        if point == ("after_rename" if editorial else "after_baseline"):
            os._exit(CRASH)

    def replacing(source, target):
        replace(source, target)
        if point == "after_head" and Path(target).name == "head.json":
            os._exit(CRASH)

    os.rename, os.replace = renaming, replacing
    RevisionStore(Path(directory)).commit_topic("T1", TopicPatch(**patch))


def contend(directory: str, action: str, patch: dict | None, barrier, results) -> None:
    """Start together with a rival process, then edit or resume the same run."""
    folder = Path(directory)
    barrier.wait(30)
    try:
        if action == "edit":
            view = RevisionStore(folder).commit_topic("T1", TopicPatch(**patch))
            outcome = f"revision {view.info.revision}"
        else:
            models = NotesModels.from_settings(WorkerSettings(uploads_dir=folder.parents[2]))
            open_run(folder.parents[1], "1", folder.name, models)
            outcome = "resumed"
    except RevisionConflict:
        outcome = "conflict"
    except Exception as error:  # Reported at once rather than as a queue timeout.
        outcome = f"error: {error!r}"
    results.put((action, outcome))


def hold_run_lock(directory: str, acquired, release) -> None:
    with run_lock(Path(directory)):
        acquired.set()
        release.wait(10)


def interrupt(directory: Path, point: str, patch: dict) -> None:
    process = PROCESSES.Process(target=commit_until, args=(str(directory), point, patch))
    process.start()
    process.join(60)
    assert process.exitcode == CRASH


def race(*jobs) -> list[tuple[str, str]]:
    barrier, results = PROCESSES.Barrier(len(jobs)), PROCESSES.Queue()
    processes = [
        PROCESSES.Process(target=contend, args=(str(directory), action, patch, barrier, results))
        for directory, action, patch in jobs
    ]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=60) for _ in processes]
    for process in processes:
        process.join(60)
        assert process.exitcode == 0
    return sorted(outcomes)


# The store.


def test_edit_one_topic_preserves_other_topics_and_sources(saved_run):
    directory, document = saved_run
    before = (directory / "notes.json").read_bytes()
    store = RevisionStore(directory)
    edited = store.commit_topic("T1", TopicPatch(**patch_for(document)))
    assert edited.info.revision == 1
    assert edited.info.parent == 0
    assert edited.info.changed_topics == ["T1"]
    other_topic_before = document.sections[0].topics[1]
    other_topic_after = edited.document.sections[0].topics[1]
    assert other_topic_after == other_topic_before
    assert edited.document.sources == document.sources
    changed = edited.document.sections[0].topics[0]
    assert [block.id for block in changed.blocks] == ["T1.1", "T1.2"]
    assert changed.blocks[0].citations == ["c1"]
    assert changed.blocks[1] == document.sections[0].topics[0].blocks[1]
    assert store.current() == edited
    assert store.read(0).document == document
    assert store.read(1) == edited
    assert (directory / "notes.json").read_bytes() == before
    assert [r.revision for r in store.list()] == [0, 1]


def test_old_run_imports_as_revision_zero(tmp_uploads, client):
    course(tmp_uploads)  # The primary transcript says "en".
    directory = tmp_uploads / "1/notes" / RUN
    directory.mkdir(parents=True)
    document = cited_document()
    document.run = RUN
    legacy = document.model_dump(mode="json", exclude={"schema_version", "language", "assets"})
    for topic in legacy["sections"][0]["topics"]:
        for field in ("objectives", "verification_stale", "error"):
            topic.pop(field)
    (directory / "notes.json").write_text(json.dumps(legacy))
    (directory / "run.json").write_text(run_metadata().model_dump_json())
    before = files(directory)

    run = client.get(url()).json()
    assert run["current_revision"] == 0
    assert run["document"]["schema_version"] == 1
    assert run["document"]["language"] == "en"
    assert client.get(url("/revisions")).json() == [
        RevisionInfo(
            revision=0,
            parent=None,
            created_at=document.created_at,
            origin="generation",
            changed_topics=[],
        ).model_dump()
    ]
    zero = client.get(url("/revisions/0")).json()
    assert zero["info"]["revision"] == 0
    assert zero["document"] == run["document"]
    assert client.get(url("/revisions/1")).status_code == 404
    assert files(directory) == before  # API reads never migrate.

    saved = client.patch(url("/topics/T1"), json=patch_for(document))
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"]["revision"] == 1
    assert saved.json()["render"] is None

    # The first worker write froze the recovered language into snapshot 0.
    transcript_path = tmp_uploads / "1/syllabus/s.pdf.transcript.json"
    transcript = Transcript.model_validate_json(transcript_path.read_text())
    put_transcript(tmp_uploads, transcript.model_copy(update={"language": "uk"}))
    zero = client.get(url("/revisions/0")).json()["document"]
    assert (zero["schema_version"], zero["language"]) == (1, "en")
    assert zero["sections"] == run["document"]["sections"]
    assert client.get(url()).json()["document"]["language"] == "en"
    assert (directory / "notes.json").read_bytes() == before["notes.json"]


def test_two_writers_have_one_conflict(saved_run, client, model_calls):
    directory, document = saved_run

    first = client.patch(url("/topics/T1"), json=patch_for(document, "First writer"))
    second = client.patch(url("/topics/T2"), json=patch_for(document, "Second writer", topic=1))

    assert first.status_code == 200, first.text
    assert second.status_code == 409
    assert "current revision is 1" in second.json()["detail"]
    run = client.get(url()).json()
    assert run["current_revision"] == 1
    t1, t2 = topics(run)
    assert t1["blocks"][0]["content"] == "First writer"
    assert t2 == document.sections[0].topics[1].model_dump()
    assert model_calls == []


def test_writer_processes_race_to_one_revision(saved_run):
    directory, document = saved_run

    outcomes = race(
        (directory, "edit", patch_for(document, "Process A")),
        (directory, "edit", patch_for(document, "Process B")),
    )

    assert outcomes == [("edit", "conflict"), ("edit", "revision 1")]
    store = RevisionStore(directory)
    assert [info.revision for info in store.list()] == [0, 1]
    assert sorted(p.name for p in (directory / "revisions").iterdir()) == ["000000", "000001"]
    content = store.current().document.sections[0].topics[0].blocks[0].content
    assert content in ("Process A", "Process B")


def test_resume_preserves_edited_revision(saved_run, client, model_calls):
    directory, document = saved_run
    course(directory.parents[2])
    assert client.patch(url("/topics/T1"), json=patch_for(document)).status_code == 200
    names = ("notes.json", "head.json", "run.json")
    before = {name: (directory / name).read_bytes() for name in names}

    resumed = client.post("/plans/1/notes", json={"resume": RUN})

    assert resumed.status_code == 409
    assert "new run" in resumed.json()["detail"]
    assert {name: (directory / name).read_bytes() for name in names} == before
    assert client.get(url()).json()["current_revision"] == 1
    assert "1" not in ACTIVE
    assert model_calls == []


def test_resume_and_edit_processes_never_overwrite_sources(saved_run):
    directory, document = saved_run
    before = (directory / "notes.json").read_bytes()

    outcomes = race((directory, "resume", None), (directory, "edit", patch_for(document)))

    assert outcomes == [("edit", "revision 1"), ("resume", "conflict")]
    assert (directory / "notes.json").read_bytes() == before
    assert NotesRun.model_validate_json((directory / "run.json").read_text()).status == "done"
    assert RevisionStore(directory).current().info.revision == 1


def test_changed_topic_loses_old_verification(saved_run, client):
    directory, document = saved_run

    assert client.patch(url("/topics/T1"), json=patch_for(document)).status_code == 200

    changed, other = topics(client.get(url()).json())
    assert changed["status"] == "unresolved"
    assert changed["verification_stale"] is True
    assert (changed["verifier"], changed["rounds"]) == (None, 0)
    # Block-indexed results no longer address the edited blocks; topic-level gaps remain.
    assert [issue["detail"] for issue in changed["open_issues"]] == ["Thin evidence"]
    assert other["status"] == "verified" and other["verification_stale"] is False
    zero = RevisionStore(directory).read(0).document.sections[0].topics[0]
    assert (zero.status, zero.verifier, len(zero.open_issues)) == ("verified", "test/verifier", 2)


def test_foreign_block_or_chunk_id_is_rejected(saved_run, client):
    directory, document = saved_run
    t1, t2 = blocks_of(document), blocks_of(document, 1)
    invalid = {
        "foreign block": [t1[0], t2[0]],
        "unknown block": [t1[0] | {"id": "T1.9"}],
        "duplicate block": [t1[0], t1[0]],
        "foreign chunk": [t1[0] | {"citations": ["c2"]}],
        "unknown chunk": [t1[0] | {"citations": ["c404"]}],
    }
    for case, blocks in invalid.items():
        response = client.patch(url("/topics/T1"), json={"base_revision": 0, "blocks": blocks})
        assert response.status_code == 422, case
    assert client.patch(url("/topics/T9"), json=patch_for(document)).status_code == 404
    assert not (directory / "revisions").exists()
    assert not (directory / "head.json").exists()

    added = {"id": "", "kind": "example", "title": None, "content": "New.", "citations": ["c1"]}
    reorder = {"base_revision": 0, "blocks": [t1[1], added, t1[0]]}
    saved = client.patch(url("/topics/T1"), json=reorder)
    assert saved.status_code == 200, saved.text
    reordered = topics(client.get(url()).json())[0]["blocks"]
    assert [reordered[0], reordered[2]] == [t1[1], t1[0]]
    assert re.fullmatch(r"b-[0-9a-f]{32}", reordered[1]["id"])

    deleted = client.patch(url("/topics/T1"), json={"base_revision": 1, "blocks": reordered[1:]})
    assert deleted.status_code == 200, deleted.text
    assert topics(client.get(url()).json())[0]["blocks"] == reordered[1:]


def test_saving_needs_no_openrouter_and_keeps_earlier_artifacts(saved_run):
    directory, document = saved_run
    worker_app.dependency_overrides[get_openrouter_opener] = lambda: None
    worker_app.dependency_overrides[get_openrouter_client] = lambda: None
    artifact = RenderedArtifact(format="pdf", path="notes.pdf", revision=0, status="ready")
    (directory / "artifacts.json").write_text(json.dumps([artifact.model_dump()]))
    client = TestClient(app)

    saved = client.patch(url("/topics/T1"), json=patch_for(document))
    restored = client.post(url("/revisions/0/restore"), json={"base_revision": 1})

    assert saved.status_code == 200, saved.text
    assert restored.status_code == 200, restored.text
    run = client.get(url()).json()
    assert run["current_revision"] == 2
    assert run["artifacts"] == [artifact.model_dump()]  # Still tagged as revision 0.


def test_only_completed_runs_are_edited(saved_run, client):
    directory, document = saved_run
    (directory / "run.json").write_text(run_metadata("running").model_dump_json())

    assert client.get(url("/revisions")).status_code == 404
    response = client.patch(url("/topics/T1"), json=patch_for(document))
    assert response.status_code == 409
    assert "completed" in response.json()["detail"]
    missing = "/plans/1/notes/20261022-130000-beef/topics/T1"
    assert client.patch(missing, json=patch_for(document)).status_code == 404
    assert not (directory.parent / "20261022-130000-beef").exists()


# Restore and no-op policy.


def test_restore_returns_content_without_old_verification(saved_run, client, model_calls):
    directory, document = saved_run
    store = RevisionStore(directory)
    store.commit_topic("T1", TopicPatch(**patch_for(document, "A")))
    store.commit_topic("T2", TopicPatch(**patch_for(document, "B", base=1, topic=1)))
    history = {name: files(directory / "revisions" / name) for name in ("000001", "000002")}
    current_t1 = store.current().document.sections[0].topics[0]

    restored = client.post(url("/revisions/1/restore"), json={"base_revision": 2})

    assert restored.status_code == 200, restored.text
    assert restored.json() == {
        "revision": restored.json()["revision"]
        | {
            "revision": 3,
            "parent": 2,
            "origin": "restore",
            "changed_topics": ["T2"],
            "restored_from": 1,
        },
        "render": None,
    }
    t1, t2 = store.current().document.sections[0].topics
    assert t1 == current_t1  # Unchanged by the restore, byte-equivalent to current state.
    assert t2.blocks == document.sections[0].topics[1].blocks
    assert (t2.status, t2.verification_stale, t2.verifier) == ("unresolved", True, None)
    assert {name: files(directory / "revisions" / name) for name in history} == history

    # Same content as revision 0 for T2 now: it keeps its current (stale) verification.
    zero = client.post(url("/revisions/0/restore"), json={"base_revision": 3}).json()
    assert zero["revision"]["changed_topics"] == ["T1"]
    t1, t2 = store.current().document.sections[0].topics
    assert t1.blocks == document.sections[0].topics[0].blocks
    assert t1.status == "unresolved" and t1.verification_stale is True
    assert (t2.status, t2.verification_stale) == ("unresolved", True)

    assert client.post(url("/revisions/2/restore"), json={"base_revision": 3}).status_code == 409
    assert client.post(url("/revisions/99/restore"), json={"base_revision": 4}).status_code == 404
    assert [info.revision for info in store.list()] == [0, 1, 2, 3, 4]
    assert model_calls == []


def test_unchanged_save_or_restore_keeps_current_revision(saved_run, client, model_calls):
    directory, document = saved_run
    unchanged = {"base_revision": 0, "blocks": blocks_of(document)}

    saved = client.patch(url("/topics/T1"), json=unchanged)
    restored = client.post(url("/revisions/0/restore"), json={"base_revision": 0})

    for response in (saved, restored):
        assert response.status_code == 200, response.text
        assert response.json()["revision"]["revision"] == 0
        assert response.json()["render"] is None
    assert not (directory / "revisions").exists() and not (directory / "head.json").exists()
    assert topics(client.get(url()).json())[0]["status"] == "verified"
    assert model_calls == []


# Document language and figure assets.


def test_language_patch_only_fills_unknown_language(saved_run, client):
    directory, document = saved_run
    document.language = None
    (directory / "notes.json").write_text(document.model_dump_json())
    before = (directory / "notes.json").read_bytes()

    text = client.patch(url("/topics/T1"), json=patch_for(document, "Still unknown"))
    assert text.status_code == 200, text.text
    assert client.get(url()).json()["document"]["language"] is None

    blocks = topics(client.get(url()).json())[1]["blocks"]
    chosen = client.patch(
        url("/topics/T2"), json={"base_revision": 1, "blocks": blocks, "language": "uk"}
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["revision"] | {"created_at": None} == {
        "revision": 2,
        "parent": 1,
        "created_at": None,
        "origin": "manual",
        "changed_topics": [],
        "restored_from": None,
    }
    run = client.get(url()).json()
    assert run["document"]["language"] == "uk"
    assert topics(run)[1]["status"] == "verified"
    assert topics(run)[1]["verification_stale"] is False

    repeated = client.patch(
        url("/topics/T2"), json={"base_revision": 2, "blocks": blocks, "language": "uk"}
    )
    assert repeated.json()["revision"]["revision"] == 2
    conflicting = client.patch(
        url("/topics/T2"), json={"base_revision": 2, "blocks": blocks, "language": "en"}
    )
    assert conflicting.status_code == 422
    assert RevisionStore(directory).read(0).document.language is None
    assert (directory / "notes.json").read_bytes() == before


def test_figures_come_only_from_the_run_asset_catalog(saved_run, client, tmp_uploads):
    directory, document = saved_run
    asset = import_asset(directory, image_bytes(), "plot.png")
    elsewhere = tmp_uploads / "1/notes/20261022-130000-beef"
    elsewhere.mkdir(parents=True)
    foreign = import_asset(elsewhere, image_bytes(size=(8, 8)), "other.png")

    def figure(path: str) -> dict:
        return patch_for(document, f"See @fig-plot.\n\n![A plot]({path}){{#fig-plot}}")

    for path in (foreign.path, f"assets/{'0' * 64}.png", "../../run.json"):
        response = client.patch(url("/topics/T1"), json=figure(path))
        assert response.status_code == 422, path
    jpeg = asset.path.replace(".png", ".jpg")
    assert client.patch(url("/topics/T1"), json=figure(jpeg)).status_code == 422

    saved = client.patch(url("/topics/T1"), json=figure(asset.path))

    assert saved.status_code == 200, saved.text
    run = client.get(url()).json()
    assert run["document"]["assets"] == [asset.model_dump()]
    assert topics(run)[1] == document.sections[0].topics[1].model_dump()
    later = client.patch(url("/topics/T2"), json=patch_for(document, "Other", base=1, topic=1))
    assert later.status_code == 200, later.text
    assert client.get(url()).json()["document"]["assets"] == [asset.model_dump()]


# Crash safety: HEAD replacement is the only editorial commit point.


@pytest.mark.parametrize("point", ["before_rename", "after_rename", "after_head"])
def test_interrupted_commit_exposes_old_or_new_revision(saved_run, point):
    directory, document = saved_run
    store = RevisionStore(directory)
    store.commit_topic("T1", TopicPatch(**patch_for(document, "Committed")))

    interrupt(directory, point, patch_for(document, "Interrupted", base=1))

    current = store.current()
    expected = 2 if point == "after_head" else 1
    assert current.info.revision == expected
    content = current.document.sections[0].topics[0].blocks[0].content
    assert content == ("Interrupted" if point == "after_head" else "Committed")
    assert [info.revision for info in store.list()] == list(range(expected + 1))
    orphan = directory / "revisions/000002"
    if point == "before_rename":
        assert any(p.name.startswith(".") for p in (directory / "revisions").iterdir())
    if point == "after_rename":
        assert orphan.is_dir()
        with pytest.raises(RevisionNotFound):
            store.read(2)
    left = files(orphan) if orphan.is_dir() else {}

    following = store.commit_topic("T1", TopicPatch(**patch_for(document, "Next", base=expected)))

    assert following.info.parent == expected
    assert following.info.revision == (2 if point == "before_rename" else 3)
    assert store.current() == following
    if point == "after_rename":
        assert files(orphan) == left
        assert [info.revision for info in store.list()] == [0, 1, 3]


def test_interrupted_baseline_publication_keeps_original_readable(saved_run):
    directory, document = saved_run
    before = (directory / "notes.json").read_bytes()

    interrupt(directory, "after_baseline", patch_for(document))

    baseline = directory / "revisions/000000"
    assert baseline.is_dir() and not (directory / "head.json").exists()
    store = RevisionStore(directory)
    assert store.current().info.revision == 0
    assert store.current().document == document
    assert [info.revision for info in store.list()] == [0]
    published = files(baseline)

    saved = store.commit_topic("T1", TopicPatch(**patch_for(document)))

    assert (saved.info.revision, saved.info.parent) == (1, 0)
    assert files(baseline) == published
    assert (directory / "notes.json").read_bytes() == before


@pytest.mark.parametrize("damage", ["corrupt", "mismatched"])
def test_invalid_baseline_is_rejected_not_overwritten(saved_run, damage):
    directory, document = saved_run
    baseline = directory / "revisions/000000"
    baseline.mkdir(parents=True)
    info = RevisionInfo(
        revision=0,
        parent=None,
        created_at=document.created_at,
        origin="generation",
        changed_topics=[],
    )
    stored = document.model_copy(update={"title": "Another run"})
    (baseline / "revision.json").write_text("{" if damage == "corrupt" else info.model_dump_json())
    (baseline / "document.json").write_text(stored.model_dump_json())
    left = files(baseline)
    store = RevisionStore(directory)

    with pytest.raises(RevisionConflict):
        store.commit_topic("T1", TopicPatch(**patch_for(document)))

    assert files(baseline) == left
    assert not (directory / "head.json").exists()
    assert store.current().document == document  # Readers fall back to notes.json.


# The run lock is never awaited on the event loop.


def test_waiting_for_the_run_lock_keeps_the_worker_responsive(saved_run):
    directory, document = saved_run
    acquired, release = PROCESSES.Event(), PROCESSES.Event()
    holder = PROCESSES.Process(target=hold_run_lock, args=(str(directory), acquired, release))
    holder.start()

    async def scenario() -> httpx2.Response:
        transport = httpx2.ASGITransport(app=worker_app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://worker.test") as http:
            body = {"course": "1", "run": RUN, "topic": "T1", "patch": patch_for(document)}
            save = asyncio.create_task(http.post("/notes/revise", json=body))
            await asyncio.sleep(0.3)
            health = await asyncio.wait_for(http.get("/health"), 5)
            assert health.status_code == 200
            assert not save.done()
            release.set()
            return await asyncio.wait_for(save, 30)

    try:
        assert acquired.wait(30)
        response = asyncio.run(scenario())
    finally:
        release.set()
        holder.join(30)
    assert response.status_code == 200, response.text
    assert response.json()["revision"]["revision"] == 1
