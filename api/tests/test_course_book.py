"""Course books use one approved snapshot and expose only published files."""

import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.note_assets import asset_resources, import_asset
from app.notes import NotesRun, RenderedArtifact
from app.notes_artifacts import atomic_json, revision_folder
from app.worker.course_book import build_book_project, render_book
from tests.e2e.synthetic import FIXTURES, control_document


def test_book_chapters_follow_document_order(tmp_path: Path):
    document = control_document()
    config = build_book_project(document, tmp_path, "uk")
    value = config.read_text()
    assert value.index("topic-T1.qmd") < value.index("topic-T2.qmd")
    assert (tmp_path / "topic-T1.qmd").is_file()
    assert (tmp_path / "topic-T2.qmd").is_file()
    assert "@eq-t1-sarrus" in (tmp_path / "topic-T2.qmd").read_text()
    assert 'crossref-eq-prefix: "Рівняння"' in value


def test_duplicate_titles_keep_distinct_topic_urls(tmp_path: Path):
    document = control_document()
    document.sections[0].topics[1].title = document.sections[0].topics[0].title
    build_book_project(document, tmp_path, "uk")
    assert (tmp_path / "topic-T1.qmd").is_file()
    assert (tmp_path / "topic-T2.qmd").is_file()


def test_book_search_has_only_current_revision_notes(tmp_path: Path):
    document = control_document()
    build_book_project(document, tmp_path, "uk")
    source = "\n".join(path.read_text() for path in tmp_path.glob("*.qmd"))
    assert "Градієнт" in source or document.sections[0].topics[0].title in source
    for item in document.sources:
        assert item.file not in source
    for section in document.sections:
        for topic in section.topics:
            for evidence in topic.evidence:
                assert evidence.text not in source


def test_book_asset_path_cannot_leave_artifact_root(tmp_path: Path):
    from app.notes_artifacts import book_asset_path

    root = tmp_path / "book"
    root.mkdir()
    (root / "index.html").write_text("ok")
    (root / "public.json").write_text("{}")
    outside = tmp_path / "private.txt"
    outside.write_text("secret")
    (root / "link.txt").symlink_to(outside)
    (root / "publication.json").write_text(json.dumps(["index.html", "public.json", "link.txt"]))
    assert book_asset_path(root, "") == root / "index.html"
    assert book_asset_path(root, "public.json") == root / "public.json"
    for path in ("../private.txt", "%2e%2e/private.txt", "link.txt", "publication.json", "missing"):
        with pytest.raises(ValueError):
            book_asset_path(root, path)
    (root / "publication.json").unlink()
    (root / "publication.json").symlink_to(outside)
    with pytest.raises(ValueError):
        book_asset_path(root, "index.html")


def test_unresolved_topic_warning_is_visible(tmp_path: Path):
    document = control_document()
    build_book_project(document, tmp_path, "uk")
    assert "Не повністю перевірено" in (tmp_path / "topic-T2.qmd").read_text()
    document.sections[0].topics[1].open_issues = []
    build_book_project(document, tmp_path, "uk")
    assert "Не повністю перевірено" in (tmp_path / "topic-T2.qmd").read_text()
    assert "\n-\n" not in (tmp_path / "topic-T2.qmd").read_text()
    document.sections[0].topics[0].status = "failed"
    # Persisted target ownership permits links to the failed chapter's status page.
    build_book_project(document, tmp_path, "uk")
    assert "Не вдалося створити тему" in (tmp_path / "topic-T1.qmd").read_text()


