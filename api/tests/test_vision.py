"""Vision transcription of book pages whose PDF text garbles formulas or has none."""

import asyncio
import json
import re
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.main import app
from app.plan import Plan
from app.storage import sha256
from app.syllabus import Transcript
from app.worker import vision
from app.worker.models import ModelSpec
from app.worker.openrouter import OpenRouterClient
from app.worker.sources import build_inputs, load_transcripts, loses_text
from tests.test_notes import course
from tests.test_plans import put_plan

PROSE = "Gaussian elimination reduces a linear system to an equivalent echelon form."
MATH = "Suppose T is an operator on V and lambda is an eigenvalue of T with T v = lambda v."
TRANSCRIBED = "If $T v = \\lambda v$ with $v \\neq \\mathbf{0}$, then $\\lambda$ is an eigenvalue."
SPEC = ModelSpec("vision/model", effort="low")


def book(path: Path, pages: list[tuple[str, str]]) -> None:
    """One text line per page, set in the named font (e.g. a TeX math font)."""
    writer = PdfWriter()
    for text, font_name in pages:
        font = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject(f"/{font_name}"),
                }
            )
        )
        page = writer.add_blank_page(400, 400)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 6 Tf 10 350 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        writer.write(f)


PAGES = [(PROSE, "Helvetica"), ("", "Helvetica"), (MATH, "CMMI10"), (PROSE, "Times-Roman")]


def model(failing: set[int] | None = None):
    """A vision model answering "Page N" for PDF page N; records the pages asked."""
    asked: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["name"] == "page_transcript"
        page = int(re.search(r"PDF page (\d+)", json.dumps(body["messages"])).group(1))
        asked.append(page)
        if page in (failing or set()):
            return httpx2.Response(500, json={"error": {"message": "down"}})
        content = json.dumps({"markdown": f"Page {page}: {TRANSCRIBED}"})
        return httpx2.Response(
            200, json={"model": "vision/model", "choices": [{"message": {"content": content}}]}
        )

    return handler, asked


def transcribe(root: Path, handler, spans=((1, 4),), spec: ModelSpec = SPEC):
    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            client = OpenRouterClient("https://openrouter.test/api/v1", "key", "m", http)
            file = root / "1/reading/book.pdf"
            return await vision.transcribe_pages(client, spec, root / "1", file, list(spans))

    return asyncio.run(run())


def test_loses_text_flags_scans_matrices_and_math_fonts(tmp_path: Path) -> None:
    book(tmp_path / "b.pdf", PAGES)
    pages = PdfReader(tmp_path / "b.pdf").pages
    text = [p.extract_text() for p in pages]

    assert [loses_text(p, t) for p, t in zip(pages, text, strict=True)] == [
        False,
        True,
        True,
        False,
    ]
    assert loses_text(pages[0], f"{PROSE}\n⎛ 1 0 ⎞")


def test_only_pages_that_need_it_are_read_once(tmp_path: Path) -> None:
    book(tmp_path / "1/reading/book.pdf", PAGES)
    handler, asked = model()

    assert transcribe(tmp_path, handler) == (2, [])
    assert sorted(asked) == [2, 3]
    digest = sha256(tmp_path / "1/reading/book.pdf")
    cached = load_transcripts(tmp_path / "1", digest)
    assert cached.key == "vision/model#1"
    assert cached.pages == {2: f"Page 2: {TRANSCRIBED}", 3: f"Page 3: {TRANSCRIBED}"}

    assert transcribe(tmp_path, handler) == (0, [])
    assert len(asked) == 2
    # Another model reads them again.
    assert transcribe(tmp_path, handler, spec=ModelSpec("other/model")) == (2, [])


def test_a_failed_page_is_read_next_time(tmp_path: Path) -> None:
    book(tmp_path / "1/reading/book.pdf", PAGES)
    handler, asked = model(failing={3})

    assert transcribe(tmp_path, handler) == (1, [3])
    handler, asked = model()
    assert transcribe(tmp_path, handler) == (1, [])
    assert asked == [3]


def excerpt_course(root: Path) -> tuple[Plan, Transcript]:
    """Course 1 of test_notes, its session s1 reading pages 1-4 of the book above."""
    course(root)
    book(root / "1/reading/book.pdf", PAGES)
    plan = Plan.model_validate_json((root / "1/plan.json").read_text())
    plan.proposals[0].pdf_end = 4
    put_plan(root, "1", plan)
    transcript = Transcript.model_validate_json(
        (root / "1/syllabus/s.pdf.transcript.json").read_text()
    )
    return plan, transcript


def test_notes_read_the_transcripts_and_warn_until_there_are_some(tmp_path: Path) -> None:
    plan, transcript = excerpt_course(tmp_path)

    before = build_inputs(tmp_path, tmp_path / "1", plan, transcript)
    assert before.skipped == [
        "1/reading/book.pdf: PDF page 2 of Ch. 1 has no extractable text (scanned or blank); "
        "the notes miss what is on them",
        "1/reading/book.pdf: PDF page 3 of Ch. 1 has formulas or matrices their PDF text "
        "garbles, and no vision transcription yet; the notes may misread them",
    ]

    transcribe(tmp_path, model()[0])
    after = build_inputs(tmp_path, tmp_path / "1", plan, transcript)

    assert after.skipped == []
    text = {c.pdf_page: c.text for c in after.chunks if c.source == 0}
    assert text[1] == PROSE and text[3] == f"Page 3: {TRANSCRIBED}"


def test_approving_an_excerpt_transcribes_its_pages(mock_openrouter, tmp_uploads: Path) -> None:
    excerpt_course(tmp_uploads)
    handler, asked = model()
    client = mock_openrouter(handler)
    session_id = client.get("/plans/1").json()["sessions"][0]["id"]

    response = client.post(
        f"/plans/1/sessions/{session_id}/excerpts",
        json={"path": "1/reading/book.pdf", "pdf_start": 3, "pdf_end": 4},
    )

    assert response.status_code == 200
    # Every approved excerpt of the course: the earlier one covers page 2 too.
    assert sorted(asked) == [2, 3]


def test_approving_without_a_model_still_works(tmp_uploads: Path) -> None:
    excerpt_course(tmp_uploads)
    client = TestClient(app)
    session_id = client.get("/plans/1").json()["sessions"][0]["id"]

    response = client.post(
        f"/plans/1/sessions/{session_id}/excerpts",
        json={"path": "1/reading/book.pdf", "pdf_start": 3, "pdf_end": 4},
    )

    assert response.status_code == 200
    assert not list((tmp_uploads / "1/text").glob("*.vision.json"))
