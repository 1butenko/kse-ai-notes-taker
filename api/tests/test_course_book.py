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
    assert value.index("T1.qmd") < value.index("T2.qmd")
    assert (tmp_path / "T1.qmd").is_file()
    assert (tmp_path / "T2.qmd").is_file()
    assert "@eq-t1-sarrus" in (tmp_path / "T2.qmd").read_text()
    assert 'crossref-eq-prefix: "Рівняння"' in value


def test_duplicate_titles_keep_distinct_topic_urls(tmp_path: Path):
    document = control_document()
    document.sections[0].topics[1].title = document.sections[0].topics[0].title
    build_book_project(document, tmp_path, "uk")
    assert (tmp_path / "T1.qmd").is_file()
    assert (tmp_path / "T2.qmd").is_file()


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
    assert "Не повністю перевірено" in (tmp_path / "T2.qmd").read_text()
    document.sections[0].topics[1].open_issues = []
    build_book_project(document, tmp_path, "uk")
    assert "Не повністю перевірено" in (tmp_path / "T2.qmd").read_text()
    assert "\n-\n" not in (tmp_path / "T2.qmd").read_text()
    document.sections[0].topics[0].status = "failed"
    document.sections[0].topics[0].blocks = []
    build_book_project(document, tmp_path, "uk")
    assert "Не вдалося створити тему" in (tmp_path / "T1.qmd").read_text()


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
    assert {"index.html", "T1.html", "T2.html", "references.html", "search.json"} <= set(published)
    search = (book / "search.json").read_text()
    assert "Власний вектор" in search
    assert "T2.html" in search and "local/reading/" not in search
    assert document.assets[0].path in published
    assert "T1.html#eq-t1-sarrus" in (book / "T2.html").read_text()
    assert (
        'href="T1.html#eq-t1-sarrus" class="quarto-xref">Рівняння' in (book / "T2.html").read_text()
    )
    assert "Рисунок&nbsp;" in (book / "T2.html").read_text()
    chapter = (book / "T1.html").read_text()
    assert "mathjax@3/es5/tex-chtml-full.js" in chapter
    assert "cdnjs.cloudflare.com/polyfill/v3" not in chapter
