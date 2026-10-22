import json
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.notes import Chunk, NoteBlock, NotesDocument, TopicNote, load_document
from app.plan import BookMatch, Plan, PlanSession, Proposal
from app.syllabus import Session, Transcript
from app.worker.config import WorkerSettings, get_worker_settings
from app.worker.main import app as worker_app
from app.worker.models import ModelSpec
from app.worker.notes import ACTIVE, fail_interrupted
from app.worker.render import block_markdown, labels, typst_safe
from app.worker.sources import Retriever, build_inputs, split_text
from tests.test_plans import put, put_plan, put_transcript

BOOK_PAGES = [
    "Chapter 1 Linear systems. Gaussian elimination reduces a linear system to echelon form.",
    "Row operations do not change the solution set of a linear system.",
    "Chapter 2 Vector spaces. A vector space is a set with addition and scalar multiplication.",
    "A basis of a vector space is a linearly independent spanning set.",
]


def text_pdf(path: Path, pages: list[str]) -> None:
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for text in pages:
        page = writer.add_blank_page(400, 400)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 8 Tf 10 350 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.set_page_label(0, len(pages) - 1, style="/D", start=10)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        writer.write(f)


def session(label: str, topic: str) -> Session:
    return Session(
        label=label,
        number=None,
        date=None,
        topic=topic,
        subtopics=[],
        required_readings=[],
        optional_readings=[],
    )


def course(root: Path) -> None:
    """Course 1: session s1 has an excerpt of the book (PDF pp. 1-2), s2 a Markdown handout."""
    text_pdf(root / "1/reading/book.pdf", BOOK_PAGES)
    put(root, "1/excerpts/s1/book - Ch. 1.pdf")
    put(
        root,
        "1/reading/handout.md",
        b"# Vector spaces\nA vector space is a set closed under addition.\n\n"
        b"Every vector space has a basis.",
    )
    put_transcript(
        root,
        Transcript(
            language="en",
            learning_materials=[],
            sessions=[session("Week 1", "Linear systems"), session("Week 2", "Vector spaces")],
            notes=None,
            source_path="1/syllabus/s.pdf",
            source_sha256="x",
            model="test/model",
            created_at="2026-10-01T00:00:00+00:00",
        ),
    )
    put_plan(
        root,
        "1",
        Plan(
            primary="1/syllabus/s.pdf",
            sessions=[
                PlanSession(
                    id="s1", label="Week 1", number=None, files=["1/excerpts/s1/book - Ch. 1.pdf"]
                ),
                PlanSession(id="s2", label="Week 2", number=None, files=["1/reading/handout.md"]),
            ],
            books=[
                BookMatch(material=0, raw="Hefferon. Linear Algebra.", file="1/reading/book.pdf")
            ],
            proposals=[
                Proposal(
                    id="p1",
                    session_id="s1",
                    reading="[1] Ch. 1",
                    book="1/reading/book.pdf",
                    label="Ch. 1",
                    pdf_start=1,
                    pdf_end=2,
                    printed="pp. 10–11",
                    method="bookmarks",
                    status="approved",
                    excerpt="1/excerpts/s1/book - Ch. 1.pdf",
                )
            ],
        ),
    )


def topic(id: str, title: str, sessions: list[int], sources: list[int], terms: list[str]):
    return {
        "id": id,
        "title": title,
        "sessions": sessions,
        "objectives": [f"Explain {title.lower()}"],
        "success_criteria": [f"Defines {title.lower()}"],
        "prerequisites": [],
        "sources": sources,
        "key_terms": terms,
    }


PLAN = {
    "title": "Linear Algebra",
    "sections": [
        {
            "title": "Foundations",
            "topics": [
                topic("T1", "Linear systems", [0], [0], ["Gaussian", "elimination"]),
                topic("T2", "Vector spaces", [1], [1], ["vector", "space", "basis"]),
            ],
        }
    ],
    "notation": [{"symbol": "$V$", "meaning": "a vector space"}],
    "terminology": [{"term": "basis", "definition": "independent spanning set"}],
    "conventions": [],
}

SELECTION = {
    "selected": [{"candidate": 0, "role": "definition", "relevance": 5, "reason": "Defines it"}],
    "gaps": [],
}


def draft(content: str) -> dict:
    return {
        "blocks": [
            {"kind": "definition", "title": "Key idea", "content": content, "citations": [0, 7]},
            {"kind": "summary", "title": None, "content": "In short.", "citations": []},
        ]
    }


def passed(ok: bool, escalate: bool = False) -> dict:
    issue = {
        "block": 0,
        "kind": "unsupported_claim",
        "severity": "major",
        "detail": "Claim not in the evidence",
        "fix": "Remove it",
    }
    return {
        "passed": ok,
        "issues": [] if ok else [issue],
        "escalate": escalate,
        "escalation_reason": "Hard proof" if escalate else None,
    }


Calls = list[tuple[str, str, dict]]


def model_stub(verify: Callable[[str, str], dict] | None = None) -> tuple[Callable, Calls]:
    """OpenRouter stand-in answering by schema name; records (schema, model, reasoning)."""
    calls: Calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        name = body["response_format"]["json_schema"]["name"]
        prompt = json.dumps(body["messages"])
        calls.append((name, body["model"], body.get("reasoning")))
        if name == "topic_draft":
            answer = draft("REVISED text" if "Previous draft" in prompt else "First text")
        elif name == "topic_verification":
            answer = (verify or (lambda m, p: passed("REVISED" in p)))(body["model"], prompt)
        else:
            answer = {
                "course_plan": PLAN,
                "coverage_review": {"approved": True, "issues": []},
                "evidence_selection": SELECTION,
                "consistency_edits": {
                    "edits": [
                        {"block": "T1.2", "content": "Harmonized summary.", "reason": "x"},
                        {"block": "T9.1", "content": "Not in the batch", "reason": "x"},
                    ]
                },
            }[name]
        return httpx2.Response(
            200,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": json.dumps(answer)}}],
            },
        )

    return handler, calls


