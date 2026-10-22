"""The synthetic control fixtures shared by backend tests, the E2E stack and visual QA."""

import asyncio
import json
import os
import zipfile
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.note_assets import asset_resources, import_asset
from app.notes import NotesDocument, NotesRun, load_document
from app.plan import load_plan
from app.syllabus import Transcript
from app.worker.artifacts import RunStore
from app.worker.config import WorkerSettings, get_worker_settings
from app.worker.main import app as worker_app
from app.worker.notes import render_notes_outputs
from app.worker.quarto import render_document
from app.worker.references import ReferenceContext, validate_references
from app.worker.render import to_quarto
from app.worker.sources import build_inputs
from tests.e2e import mock_openrouter as mock
from tests.e2e.synthetic import (
    COURSE,
    FIXTURES,
    LEGACY_RUN,
    SCHEMAS,
    answer,
    control_document,
    seed,
)


def blocks(document: NotesDocument) -> list:
    return [b for s in document.sections for t in s.topics for b in t.blocks]


def test_control_fixture_covers_the_quality_checklist() -> None:
    document = control_document()

    assert validate_references(document) == []
    assert document.schema_version == 2 and document.language == "uk"
    topics = {t.topic_id: t for s in document.sections for t in s.topics}
    assert [t.status for t in topics.values()] == ["verified", "unresolved"]
    assert topics["T2"].open_issues and topics["T2"].open_issues[0].severity == "major"
    kinds = {b.kind for b in blocks(document)}
    assert {"definition", "theorem", "proof", "example", "summary"} <= kinds
    text = "\n".join(b.content for b in blocks(document))
    for feature in (
        r"\begin{pmatrix}",  # matrices
        "a_{m1}",  # indices
        "{#eq-t1-sarrus}",  # long labelled formula
        "{#tbl-t1-row-operations}",  # captioned table
        "{#fig-t2-eigenvector}",  # figure
        "@eq-t1-sarrus",  # cross-topic equation reference
        "Topic T1",  # legacy topic link
        "In English:",  # English fragment in a Ukrainian document
    ):
        assert feature in text, feature
    assert {c for b in blocks(document) for c in b.citations} == {
        c for s in document.sources for c in s.chunk_ids
    }


def test_control_figure_matches_the_asset_registry(tmp_path: Path) -> None:
    document = control_document()

    imported = import_asset(tmp_path, (FIXTURES / "figure.png").read_bytes(), "figure.png")

    assert document.assets == [imported]
    figure = next(b for b in blocks(document) if "![" in b.content)
    assert asset_resources(tmp_path, document.assets, figure.content) == {
        imported.path: tmp_path / imported.path
    }


def test_control_evidence_matches_seeded_readings(tmp_path: Path) -> None:
    seed(tmp_path)
    course = tmp_path / COURSE
    plan = load_plan(course)
    transcript = Transcript.model_validate_json(
        (tmp_path / f"{plan.primary}.transcript.json").read_text()
    )

    inputs = build_inputs(tmp_path, course, plan, transcript)

    document = control_document()
    assert inputs.skipped == []
    assert [s.model_dump() for s in inputs.sources] == [s.model_dump() for s in document.sources]
    chunks = {c.id: c.text for c in inputs.chunks}
    for section in document.sections:
        for note in section.topics:
            for item in note.evidence:
                assert chunks[item.chunk_id] == item.text


def test_seed_refuses_to_overwrite_a_course(tmp_path: Path) -> None:
    seed(tmp_path)
    with pytest.raises(FileExistsError):
        seed(tmp_path)


def test_legacy_fixture_loads_without_schema_metadata(tmp_path: Path) -> None:
    raw = json.loads((FIXTURES / "legacy-notes.json").read_text())
    assert not {"schema_version", "language", "assets"} & raw.keys()
    topics = [t for s in raw["sections"] for t in s["topics"]]
    assert all("verification_stale" not in t for t in topics)
    seed(tmp_path)
    target = tmp_path / COURSE / "notes" / LEGACY_RUN / "notes.json"
    before = target.read_bytes()

    document = load_document(tmp_path / COURSE, LEGACY_RUN)

    assert document is not None
    assert document.schema_version == 1
    assert document.language == "uk"  # recovered read-only from the course transcript
    assert [(t["topic_id"], b["id"], b["citations"]) for t in topics for b in t["blocks"]] == [
        (t.topic_id, b.id, b.citations)
        for s in document.sections
        for t in s.topics
        for b in t.blocks
    ]
    assert target.read_bytes() == before


def request(schema: str, prompt: str = "", model: str = "e2e/model") -> dict:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_schema", "json_schema": {"name": schema}},
    }


