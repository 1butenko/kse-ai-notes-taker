from pathlib import Path
from typing import Any

import mammoth

from app.llm import PDF_PLUGINS, Strict, chat, pdf_part


class Reading(Strict):
    raw: str
    title: str | None
    authors: list[str]
    year: str | None
    url: str | None
    pages: str | None


class SessionReading(Reading):
    material_ref: int | None


class Session(Strict):
    label: str
    number: int | None
    date: str | None
    topic: str
    subtopics: list[str]
    required_readings: list[SessionReading]
    optional_readings: list[SessionReading]


class SyllabusExtraction(Strict):
    language: str | None
    learning_materials: list[Reading]
    sessions: list[Session]
    notes: str | None


class Transcript(SyllabusExtraction):
    source_path: str
    source_sha256: str
    model: str
    created_at: str


SYSTEM_PROMPT = """\
You extract the reading plan from a university course syllabus.

Extract only two things:
1. learning_materials: the course-wide list of learning materials / literature / bibliography,
   if the syllabus has one. One entry per item, in the order listed, across all its
   subsections (e.g. books, then videos).
2. sessions: the plan of weeks, lectures, seminars or modules, in the order given. For each:
   - label: only the session's kind and number as written, e.g. "Week 3", "Лекція 5",
     "Module 2", "Lecture 1"; the rest of the heading goes in topic.
   - number: its number if there is one, else null.
   - date: the date exactly as written, else null. Do not normalise or guess the year.
   - topic: the session topic. subtopics: its listed subtopics, else [].
   - required_readings / optional_readings: the readings listed for this session. Put a reading
     in optional_readings only when the syllabus marks it optional, additional or further
     reading (e.g. "додаткова", "further", "recommended"). Unlabelled readings are required.

Choosing the session plan. Syllabi often contain more than one schedule, e.g. a table of
topics or lectures with a "learning materials" / "literature" column, and a separate calendar
("week plan") with dates but no readings. Use as sessions the schedule that assigns readings
to sessions, at its granularity (e.g. one session per lecture), even if another schedule
comes later or looks more complete. Never return a plan with no readings when the syllabus
assigns readings somewhere. Use the other schedule only to fill `date`: find where the same
session appears in the calendar and copy that week's heading and dates, e.g. a lecture listed
under "Week 2 (7.09 – 13.09)" gets date "Week 2 (7.09 – 13.09)". Group headings that only
bundle sessions (e.g. "1. Linear operators" above Lectures 5-7) are not sessions themselves.
Practice sessions that repeat a lecture's topic are not separate sessions unless they have
their own readings.

Reading tables. In a schedule table, one cell of the materials column often covers several
sessions listed in the neighbouring cell. Its lines appear in the same top-to-bottom order as
those sessions: give each block of references to the session printed at the same height. When
a block sits between two sessions, give it to the first one it spans. Sessions with nothing
next to them get no readings. Check every session row; do not stop after the first.

For every reading:
- raw: the citation copied verbatim, in the syllabus's own language. Never translate it.
- title, authors, year, url: parsed from the citation when present, else null / [].
- pages: the chapters, sections or pages cited, as written (e.g. "ch. 3-4", "pp. 45-67"), else null.
- material_ref (session readings only): the 0-based index of the same item in
  learning_materials, only when you are confident it is the same work; else null.

Numbered references. Sessions often cite the learning materials list by number, e.g.
"[1] Chapter 1.1, Chapter 1.2; [4] Chapter 2.1". Split at each number marker: every "[n] ..."
group is one reading, so this example is two readings. For each: raw is the group verbatim
("[1] Chapter 1.1, Chapter 1.2"), pages is the part after the marker ("Chapter 1.1, Chapter
1.2"), title and authors come from item [n] of the list, and material_ref is that item's
0-based index (item [1] is index 0 when the list is numbered from 1).

language: the syllabus's main language as an ISO 639-1 code, e.g. "uk" or "en".
notes: a short remark when something is missing or unclear, e.g. "No session plan found";
else null. If a section is absent, return an empty list for it. Do not invent content.
"""


class EmptyDocument(Exception):
    pass


def build_messages(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Chat messages for a syllabus file, plus the OpenRouter plugins it needs."""
    data = path.read_bytes()
    if not data:
        raise EmptyDocument("The file is empty")

    if path.suffix.lower() == ".pdf":
        prompt = "Extract the reading plan from this syllabus."
        return chat(SYSTEM_PROMPT, prompt, pdf_part(path.name, data)), PDF_PLUGINS

    html = docx_to_html(path)
    prompt = f"Extract the reading plan from this syllabus (converted from DOCX to HTML):\n\n{html}"
    return chat(SYSTEM_PROMPT, prompt), None


def docx_to_html(path: Path) -> str:
    try:
        with path.open("rb") as file:
            html = mammoth.convert_to_html(file).value
    except Exception as error:
        raise EmptyDocument("Could not read the DOCX file") from error
    if not html.strip():
        raise EmptyDocument("No text found in the DOCX file")
    return html


def drop_bad_refs(extraction: SyllabusExtraction) -> int:
    count = len(extraction.learning_materials)
    dropped = 0
    for session in extraction.sessions:
        for reading in session.required_readings + session.optional_readings:
            if reading.material_ref is not None and not 0 <= reading.material_ref < count:
                reading.material_ref = None
                dropped += 1
    return dropped