@pytest.fixture
def no_quarto(tmp_uploads: Path):
    settings = WorkerSettings(uploads_dir=tmp_uploads, quarto_bin="no-such-quarto-binary")
    worker_app.dependency_overrides[get_worker_settings] = lambda: settings
    yield tmp_uploads


@pytest.fixture
def fake_quarto(tmp_uploads: Path, tmp_path_factory: pytest.TempPathFactory):
    """A `quarto` that writes a PDF next to the document, except for topic T2."""
    script = tmp_path_factory.mktemp("bin") / "quarto"
    script.write_text(
        "#!/bin/sh\n"
        'case "$PWD" in */T2/*) echo "typst error" && exit 1;; esac\n'
        'printf "%%PDF-1.4 %s" "$2" > "${2%.qmd}.pdf"\n'
    )
    script.chmod(0o755)
    settings = WorkerSettings(uploads_dir=tmp_uploads, quarto_bin=str(script))
    worker_app.dependency_overrides[get_worker_settings] = lambda: settings
    yield tmp_uploads


# Inputs


def test_split_text_keeps_pieces_under_the_limit() -> None:
    text = "\n".join(["short line"] * 300 + ["x" * 3000])
    pieces = split_text(text)
    assert all(len(p) <= 1400 for p in pieces)
    assert "".join(p.replace("\n", "") for p in pieces) == text.replace("\n", "")


def test_retriever_ranks_matching_chunks_and_respects_scope() -> None:
    chunks = [
        Chunk(id=f"c{i}", source=i, file="f", pdf_page=None, printed_page=None, text=text)
        for i, text in enumerate(BOOK_PAGES)
    ]
    retriever = Retriever(chunks)

    assert [c.id for c in retriever.search("vector space basis", 2)] == ["c3", "c2"]
    assert [c.id for c in retriever.search("vector space", 5, {"c0", "c2"})] == ["c2"]
    assert retriever.search("matrices", 5) == []


def test_build_inputs_reads_excerpt_pages_from_the_book(tmp_path: Path) -> None:
    course(tmp_path)
    plan = Plan.model_validate_json((tmp_path / "1/plan.json").read_text())
    transcript = Transcript.model_validate_json(
        (tmp_path / "1/syllabus/s.pdf.transcript.json").read_text()
    )

    inputs = build_inputs(tmp_path, tmp_path / "1", plan, transcript)

    book, handout = inputs.sources
    assert (book.file, book.title, book.sessions) == (
        "1/reading/book.pdf",
        "Hefferon. Linear Algebra.",
        [0],
    )
    assert [c.pdf_page for c in inputs.chunks if c.source == 0] == [1, 2]
    assert inputs.chunks[0].id.endswith("-p1-0")
    assert inputs.chunks[0].printed_page is None
    assert "Gaussian elimination" in inputs.chunks[0].text
    assert (handout.file, handout.sessions, handout.pdf_start) == (
        "1/reading/handout.md",
        [1],
        None,
    )
    (book_cache,) = [
        json.loads(f.read_text())
        for f in (tmp_path / "1/text").glob("*.json")
        if json.loads(f.read_text())["count"] == len(BOOK_PAGES)
    ]
    assert sorted(book_cache["pages"]) == ["1", "2"]

    again = build_inputs(tmp_path, tmp_path / "1", plan, transcript)
    assert [c.id for c in again.chunks] == [c.id for c in inputs.chunks]


# The run


@pytest.fixture
def legacy_notes(tmp_path: Path):
    run = "20261001-000000-abcd"
    payload = {
        "course": "1",
        "run": run,
        "title": "Linear Algebra",
        "created_at": "2026-10-01T00:00:00+00:00",
        "sections": [
            {
                "title": "Foundations",
                "topics": [
                    {
                        "topic_id": "T1",
                        "title": "Linear systems",
                        "status": "verified",
                        "blocks": [
                            {
                                "id": "T1.1",
                                "kind": "definition",
                                "title": None,
                                "content": "Row operations preserve solutions.",
                                "citations": ["book-p1-0", "book-p2-0"],
                            },
                            {
                                "id": "T1.2",
                                "kind": "summary",
                                "title": None,
                                "content": "Use elimination.",
                                "citations": [],
                            },
                        ],
                        "evidence": [
                            {
                                "chunk_id": "book-p1-0",
                                "source": 0,
                                "title": "Linear Algebra",
                                "page": "10",
                                "role": "definition",
                                "relevance": 5,
                                "reason": "Defines the row operation",
                                "text": "Row operations preserve solutions.",
                            }
                        ],
                        "rounds": 1,
                        "verifier": "test/model",
                        "open_issues": [],
                    }
                ],
            }
        ],
        "sources": [
            {
                "id": 0,
                "file": "1/reading/book.pdf",
                "title": "Linear Algebra",
                "label": "Ch. 1",
                "pdf_start": 1,
                "pdf_end": 2,
                "sessions": [0],
                "outline": ["Linear systems"],
                "chunk_ids": ["book-p1-0", "book-p2-0"],
            }
        ],
        "notation": [],
        "terminology": [],
        "models": {"generator": "test/model"},
    }
    target = tmp_path / "1/notes" / run / "notes.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(payload))
    return tmp_path / "1", run, target, payload