def test_book_route_uses_publication_and_final_wire_policy(tmp_uploads: Path):
    document = control_document()
    directory = tmp_uploads / document.course / "notes" / document.run
    directory.mkdir(parents=True)
    (directory / "notes.json").write_text(document.model_dump_json())
    run = NotesRun(
        id=document.run,
        course=document.course,
        status="done",
        stage="done",
        created_at=document.created_at,
        updated_at=document.created_at,
        models={},
    )
    (directory / "run.json").write_text(run.model_dump_json())
    root = revision_folder(directory, 0) / "artifacts"
    book = root / "test-job/book"
    book.mkdir(parents=True)
    (book / "index.html").write_text("<html>Book</html>")
    (book / "search.json").write_text("[]")
    (book / "private.txt").write_text("secret")
    (book / "publication.json").write_text('["index.html", "search.json"]')
    atomic_json(
        root / "manifest.json",
        [
            RenderedArtifact(
                format="book", path="test-job/book", revision=0, status="ready"
            ).model_dump()
        ],
    )
    prefix = f"/plans/{document.course}/notes/{document.run}/revisions/0"
    with TestClient(app) as client:
        response = client.get(prefix + "/book/", headers={"Origin": "null"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in response.headers
        assert "sandbox allow-scripts" in response.headers["content-security-policy"]
        assert response.headers["x-notes-revision"] == "0"
        allowed = client.get(
            prefix + "/book/search.json", headers={"Origin": "http://localhost:3000"}
        )
        assert allowed.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in allowed.headers
        partial = client.get(
            prefix + "/book/index.html",
            headers={"Origin": "http://localhost:3000", "Range": "bytes=0-3"},
        )
        assert partial.status_code == 206
        assert partial.content == b"<htm"
        assert partial.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in partial.headers
        assert "x-book-published" not in partial.headers
        assert (
            client.get(prefix + "/book/search.json", headers={"Origin": "null"}).status_code == 200
        )
        for path in ("/book/private.txt", "/book/publication.json", "/artifacts/book"):
            rejected = client.get(prefix + path, headers={"Origin": "null"})
            assert rejected.status_code == 404
            assert rejected.headers.get("access-control-allow-origin") != "*"


@pytest.mark.anyio
async def test_real_book_search_and_registered_image(tmp_path: Path):
    quarto = os.environ.get("QUARTO_TEST_BIN")
    if not quarto:
        pytest.skip("Set QUARTO_TEST_BIN to exercise actual Quarto book output")
    document = control_document()
    assert (
        import_asset(tmp_path, (FIXTURES / "figure.png").read_bytes(), "figure.png")
        == document.assets[0]
    )
    project = tmp_path / "job/book-source"
    build_book_project(document, project, "uk")
    for qmd in project.glob("*.qmd"):
        for name, source in asset_resources(tmp_path, document.assets, qmd.read_text()).items():
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    artifact = await render_book(project, 7, quarto)
    assert artifact.status == "ready", artifact.error
    book = tmp_path / "job/book"
    published = json.loads((book / "publication.json").read_text())
    assert {
        "index.html",
        "topic-T1.html",
        "topic-T2.html",
        "references.html",
        "search.json",
    } <= set(published)
    search = (book / "search.json").read_text()
    assert "Власний вектор" in search
    assert "topic-T2.html" in search and "local/reading/" not in search
    assert document.assets[0].path in published
    assert "topic-T1.html#eq-t1-sarrus" in (book / "topic-T2.html").read_text()
    assert (
        'href="topic-T1.html#eq-t1-sarrus" class="quarto-xref">Рівняння'
        in (book / "topic-T2.html").read_text()
    )
    assert "Рисунок&nbsp;" in (book / "topic-T2.html").read_text()
    chapter = (book / "topic-T1.html").read_text()
    assert "mathjax@3/es5/tex-chtml-full.js" in chapter
    assert "cdnjs.cloudflare.com/polyfill/v3" not in chapter


@pytest.mark.parametrize("invalid", ["unknown", "duplicate", "foreign_evidence", "foreign_source"])
def test_book_enforces_shared_reference_errors(tmp_path, invalid):
    from app.worker.quarto import QuartoError

    document = control_document()
    first = document.sections[0].topics[0]
    other = document.sections[0].topics[1]
    if invalid == "unknown":
        other.blocks[0].content += "\n\nSee @eq-does-not-exist."
    elif invalid == "duplicate":
        other.blocks[0].content += "\n\n$$x=1$$ {#eq-t1-sarrus}"
    elif invalid == "foreign_evidence":
        first.blocks[0].citations = [other.evidence[0].chunk_id]
    else:
        other.evidence[0].source = 999
    with pytest.raises(QuartoError, match="Invalid references"):
        build_book_project(document, tmp_path, "uk")
    assert not (tmp_path / "_quarto.yml").exists()


def test_failed_topic_allows_only_known_targets_linked_to_its_status_page(tmp_path):
    """No guessed ownership from eq-t1-* names; only persisted targets have provenance."""
    from app.worker.quarto import QuartoError

    document = control_document()
    first, other = document.sections[0].topics
    first.status = "failed"
    # Its persisted labels are known, but the chapter renders a placeholder only.
    build_book_project(document, tmp_path, "uk")
    chapter = (tmp_path / "topic-T2.qmd").read_text()
    assert "topic-T1.html#sec-T1" in chapter
    assert "@eq-t1-sarrus" not in chapter
    first.blocks = []
    with pytest.raises(QuartoError, match="Unknown reference: eq-t1-sarrus"):
        build_book_project(document, tmp_path, "uk")
    # The stable topic anchor still exists even when generation produced no blocks.
    for block in other.blocks:
        block.content = (
            block.content.replace("@eq-t1-sarrus", "@sec-T1")
            .replace("@tbl-t1-row-operations", "@sec-T1")
            .replace("@eq-t1-augmented", "@sec-T1")
        )
    build_book_project(document, tmp_path, "uk")
    assert "Не вдалося створити тему" in (tmp_path / "topic-T1.qmd").read_text()


@pytest.mark.parametrize(
    "reserved", ["index", "references", "..", "../T2", "/absolute", "space name", "тема"]
)
def test_legacy_topic_ids_cannot_replace_owned_book_files(tmp_path, reserved):
    document = control_document()
    document.sections[0].topics[0].topic_id = reserved
    build_book_project(document, tmp_path, "uk")
    assert json.dumps(document.title, ensure_ascii=False) in (tmp_path / "index.qmd").read_text()
    chapter_files = [p for p in tmp_path.glob("topic-*.qmd")]
    assert len(chapter_files) == 2
    assert len({p.name for p in chapter_files}) == 2
    assert (tmp_path / "references.qmd").is_file()


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", ["unknown", "duplicate", "foreign_source"])
async def test_native_invalid_book_retry_retains_last_ready_same_key(tmp_path, invalid):
    from app.notes_artifacts import manifest, ready_book_root
    from app.worker.config import WorkerSettings
    from app.worker.revisions import enqueue_render, render_revision

    quarto = os.environ.get("QUARTO_TEST_BIN")
    if not quarto:
        pytest.skip("Set QUARTO_TEST_BIN for actual book publication and retry")
    document = control_document()
    tmp_path = tmp_path / document.course / "notes" / document.run
    tmp_path.mkdir(parents=True)
    import_asset(tmp_path, (FIXTURES / "figure.png").read_bytes(), "figure.png")
    project = tmp_path / "old/book-source"
    build_book_project(document, project, "uk")
    for qmd in project.glob("*.qmd"):
        for name, source in asset_resources(tmp_path, document.assets, qmd.read_text()).items():
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    prior = await render_book(project, 0, quarto)
    assert prior.status == "ready", prior.error
    prior.path = "old/book"
    old_bytes = (project.parent / "book/index.html").read_bytes()
    # Model a legacy invalid saved revision with an earlier Ready book from the
    # validator-bypassing implementation. Retry must fail without losing that file.
    note = document.sections[0].topics[1]
    if invalid == "unknown":
        note.blocks[0].content += "\n\nSee @eq-does-not-exist."
    elif invalid == "duplicate":
        note.blocks[0].content += "\n\n$$x=1$$ {#eq-t1-sarrus}"
    else:
        note.evidence[0].source = 999
    (tmp_path / "notes.json").write_text(document.model_dump_json())
    (tmp_path / "run.json").write_text(
        NotesRun(
            id=document.run,
            course=document.course,
            status="done",
            stage="done",
            created_at=document.created_at,
            updated_at=document.created_at,
            models={},
        ).model_dump_json()
    )
    job = enqueue_render(tmp_path, 0, ["book"])
    root = revision_folder(tmp_path, 0) / "artifacts"
    root.mkdir(exist_ok=True)
    shutil.move(str(project.parent), str(root / "old"))
    atomic_json(root / "manifest.json", [prior.model_dump()])
    result = await render_revision(
        tmp_path, job.id, WorkerSettings(_env_file=None, uploads_dir=tmp_path, quarto_bin=quarto)
    )
    assert result.status == "failed"
    assert any("Invalid references:" in error for error in result.errors)
    retained = ready_book_root(tmp_path, 0)
    assert (retained / "index.html").read_bytes() == old_bytes
    assert [(a.format, a.status) for a in manifest(tmp_path, 0)] == [("book", "ready")]
    assert not (revision_folder(tmp_path, 0) / "artifacts" / job.id / "book").exists()


@pytest.mark.anyio
async def test_native_known_failed_target_goes_to_status_page(tmp_path):
    quarto = os.environ.get("QUARTO_TEST_BIN")
    if not quarto:
        pytest.skip("Set QUARTO_TEST_BIN for actual failed-topic status links")
    document = control_document()
    document.sections[0].topics[0].status = "failed"
    import_asset(tmp_path, (FIXTURES / "figure.png").read_bytes(), "figure.png")
    project = tmp_path / "job/book-source"
    build_book_project(document, project, "uk")
    for qmd in project.glob("*.qmd"):
        for name, source in asset_resources(tmp_path, document.assets, qmd.read_text()).items():
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    result = await render_book(project, 0, quarto)
    assert result.status == "ready", result.error
    chapter = (tmp_path / "job/book/topic-T2.html").read_text()
    assert "topic-T1.html#sec-T1" in chapter
    assert 'class="quarto-unresolved-ref"' not in chapter
    assert "Не вдалося створити тему" in (tmp_path / "job/book/topic-T1.html").read_text()
