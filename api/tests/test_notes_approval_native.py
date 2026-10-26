"""Opt-in real Quarto evidence for approved and historical student artifacts."""

import asyncio
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.note_assets import asset_resources, import_asset
from app.notes import NotesRun
from app.notes_revisions import ApprovalAction, RevisionStore
from app.worker.course_book import build_book_project, render_book
from app.worker.quarto import render_document
from app.worker.render import labels, to_quarto, topic_to_quarto
from tests.e2e.synthetic import FIXTURES, control_document


def extracted(path: Path, kind: str) -> str:
    if kind == "pdf":
        return " ".join(page.extract_text() for page in PdfReader(path).pages)
    if kind == "docx":
        with zipfile.ZipFile(path) as archive:
            return archive.read("word/document.xml").decode()
    return path.read_text()


def test_real_quarto_approval_all_formats(tmp_path: Path):
    binary = os.environ.get("QUARTO_TEST_BIN")
    if not binary:
        pytest.skip("Set QUARTO_TEST_BIN to run real teacher-approval formats")
    output = Path(os.environ.get("NOTES_APPROVAL_OUTPUT") or tmp_path / "approval-native")
    output.mkdir(parents=True, exist_ok=True)
    document = control_document()
    run = output / "uploads" / document.course / "notes" / document.run
    run.mkdir(parents=True)
    import_asset(run, (FIXTURES / "figure.png").read_bytes(), "figure.png")
    (run / "notes.json").write_text(document.model_dump_json())
    (run / "run.json").write_text(
        NotesRun(
            id=document.run,
            course=document.course,
            status="done",
            stage="done",
            created_at=document.created_at,
            updated_at=document.created_at,
            models=document.models,
        ).model_dump_json()
    )
    store = RevisionStore(run)
    approved = store.decide(
        "T2", ApprovalAction(base_revision=0, action="approve", reviewer="Teacher")
    ).document
    historical = store.read(0).document
    warning = labels(document.language)["unverified"]

    async def render_snapshot(snapshot, revision: int, kinds: list[str]) -> None:
        root = output / f"revision-{revision}"
        for scope in ("full", "T2"):
            folder = root / scope
            folder.mkdir(parents=True)
            sources = {}
            resources = {}
            for kind in kinds:
                if scope == "full":
                    source = to_quarto(snapshot, snapshot.language, kind)
                else:
                    section = next(
                        s for s in snapshot.sections if any(t.topic_id == "T2" for t in s.topics)
                    )
                    topic = next(t for t in section.topics if t.topic_id == "T2")
                    source = topic_to_quarto(snapshot, section, topic, snapshot.language, kind)
                path = folder / "sources" / kind / "notes.qmd"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source)
                sources[kind] = path
                resources.update(asset_resources(run, snapshot.assets, source))
            rendered = await render_document(sources, folder, revision, binary, resources)
            assert all(item.status == "ready" for item in rendered), rendered
            for kind in kinds:
                path = folder / f"notes.{kind}"
                assert path.is_file() and path.stat().st_size > 100
                content = extracted(path, kind)
                assert (warning in content) == (revision == 0), (revision, scope, kind)
        project = root / "book-source"
        build_book_project(snapshot, project, snapshot.language)
        for qmd in project.glob("*.qmd"):
            for name, asset in asset_resources(run, snapshot.assets, qmd.read_text()).items():
                destination = project / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(asset, destination)
        book = await render_book(project, revision, binary)
        assert book.status == "ready", book.error
        chapter = (root / "book" / "topic-T2.html").read_text()
        assert (warning in chapter) == (revision == 0), revision

    asyncio.run(render_snapshot(historical, 0, ["html", "pdf", "docx"]))
    asyncio.run(render_snapshot(approved, 1, ["html", "pdf", "docx"]))