def test_legacy_notes_load_without_losing_ids(legacy_notes) -> None:
    directory, run, target, payload = legacy_notes
    before = target.read_bytes()
    expected = [
        (topic["topic_id"], block["id"], block["citations"])
        for section in payload["sections"]
        for topic in section["topics"]
        for block in topic["blocks"]
    ]

    document = load_document(directory, run)

    assert document is not None
    assert [
        (topic.topic_id, block.id, block.citations)
        for section in document.sections
        for topic in section.topics
        for block in topic.blocks
    ] == expected
    assert document.schema_version == 1
    assert document.language is None
    assert document.sections[0].topics[0].verification_stale is False
    assert document.sections[0].topics[0].objectives == []
    assert [source.model_dump() for source in document.sources] == payload["sources"]
    assert [item.model_dump() for item in document.sections[0].topics[0].evidence] == (
        payload["sections"][0]["topics"][0]["evidence"]
    )
    assert target.read_bytes() == before


@pytest.mark.parametrize("language", ["uk", "en"])
def test_legacy_notes_recover_language_from_primary_transcript(legacy_notes, language) -> None:
    directory, run, target, _ = legacy_notes
    course(directory.parent)
    path = directory / "syllabus/s.pdf.transcript.json"
    transcript = Transcript.model_validate_json(path.read_text())
    put_transcript(directory.parent, transcript.model_copy(update={"language": language}))
    before = target.read_bytes()

    document = load_document(directory, run)

    assert document is not None
    assert document.language == language
    assert document.schema_version == 1
    assert target.read_bytes() == before


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "invalid",
        "invalid_utf8",
        "unsupported",
        "invalid_plan",
        "invalid_utf8_plan",
        "other_course",
        "traversal",
    ],
)
def test_legacy_notes_keep_unknown_language_when_transcript_unavailable(legacy_notes, case) -> None:
    directory, run, target, _ = legacy_notes
    course(directory.parent)
    transcript_path = directory / "syllabus/s.pdf.transcript.json"
    if case == "missing":
        transcript_path.unlink()
    elif case == "invalid":
        transcript_path.write_text("not JSON")
    elif case == "invalid_utf8":
        transcript_path.write_bytes(b'{"language": "\xff\xfe"}')
    elif case == "invalid_utf8_plan":
        (directory / "plan.json").write_bytes(b'{"primary": "\xff\xfe"}')
    elif case == "unsupported":
        transcript = Transcript.model_validate_json(transcript_path.read_text())
        put_transcript(directory.parent, transcript.model_copy(update={"language": "fr"}))
    elif case == "invalid_plan":
        (directory / "plan.json").write_text("not JSON")
    else:
        primary = "2/syllabus/s.pdf" if case == "other_course" else "1/syllabus/../../s.pdf"
        external = directory.parent / f"{primary}.transcript.json"
        external.parent.mkdir(parents=True, exist_ok=True)
        external.write_bytes(transcript_path.read_bytes())
        put_plan(directory.parent, "1", Plan(primary=primary))
    before = target.read_bytes()

    document = load_document(directory, run)

    assert document is not None
    assert document.language is None
    assert target.read_bytes() == before


def test_version_two_unknown_language_does_not_inherit_current_transcript(legacy_notes) -> None:
    directory, run, target, payload = legacy_notes
    course(directory.parent)
    target.write_text(json.dumps(payload | {"schema_version": 2, "language": None}))

    document = load_document(directory, run)

    assert document is not None
    assert document.language is None