def test_mock_openrouter_answers_by_schema_and_topic(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "mock.jsonl"
    monkeypatch.setenv("NOTES_E2E_MOCK_LOG", str(log))
    client = TestClient(mock.app)

    assert client.get("/health").json() == {"status": "ok"}
    prompts = {"topic_draft": "Topic T2: x", "topic_verification": "Topic T2: x"}
    for schema in SCHEMAS:
        response = client.post(
            "/api/v1/chat/completions", json=request(schema, prompts.get(schema, ""))
        )
        assert response.status_code == 200, (schema, response.text)
        assert response.json()["model"] == "e2e/model"
        json.loads(response.json()["choices"][0]["message"]["content"])

    unknown = client.post("/api/v1/chat/completions", json=request("future_schema"))
    assert unknown.status_code == 500
    assert "future_schema" in unknown.json()["error"]["message"]
    no_topic = client.post("/api/v1/chat/completions", json=request("topic_draft"))
    assert no_topic.status_code == 500

    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r.get("schema") for r in records[: len(SCHEMAS)]] == list(SCHEMAS)
    assert "error" in records[-1] and "error" in records[-2]
    assert answer(request("topic_verification", "Topic T1: x"))[0]["passed"] is True
    assert answer(request("topic_verification", "Topic T2: x"))[0]["passed"] is False
    draft = answer(request("topic_draft", "Topic T2: x"))[0]
    assert all("![" not in b["content"] for b in draft["blocks"])


@pytest.fixture
def synthetic_uploads(tmp_uploads: Path):
    settings = WorkerSettings(uploads_dir=tmp_uploads, quarto_bin="no-such-quarto-binary")
    worker_app.dependency_overrides[get_worker_settings] = lambda: settings
    seed(tmp_uploads)
    yield tmp_uploads


def test_generation_through_the_scripted_llm(mock_openrouter, synthetic_uploads: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        result, _ = answer(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "model": "e2e/model",
                "choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}],
            },
        )

    client = mock_openrouter(handler)

    response = client.post(f"/plans/{COURSE}/notes")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["run"]["status"] == "done", body["run"]
    document = NotesDocument.model_validate(body["document"])
    assert validate_references(document) == []
    assert document.language == "uk"
    statuses = {t.topic_id: t.status for s in document.sections for t in s.topics}
    assert statuses == {"T1": "verified", "T2": "unresolved"}
    assert {s.title for s in document.sources} == {"linear-systems.md", "eigenvalues.md"}


@pytest.fixture(scope="module")
def control_render(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list]:
    """Opt in with QUARTO_TEST_BIN (and TYPST_FONT_PATHS). Set NOTES_FIXTURE_OUTPUT to keep
    the rendered files for visual QA."""
    binary = os.environ.get("QUARTO_TEST_BIN")
    if not binary:
        pytest.skip("Set QUARTO_TEST_BIN to render the control fixture with an installed Quarto")
    root = tmp_path_factory.mktemp("control")
    output = Path(os.environ.get("NOTES_FIXTURE_OUTPUT") or root / "run")
    output.mkdir(parents=True, exist_ok=True)
    document = control_document()
    import_asset(output, (FIXTURES / "figure.png").read_bytes(), "figure.png")
    run = NotesRun(
        id=document.run,
        course=document.course,
        status="running",
        stage="rendering",
        created_at=document.created_at,
        updated_at=document.created_at,
        models=document.models,
    )
    settings = WorkerSettings(uploads_dir=root, quarto_bin=binary, quarto_concurrency=2)
    artifacts = asyncio.run(render_notes_outputs(document, RunStore(output, run), settings))

    # Generation does not schedule Word yet: render it through the same subprocess boundary.
    source = to_quarto(document, document.language, "docx", ReferenceContext())
    folder = output / "sources" / "docx"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "notes.qmd").write_text(source)
    resources = asset_resources(output, document.assets, source)
    artifacts += asyncio.run(
        render_document({"docx": folder / "notes.qmd"}, output, 0, binary, resources=resources)
    )
    return output, artifacts


def rendered_text(output: Path) -> dict[str, str]:
    from pypdf import PdfReader

    with zipfile.ZipFile(output / "notes.docx") as archive:
        word = archive.read("word/document.xml").decode()
    return {
        "html": (output / "notes.html").read_text(),
        "pdf": " ".join(page.extract_text() for page in PdfReader(output / "notes.pdf").pages),
        "docx": word,
    }


def test_control_fixture_renders_with_actual_quarto(control_render) -> None:
    output, artifacts = control_render

    assert [a.model_dump() for a in artifacts if a.status != "ready"] == []
    assert {(a.topic_id, a.format) for a in artifacts} == {
        (topic, kind) for topic in (None, "T1", "T2") for kind in ("html", "pdf")
    } | {(None, "docx")}
    text = rendered_text(output)
    assert 'lang="uk"' in text["html"] and "MathJax" in text["html"]
    assert 'id="tbl-t1-row-operations"' in text["html"]
    assert 'id="fig-t2-eigenvector"' in text["html"]
    assert "data:image/png;base64," in text["html"]
    assert "Власні значення" in text["pdf"] and "Елементарні перетворення" in text["pdf"]
    assert "Власні значення" in text["docx"]
    with zipfile.ZipFile(output / "notes.docx") as archive:
        assert any(name.startswith("word/media/") for name in archive.namelist())


@pytest.mark.xfail(
    strict=True,
    reason="Known defect: a non-callout block whose content starts with a figure gets its bold "
    "title inlined into the image paragraph, so Quarto renders no figure and @fig-... "
    "prints as ?@fig-... in HTML, PDF and DOCX. Remove this marker once fixed.",
)
def test_control_cross_references_resolve_in_every_format(control_render) -> None:
    output, _ = control_render
    for kind, text in rendered_text(output).items():
        assert "?@" not in text, kind
