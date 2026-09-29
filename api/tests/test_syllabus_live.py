"""Live extraction checks against real syllabi. They call OpenRouter and cost money, so they
only run with `LIVE=1 uv run pytest tests/test_syllabus_live.py -s`."""

import asyncio
import os
import re
from pathlib import Path

import httpx2
import pytest

from app.config import Settings
from app.llm import strict_schema
from app.openrouter import OpenRouterClient
from app.syllabus import SyllabusExtraction, build_messages, drop_bad_refs

SYLLABI = Path(__file__).parents[2] / "test_sullabys"

pytestmark = pytest.mark.skipif(os.environ.get("LIVE") != "1", reason="set LIVE=1 to run")


def extract(path: Path) -> SyllabusExtraction:
    settings = Settings()
    assert settings.openrouter_api_key, "OPENROUTER_API_KEY is not set"

    async def run() -> str:
        async with httpx2.AsyncClient(timeout=180) as http:
            client = OpenRouterClient(
                settings.openrouter_url,
                settings.openrouter_api_key,
                settings.openrouter_model,
                http,
            )
            messages, plugins = build_messages(path)
            schema = strict_schema(SyllabusExtraction)
            return await client.complete_json(messages, "transcript", schema, plugins)

    extraction = SyllabusExtraction.model_validate_json(asyncio.run(run()))
    drop_bad_refs(extraction)
    return extraction


def dump(extraction: SyllabusExtraction) -> None:
    for s in extraction.sessions:
        readings = [(r.raw, r.material_ref) for r in s.required_readings + s.optional_readings]
        print(f"{s.label!r} | date={s.date!r} | {readings}")


def test_applied_linear_algebra_maps_materials_to_lectures() -> None:
    """Materials sit in a table column next to the lectures and cite a numbered book list
    ([1]-[4]); a separate week plan has the dates but no materials."""
    extraction = extract(SYLLABI / "Syllabus ALA_2026_online (1).pdf")
    dump(extraction)

    books = [m.raw for m in extraction.learning_materials]
    assert len(books) >= 4
    assert "Olver" in books[0] and "Strang" in books[3]

    lectures = {}
    for s in extraction.sessions:
        match = re.search(r"Lecture\s+(\d+)", s.label)
        if match:
            lectures[int(match.group(1))] = s
    assert sorted(lectures) == list(range(1, 16)), [s.label for s in extraction.sessions]

    def refs(n: int) -> set[int | None]:
        s = lectures[n]
        return {r.material_ref for r in s.required_readings + s.optional_readings}

    expected = {
        1: {0, 1, 3},
        2: {0},
        3: {0, 3},
        4: {0, 1, 3},
        5: {0, 1},
        8: {0, 1},
        9: {0},
        10: {0, 3},
        11: {0},
        12: {0},
        13: {0, 1},
        14: set(),
        15: set(),
    }
    wrong = {n: refs(n) for n, want in expected.items() if refs(n) != want}
    assert not wrong, f"material refs per lecture differ: {wrong}"

    # The one cell spanning lectures 6-7 ("[1] Chapter 8.2 ..., 8.3; [2] Chapter 8.2").
    assert refs(6) | refs(7) == {0, 1}

    assert lectures[1].label.strip(" .") == "Lecture 1"
    assert "SLE" in lectures[1].topic

    lecture1 = lectures[1].required_readings
    assert any("1.3" in (r.pages or r.raw) for r in lecture1)

    # Dates come from the week plan.
    assert lectures[1].date and "1.09" in lectures[1].date
    assert lectures[13].date and "16.11" in lectures[13].date


BOOK = SYLLABI / "books" / "hefferon.pdf"


def hefferon_course(root: Path, strip_bookmarks: bool) -> None:
    from pypdf import PdfReader, PdfWriter

    from app.plan import Plan
    from app.syllabus import Reading, Session, SessionReading, Transcript
    from tests.test_plans import put_plan, put_transcript

    book = root / "1/reading/jim_hefferon_linear_algebra.pdf"
    book.parent.mkdir(parents=True)
    if strip_bookmarks:
        writer = PdfWriter(clone_from=PdfReader(BOOK))
        writer._root_object.pop("/Outlines", None)
        with book.open("wb") as f:
            writer.write(f)
    else:
        book.write_bytes(BOOK.read_bytes())

    def cite(raw: str, pages: str) -> SessionReading:
        return SessionReading(
            raw=raw, title=None, authors=[], year=None, url=None, pages=pages, material_ref=1
        )

    def lecture(n: int, *readings: SessionReading) -> Session:
        return Session(
            label=f"Lecture {n}",
            number=n,
            date=None,
            topic="",
            subtopics=[],
            required_readings=list(readings),
            optional_readings=[],
        )

    def material(raw: str) -> Reading:
        return Reading(raw=raw, title=None, authors=[], year=None, url=None, pages=None)

    put_transcript(
        root,
        Transcript(
            language="en",
            learning_materials=[
                material("[1] Gilbert Strang. Linear Algebra and Its Applications."),
                material("[2] Jim Hefferon. Linear Algebra. 4th ed."),
            ],
            sessions=[
                lecture(1, cite("[2] Chapter One, Section I", "Chapter One, Section I")),
                lecture(2, cite("[2] pp. 100-110", "pp. 100-110")),
                lecture(3, cite("[2] Chapter Two", "Chapter Two")),
            ],
            notes=None,
            source_path="1/syllabus/s.pdf",
            source_sha256="x",
            model="m",
            created_at="2026-09-30T00:00:00+00:00",
        ),
    )
    put_plan(root, "1", Plan(primary="1/syllabus/s.pdf"))


def map_hefferon(tmp_uploads: Path, strip_bookmarks: bool) -> dict:
    from fastapi.testclient import TestClient

    from app.main import app

    hefferon_course(tmp_uploads, strip_bookmarks)
    response = TestClient(app).post("/plans/1/map")
    assert response.status_code == 200, response.text
    plan = response.json()
    for s in plan["sessions"]:
        for p in s["proposals"]:
            print(
                s["session"]["label"],
                p["label"],
                p["pdf_start"],
                p["pdf_end"],
                p["method"],
                p["printed"],
                p["note"],
            )
    return plan


def spans(plan: dict) -> list[list[tuple]]:
    return [
        [(p["pdf_start"], p["pdf_end"], p["method"]) for p in s["proposals"]]
        for s in plan["sessions"]
    ]


def test_hefferon_bookmarks(tmp_uploads: Path) -> None:
    plan = map_hefferon(tmp_uploads, strip_bookmarks=False)

    assert plan["books"][0]["file"] is None  # Strang isn't uploaded
    assert plan["books"][1]["file"].endswith("hefferon_linear_algebra.pdf")
    # Chapter One Section I is PDF 11-45; printed pp. 100-110 are PDF 110-120; Chapter Two 93-182.
    assert spans(plan) == [
        [(11, 45, "bookmarks")],
        [(110, 120, "pages")],
        [(93, 182, "bookmarks")],
    ]


def test_hefferon_table_of_contents(tmp_uploads: Path) -> None:
    plan = map_hefferon(tmp_uploads, strip_bookmarks=True)

    lecture1, lecture2, lecture3 = spans(plan)
    assert lecture2 == [(110, 120, "pages")]
    ((start, end, method),) = lecture3
    assert method == "toc" and abs(start - 93) <= 1 and abs(end - 182) <= 1
    ((start, _, method),) = lecture1
    assert method == "toc" and abs(start - 11) <= 1
