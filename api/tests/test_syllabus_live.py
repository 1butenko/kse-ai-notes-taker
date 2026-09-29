"""Live extraction checks against real syllabi. They call OpenRouter and cost money, so they
only run with `LIVE=1 uv run pytest tests/test_syllabus_live.py -s`."""

import asyncio
import os
import re
from pathlib import Path

import httpx2
import pytest

from app.config import Settings
from app.openrouter import OpenRouterClient
from app.routers.syllabus import SCHEMA
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
            return await client.complete_json(messages, "syllabus", SCHEMA, plugins)

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