def test_generated_notes_persist_language(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    transcript_path = no_quarto / "1/syllabus/s.pdf.transcript.json"
    transcript = Transcript.model_validate_json(transcript_path.read_text())
    put_transcript(no_quarto, transcript.model_copy(update={"language": "uk"}))
    handler, _ = model_stub()
    client = mock_openrouter(handler)

    response = client.post("/plans/1/notes")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["run"]["status"] == "done"
    assert body["document"]["language"] == "uk"
    assert body["document"]["schema_version"] == 2
    saved = json.loads((no_quarto / "1/notes" / body["run"]["id"] / "notes.json").read_text())
    assert saved["language"] == "uk"
    assert saved["schema_version"] == 2
    # Once persisted, the document language does not follow a changed course transcript.
    put_transcript(no_quarto, transcript)
    reloaded = client.get(f"/plans/1/notes/{body['run']['id']}").json()["document"]
    assert reloaded["language"] == "uk"


def test_generate_notes_runs_every_stage_with_its_model(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    handler, calls = model_stub()
    client = mock_openrouter(handler)

    response = client.post("/plans/1/notes")
    assert response.status_code == 202, response.text
    body = response.json()
    run = body["run"]
    assert run["status"] == "done", run
    assert run["topics_total"] == run["topics_done"] == 2
    assert any("PDF not rendered" in w for w in run["warnings"])
    assert body["pdf"] is False
    assert body["topic_pdfs"] == []

    models = {name: (model, reasoning) for name, model, reasoning in calls}
    assert models["course_plan"] == ("openai/gpt-6.1-sol", {"effort": "medium"})
    assert models["coverage_review"] == ("openai/gpt-6.1-sol", {"effort": "high"})
    assert models["evidence_selection"] == ("openai/gpt-6-luna", {"effort": "low"})
    assert models["topic_draft"] == ("google/gemini-3.7-flash", {"effort": "medium"})
    assert models["topic_verification"] == ("openai/gpt-6-luna", {"effort": "high"})
    assert models["consistency_edits"] == ("google/gemini-3.7-flash", {"effort": "medium"})
    names = [c[0] for c in calls]
    assert names.count("topic_draft") == 4
    assert names.count("topic_verification") == 5  # includes the changed full topic

    document = NotesDocument.model_validate(body["document"])
    notes = document.sections[0].topics
    assert [n.topic_id for n in notes] == ["T1", "T2"]
    assert all(n.status == "verified" for n in notes)
    assert [n.rounds for n in notes] == [3, 2]
    assert notes[0].blocks[0].content == "REVISED text"
    assert notes[0].blocks[1].content == "Harmonized summary."
    assert notes[0].blocks[0].citations == [notes[0].evidence[0].chunk_id]

    folder = no_quarto / "1/notes" / run["id"]
    for name in ["inputs.json", "plan.json", "plan/draft-1.json", "plan/review-1.json"]:
        assert (folder / name).is_file(), name
    for name in [
        "evidence.json",
        "draft-1.json",
        "verification-1.json",
        "draft-2.json",
        "note.json",
    ]:
        assert (folder / "topics/T1" / name).is_file(), name
    first = json.loads((folder / "topics/T1/verification-1.json").read_text())
    assert first["passed"] is False and first["model"] == "openai/gpt-6-luna"

    qmd = (folder / "notes.qmd").read_text()
    assert 'title: "Linear Algebra"' in qmd
    assert "  typst:" in qmd
    assert "# Foundations" in qmd and "## Linear systems" in qmd
    assert ":::: {.callout-note}\n## Definition: Key idea" in qmd
    assert "citeproc: true" in qmd and "[@src-0, PDF p. 1]" in qmd
    references = json.loads(
        next(line[12:] for line in qmd.splitlines() if line.startswith("references: "))
    )
    assert {"id": "src-0", "type": "document", "title": "Hefferon. Linear Algebra."} in references
    assert "*Sources:" not in qmd

    topic_qmd = (folder / "topics/T2/note.qmd").read_text()
    assert 'title: "Vector spaces"' in topic_qmd
    assert 'subtitle: "Foundations · Linear Algebra"' in topic_qmd
    assert "toc: false" in topic_qmd and "# Foundations" not in topic_qmd
    assert "Linear systems" not in topic_qmd and "Notation" not in topic_qmd
    assert "[@src-1]" in topic_qmd and '"title": "handout.md"' in topic_qmd

    listed = client.get("/plans/1/notes").json()
    assert [r["id"] for r in listed] == [run["id"]]
    assert client.get(f"/plans/1/notes/{run['id']}").json()["run"]["status"] == "done"
    assert client.get(f"/plans/1/notes/{run['id']}/qmd").text == qmd
    assert client.get(f"/plans/1/notes/{run['id']}/pdf").status_code == 404
    assert client.get(f"/plans/1/notes/{run['id']}/topics/T1/pdf").status_code == 404
    assert client.get("/plans/1/notes/20990101-000000-abcd").status_code == 404


def test_each_topic_gets_its_own_pdf(mock_openrouter, fake_quarto: Path) -> None:
    course(fake_quarto)
    handler, _ = model_stub()
    client = mock_openrouter(handler)

    body = client.post("/plans/1/notes").json()
    run = body["run"]["id"]
    assert body["pdf"] is True
    assert body["topic_pdfs"] == ["T1"]
    assert any(w.startswith("PDF of T2 not rendered") for w in body["run"]["warnings"])

    pdf = client.get(f"/plans/1/notes/{run}/topics/T1/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert 'inline; filename="notes-T1.pdf"' in pdf.headers["content-disposition"]
    assert pdf.content == b"%PDF-1.4 note.qmd"
    folder = fake_quarto / "1/notes" / run
    artifacts = json.loads((folder / "artifacts.json").read_text())
    assert len(artifacts) == 6
    assert all(a["revision"] == 0 for a in artifacts)
    assert {(a["format"], a["topic_id"]) for a in artifacts if a["status"] == "ready"} == {
        ("pdf", None),
        ("pdf", "T1"),
    }
    assert all(not a["path"].startswith("/") for a in artifacts)
    assert any(a["path"] == "topics/T1/note.pdf" for a in artifacts)
    assert (folder / "sources/html/notes.qmd").is_file()
    assert client.get(f"/plans/1/notes/{run}/topics/T2/pdf").status_code == 404
    assert client.get(f"/plans/1/notes/{run}/topics/T9/pdf").status_code == 404
    assert client.get(f"/plans/1/notes/{run}/topics/..%2F..%2Frun.json/pdf").status_code == 404


def test_verifier_escalates_to_astra(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)

    def verify(model: str, prompt: str) -> dict:
        return passed(ok=model == "openai/gpt-6.1-sol", escalate=model != "openai/gpt-6.1-sol")

    handler, calls = model_stub(verify)
    run = mock_openrouter(handler).post("/plans/1/notes").json()["run"]

    verifiers = [model for name, model, _ in calls if name == "topic_verification"]
    assert sorted(verifiers) == ["openai/gpt-6-luna"] * 3 + ["openai/gpt-6.1-sol"] * 3
    note = TopicNote.model_validate_json(
        (no_quarto / "1/notes" / run["id"] / "topics/T1/note.json").read_text()
    )
    assert (note.status, note.rounds, note.verifier) == ("verified", 1, "openai/gpt-6.1-sol")


def test_unresolved_topic_is_kept_with_its_open_issues(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    handler, calls = model_stub(lambda model, prompt: passed(False))
    body = mock_openrouter(handler).post("/plans/1/notes").json()

    note = NotesDocument.model_validate(body["document"]).sections[0].topics[0]
    assert note.status == "unresolved"
    assert note.rounds == 4
    assert note.verifier == "openai/gpt-6-luna"  # fresh composition check
    assert [i.kind for i in note.open_issues] == ["unsupported_claim"]
    verifiers = [m for name, m, _ in calls if name == "topic_verification"]
    assert verifiers.count("openai/gpt-6.1-sol") == 2


def test_resume_reuses_the_plan_and_finished_topics(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    handler, calls = model_stub()
    client = mock_openrouter(handler)
    run = client.post("/plans/1/notes").json()["run"]
    folder = no_quarto / "1/notes" / run["id"]
    published = (folder / "notes.json").read_bytes()

    # A completed run's published notes are never regenerated in place.
    completed = client.post("/plans/1/notes", json={"resume": run["id"]})
    assert completed.status_code == 409
    assert "new run" in completed.json()["detail"]
    assert (folder / "notes.json").read_bytes() == published

    # A failed run that never published its notes stays resumable.
    failed = json.loads((folder / "run.json").read_text()) | {"status": "failed"}
    (folder / "run.json").write_text(json.dumps(failed))
    (folder / "topics/T2/note.json").unlink()
    calls.clear()

    again = client.post("/plans/1/notes", json={"resume": run["id"]}).json()["run"]

    assert again["id"] == run["id"] and again["status"] == "done"
    names = [c[0] for c in calls]
    assert "course_plan" not in names
    assert names.count("evidence_selection") == 1


def test_failed_model_call_fails_only_that_topic(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    stub, _ = model_stub()

    def handler(request: httpx2.Request) -> httpx2.Response:
        if b"Vector spaces" in request.content and b"evidence_selection" in request.content:
            return httpx2.Response(500, json={"error": {"message": "boom"}})
        return stub(request)

    run = mock_openrouter(handler).post("/plans/1/notes").json()
    notes = NotesDocument.model_validate(run["document"]).sections[0].topics
    assert [n.status for n in notes] == ["verified", "failed"]
    assert notes[1].error == "The model request failed"
    assert any("T2" in w for w in run["run"]["warnings"])


def test_generate_notes_preconditions(mock_openrouter, no_quarto: Path) -> None:
    handler, _ = model_stub()
    client = mock_openrouter(handler)
    assert client.post("/plans/1/notes").status_code == 409

    course(no_quarto)
    ACTIVE.add("1")
    try:
        response = client.post("/plans/1/notes")
        assert response.status_code == 409
        assert response.json()["detail"] == "Notes are already being generated"
    finally:
        ACTIVE.discard("1")
    assert client.post("/plans/1/notes", json={"resume": "20990101-000000-abcd"}).status_code == 404


def test_model_spec_parameters() -> None:
    assert ModelSpec("m", "high", 100).parameters() == {
        "max_tokens": 100,
        "reasoning": {"effort": "high"},
    }
    assert ModelSpec("m").parameters()["reasoning"] == {"enabled": True}


def test_evidence_gaps_do_not_block_the_plan(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    stub, calls = model_stub()
    gap = {
        "approved": False,
        "issues": [
            {
                "kind": "weak_evidence",
                "severity": "blocking",
                "topics": ["T2"],
                "detail": "No material covers inner products",
                "fix": "Add a source",
            }
        ],
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        if b'"coverage_review"' in request.content:
            content = json.dumps(gap)
            return httpx2.Response(200, json={"choices": [{"message": {"content": content}}]})
        return stub(request)

    run = mock_openrouter(handler).post("/plans/1/notes").json()["run"]

    assert run["status"] == "done"
    assert [c[0] for c in calls].count("course_plan") == 1
    assert any(
        "Thin evidence for T2: No material covers inner products" in w for w in run["warnings"]
    )


def test_restart_fails_interrupted_runs(mock_openrouter, no_quarto: Path) -> None:
    course(no_quarto)
    handler, _ = model_stub()
    client = mock_openrouter(handler)
    run = client.post("/plans/1/notes").json()["run"]
    target = no_quarto / "1/notes" / run["id"] / "run.json"
    stale = json.loads(target.read_text()) | {"status": "running", "stage": "topics"}
    target.write_text(json.dumps(stale))

    assert fail_interrupted(no_quarto) == [f"1/{run['id']}"]
    assert fail_interrupted(no_quarto) == []

    after = client.get(f"/plans/1/notes/{run['id']}").json()["run"]
    assert after["status"] == "failed"
    assert "worker restart" in after["error"]
    assert (
        client.post("/plans/1/notes", json={"resume": run["id"]}).json()["run"]["status"] == "done"
    )


@pytest.mark.parametrize(
    ("source", "safe"),
    [
        (r"$0=(0,0,0)^T\notin P$", r"$0=(0,0,0)^{T}{}\notin P$"),
        (r"$A_{\rm red}x=0$", r"$A_{\mathrm{red}}{}x=0$"),
        (r"$[v]_\mathcal{B} = [v]_\mathcal C$", r"$[v]_{\mathcal{B}}{} = [v]_{\mathcal C}$"),
        (r"$(a)^\top b$", r"$(a)^{\top}{} b$"),
        (r"$$\sum_{i=1}^{n} x_i$$", r"$$\sum_{i=1}^{n}{} x_{i}$$"),
        (r"$e^\frac{1}{2}$ and $x_{\{1\}}$", r"$e^\frac{1}{2}$ and $x_{\{1\}}$"),
        ("costs 5 a_b", "costs 5 a_b"),
    ],
)
def test_typst_safe_math(source: str, safe: str) -> None:
    assert typst_safe(source) == safe


def test_block_titles_keep_lists_and_single_qed() -> None:
    text = labels("en")

    def render(kind: str, title: str | None, content: str) -> str:
        block = NoteBlock(id="T1.1", kind=kind, title=title, content=content, citations=[])
        return block_markdown(block, text, "")

    assert "## Summary\n\n- one\n- two" in render("summary", "Summary", "- one\n- two")
    assert "## Proof\n\nDone. ∎" in render("proof", None, "Done. ∎")
    assert "square" not in render("proof", None, "Done. ∎")
    assert "Trivial. $\\square$" in render("proof", None, "Trivial.")


def test_topic_without_example_reports_gap_when_objective_requires_one(legacy_notes) -> None:
    from app.worker.topics import topic_structure_issues

    directory, run, _, _ = legacy_notes
    note = load_document(directory, run).sections[0].topics[0]
    assert topic_structure_issues(note) == []
    note.objectives = ["Give a worked example of a row operation"]
    assert any("example" in issue.lower() for issue in topic_structure_issues(note))
    assert not any("theorem" in issue.lower() for issue in topic_structure_issues(note))


def response_with(answer: dict) -> httpx2.Response:
    return httpx2.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})


def test_structure_does_not_invent_unsupported_definition(mock_openrouter, no_quarto) -> None:
    import copy

    course(no_quarto)
    stub, _ = model_stub(lambda m, p: passed(True))
    plan = copy.deepcopy(PLAN)
    plan["sections"][0]["topics"][0]["objectives"] = ["Define row equivalence"]

    def handler(request):
        name = json.loads(request.content)["response_format"]["json_schema"]["name"]
        if name == "course_plan":
            return response_with(plan)
        if name == "evidence_selection":
            return response_with(SELECTION | {"gaps": ["No definition of row equivalence"]})
        if name == "topic_draft":
            return response_with(
                {
                    "blocks": [
                        {
                            "kind": "overview",
                            "title": None,
                            "content": "The material discusses row operations.",
                            "citations": [0],
                        }
                    ]
                }
            )
        return stub(request)

    body = mock_openrouter(handler).post("/plans/1/notes").json()
    note = body["document"]["sections"][0]["topics"][0]
    assert note["objectives"] == ["Define row equivalence"]
    assert [block["kind"] for block in note["blocks"]] == ["overview"]
    assert note["status"] == "unresolved"
    assert any("definition" in issue["detail"].lower() for issue in note["open_issues"])
    assert any(
        issue["detail"] == "No definition of row equivalence" for issue in note["open_issues"]
    )


def test_harmonization_preserves_reference_ids_and_citations(mock_openrouter, no_quarto) -> None:
    from app.worker.references import reference_id

    course(no_quarto)
    stub, _ = model_stub(lambda m, p: passed(True))
    original = "A solution satisfies $Ax=b$. See [@src-0].\n\n$$x=1$$ {#eq-answer}"
    changed = original.replace("A solution", "Every solution")

    def handler(request):
        name = json.loads(request.content)["response_format"]["json_schema"]["name"]
        if name == "topic_draft":
            return response_with(draft(original))
        if name == "consistency_edits":
            return response_with(
                {"edits": [{"block": "T1.1", "content": changed, "reason": "clarity"}]}
            )
        return stub(request)

    body = mock_openrouter(handler).post("/plans/1/notes").json()
    note = body["document"]["sections"][0]["topics"][0]
    block = note["blocks"][0]
    assert block["id"] == "T1.1" and block["content"] == changed
    assert block["citations"] == [note["evidence"][0]["chunk_id"]]
    assert reference_id(note["topic_id"], block["id"]) == "sec-T1--T1_2e_1"
    assert note["objectives"] == ["Explain linear systems"]
    assert note["status"] == "verified" and not note["verification_stale"]


@pytest.mark.parametrize(
    "mutation",
    ["formula", "equation", "figure", "table", "citation", "locator", "narrative_locator"],
)
def test_harmonization_rejects_changes_to_protected_content(mock_openrouter, no_quarto, mutation):
    course(no_quarto)
    stub, _ = model_stub(lambda m, p: passed(True))
    original = (
        "A solution satisfies $Ax=b$. See [@src-0, p. 10].\n\n"
        "Narrative @src-0 [p. 20] explains.\n\n$$x=1$$ {#eq-answer}\n\n"
        "![Diagram](assets/diagram.png){#fig-diagram}\n\n"
        "| x | y |\n|---|---|\n| 1 | 2 |\n\n: Values {#tbl-values}"
    )
    before, after = {
        "formula": ("Ax=b", "Ax=0"),
        "equation": ("eq-answer", "eq-renamed"),
        "figure": ("fig-diagram", "fig-renamed"),
        "table": ("tbl-values", "tbl-renamed"),
        "citation": ("[@src-0, p. 10]", ""),
        "locator": ("p. 10", "p. 999"),
        "narrative_locator": ("p. 20", "p. 999"),
    }[mutation]

    def handler(request):
        name = json.loads(request.content)["response_format"]["json_schema"]["name"]
        if name == "topic_draft":
            return response_with(draft(original))
        if name == "consistency_edits":
            return response_with(
                {
                    "edits": [
                        {
                            "block": "T1.1",
                            "content": original.replace(before, after),
                            "reason": "rewrite",
                        }
                    ]
                }
            )
        return stub(request)

    body = mock_openrouter(handler).post("/plans/1/notes").json()
    assert body["document"]["sections"][0]["topics"][0]["blocks"][0]["content"] == original


@pytest.mark.parametrize("outcome", ["major", "error", "pass"])
def test_harmonized_text_gets_fresh_full_topic_verification(mock_openrouter, no_quarto, outcome):
    course(no_quarto)
    stub, _ = model_stub(lambda m, p: passed(True))
    checked = []

    def handler(request):
        body = json.loads(request.content)
        name = body["response_format"]["json_schema"]["name"]
        prompt = json.dumps(body["messages"])
        if name == "topic_verification" and "Harmonized summary." in prompt:
            checked.append(prompt)
            if outcome == "error":
                return httpx2.Response(500, json={"error": {"message": "Unavailable"}})
            return response_with(passed(outcome == "pass"))
        return stub(request)

    body = mock_openrouter(handler).post("/plans/1/notes").json()
    note = body["document"]["sections"][0]["topics"][0]
    assert checked, "The displayed changed topic must be checked again"
    assert "First text" in checked[0] and "E0" in checked[0] and "Terminology" in checked[0]
    assert note["blocks"][1]["content"] == "Harmonized summary."
    assert note["status"] == ("verified" if outcome == "pass" else "unresolved")
    assert note["verification_stale"] == (outcome == "error")
    if outcome == "major":
        assert any(i["kind"] == "unsupported_claim" for i in note["open_issues"])


@pytest.mark.parametrize(
    "kind",
    [
        "overview",
        "definition",
        "theorem",
        "proof",
        "example",
        "intuition",
        "explanation",
        "remark",
        "summary",
    ],
)
def test_every_block_kind_has_localized_callout(kind):
    block = NoteBlock(
        id="T1.1", kind=kind, title=None, content="Supported explanation.", citations=[]
    )
    for language in ("uk", "en"):
        text = labels(language)
        result = block_markdown(block, text, "[@src-0]", target="html")
        assert ".callout-" in result and f"## {text[kind]}" in result
        assert "[@src-0]" in result


def test_long_proof_folds_only_in_html():
    block = NoteBlock(
        id="T1.1", kind="proof", title=None, content="A proof step. " * 150, citations=[]
    )
    html = block_markdown(block, labels("uk"), "", target="html")
    pdf = block_markdown(block, labels("uk"), "", target="pdf")
    assert 'collapse="true"' in html and 'collapse="true"' not in pdf
    assert block.content.strip() in html and block.content.strip() in pdf


def test_fresh_harmonization_check_keeps_structure_and_evidence_gaps(mock_openrouter, no_quarto):
    import copy

    course(no_quarto)
    stub, _ = model_stub(lambda m, p: passed(True))
    plan = copy.deepcopy(PLAN)
    plan["sections"][0]["topics"][0]["objectives"] = ["Give a worked example"]

    def handler(request):
        name = json.loads(request.content)["response_format"]["json_schema"]["name"]
        if name == "course_plan":
            return response_with(plan)
        if name == "evidence_selection":
            return response_with(SELECTION | {"gaps": ["No supported worked example"]})
        return stub(request)

    client = mock_openrouter(handler)
    body = client.post("/plans/1/notes").json()
    note = body["document"]["sections"][0]["topics"][0]
    assert note["blocks"][1]["content"] == "Harmonized summary."
    assert note["status"] == "unresolved" and not note["verification_stale"]
    assert {i["kind"] for i in note["open_issues"]} == {"citation", "missing_objective"}
    # Reading a saved note must not inherit a later plan's objectives.
    path = no_quarto / "1/notes" / body["run"]["id"] / "plan.json"
    path.write_text(json.dumps(PLAN))
    reloaded = client.get(f"/plans/1/notes/{body['run']['id']}").json()
    assert reloaded["document"]["sections"][0]["topics"][0]["objectives"] == [
        "Give a worked example"
    ]


def study_note_document(language):
    from app.notes import VerificationIssue
    from tests.test_notes_references import cited_document

    document = cited_document()
    document.language = language
    document.title = "Лінійна алгебра" if language == "uk" else "Linear algebra"
    document.sections[0].title = "Основи" if language == "uk" else "Foundations"
    note = document.sections[0].topics[0]
    note.title = "Розв'язки систем" if language == "uk" else "Solutions of systems"
    note.objectives = ["Define a solution and give an example"]
    note.blocks = [
        NoteBlock(id=f"T1.{index}", kind=kind, title=None, content=content, citations=["c1"])
        for index, (kind, content) in enumerate(
            [
                ("intuition", "We seek a value that makes both sides equal."),
                ("definition", "A solution of $x+1=3$ is a value satisfying the equality."),
                ("example", "Substitute $x=2$: $2+1=3$."),
                ("summary", "Check a solution by substitution."),
                ("proof", "Subtracting one preserves equality. " * 60 + "Therefore $x=2$."),
            ],
            1,
        )
    ]
    note.status = "unresolved"
    note.open_issues = [
        VerificationIssue(
            block=2,
            kind="citation",
            severity="major",
            detail="Further examples need course evidence.",
            fix="Add a supporting reading.",
        )
    ]
    return document


@pytest.mark.parametrize("language", ["en", "uk"])
def test_native_study_topic_html_pdf_with_sources(tmp_path, monkeypatch, language):
    import asyncio
    import os
    import re
    from unittest.mock import AsyncMock

    from pypdf import PdfReader

    from app.worker.openrouter import OpenRouterClient
    from app.worker.quarto import render_document
    from app.worker.render import topic_to_quarto

    binary = os.environ.get("QUARTO_TEST_BIN")
    if not binary:
        pytest.skip("Set QUARTO_TEST_BIN for native study-topic HTML/PDF controls")
    llm = AsyncMock(side_effect=AssertionError("Rendering must not call an LLM"))
    monkeypatch.setattr(OpenRouterClient, "complete_json", llm)
    document = study_note_document(language)
    section = document.sections[0]
    sources = {}
    for target in ("html", "pdf"):
        source = tmp_path / target / "study.qmd"
        source.parent.mkdir()
        source.write_text(topic_to_quarto(document, section, section.topics[0], "en", target))
        assert source.read_text().count("[@src-1, p. 10]") == 5
        sources[target] = source
    output = tmp_path / "output"
    result = asyncio.run(render_document(sources, output, 0, binary))
    assert all(a.status == "ready" for a in result), [a.model_dump() for a in result]
    html = (output / "study.html").read_text()
    pdf_text = " ".join(page.extract_text() for page in PdfReader(output / "study.pdf").pages)
    main = re.search(r"<main[\s\S]*?</main>", html)[0]
    html_text = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", main))
    assert not any(0xE000 <= ord(char) <= 0xF8FF for char in pdf_text)
    pdf_text = re.sub(r"(?<=[A-Za-z])\s*-\s*(?=[A-Za-z])", "", pdf_text)
    pdf_text = re.sub(r"\s+", " ", pdf_text)
    for text in (html_text, pdf_text):
        assert all(
            labels(language)[kind] in text for kind in ("definition", "example", "summary", "proof")
        )
        assert labels(language)["unverified"] in text
        assert "Further examples need course evidence." in text
        assert "Check a solution by substitution." in text
        assert text.count("Subtracting one preserves equality.") == 60
        assert "known textbook" in text.lower()
        assert re.search(r"known textbook.{0,30}, (?:p\. )?10\)", text, re.I)
    assert "callout-collapse collapse" in html
    assert not llm.called


def test_proof_folding_allows_only_controlled_callout_attribute():
    from app.worker.quarto import QuartoError, validate_markdown

    validate_markdown(':::: {.callout-note collapse="true"}\n## Proof\n\nBody.\n::::')
    for attributes in (
        'collapse="false"',
        'collapse="true" onclick="alert(1)"',
        'style="color:red"',
    ):
        with pytest.raises(QuartoError):
            validate_markdown(f":::: {{.callout-note {attributes}}}\nBody\n::::")


@pytest.mark.parametrize(
    "before,after,allowed",
    [
        ("As @src-0 [p. 10] explains.", "As @src-0 [p. 999] explains.", False),
        ("As @src-0 [p. 10] explains.", "As @src-0 explains.", False),
        ("As @src-0 explains.", "As @src-0 [p. 999] explains.", False),
        ("As @src-0 [p. 10] explains.", "Following @src-0 [p. 10], we conclude.", True),
        ("As @src-0 explains. Prose [one].", "Following @src-0 explains. Prose [two].", True),
        ("As @src-0\n[p. 10] explains.", "As @src-0\n[p. 999] explains.", False),
        ("As @src-0 [p.\n10] explains.", "As @src-0 [p.\n999] explains.", False),
        ("As @src-0\r\r [p. 10] explains.", "As @src-0\r\r [p. 999] explains.", False),
        ("As [@src-0, p. 10] explains.", "As [@src-0, p. 999] explains.", False),
        ("$x" + "\\" + "\r" + "$ Topic T2$", "$x" + "\\" + "\r" + "$ Topic T3$", False),
        ("$x\n\r\r\nTopic T2$", "$x\n\r\r\nTopic T3$", True),
    ],
)
def test_harmonization_preserves_narrative_locators_and_cr_math(before, after, allowed):
    from app.worker.composition import preserves_content

    assert preserves_content(before, after) is allowed


@pytest.mark.parametrize(
    "suffix",
    [
        "[see [discussion], p. 10]",
        r"[see \] discussion, p. 10]",
        "[see [outer [discussion]], p. 10]",
        r"[see \[discussion\], p. 10]",
        "[see `discussion`, p. 10]",
        "[see `]` discussion, p. 10]",
    ],
)
def test_complete_narrative_suffix_is_preserved(suffix):
    from app.worker.composition import preserves_content

    before = f"As @src-0 {suffix} explains."
    assert not preserves_content(before, before.replace("p. 10", "p. 999"))
    assert preserves_content(before, f"Following @src-0 {suffix}, we conclude.")
    # Even text inside a code span belongs to the associated citation suffix.
    assert not preserves_content(before, before.replace("discussion", "exposition"))


@pytest.mark.parametrize("suffix", ["[see [discussion], p. 10]", r"[see \] discussion, p. 10]"])
def test_harmonization_rejects_nested_narrative_page_mutation(mock_openrouter, no_quarto, suffix):
    course(no_quarto)
    stub, _ = model_stub(lambda m, p: passed(True))
    original = f"As @src-0 {suffix} explains."

    def handler(request):
        name = json.loads(request.content)["response_format"]["json_schema"]["name"]
        if name == "topic_draft":
            return response_with(draft(original))
        if name == "consistency_edits":
            return response_with(
                {
                    "edits": [
                        {
                            "block": "T1.1",
                            "content": original.replace("p. 10", "p. 999"),
                            "reason": "rewrite",
                        }
                    ]
                }
            )
        return stub(request)

    body = mock_openrouter(handler).post("/plans/1/notes").json()
    assert body["document"]["sections"][0]["topics"][0]["blocks"][0]["content"] == original
