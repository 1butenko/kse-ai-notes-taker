import base64
from pathlib import Path
from typing import Any

import mammoth
from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
   if the syllabus has one. One entry per item.
2. sessions: the plan of weeks, lectures, seminars or modules, in the order given. For each:
   - label: the heading exactly as written, e.g. "Week 3", "Лекція 5", "Module 2".
   - number: its number if there is one, else null.
   - date: the date exactly as written, else null. Do not normalise or guess the year.
   - topic: the session topic. subtopics: its listed subtopics, else [].
   - required_readings / optional_readings: the readings listed for this session. Put a reading
     in optional_readings only when the syllabus marks it optional, additional or further
     reading (e.g. "додаткова", "further", "recommended"). Unlabelled readings are required.

For every reading:
- raw: the citation copied verbatim, in the syllabus's own language. Never translate it.
- title, authors, year, url: parsed from the citation when present, else null / [].
- pages: the chapters, sections or pages cited, as written (e.g. "ch. 3-4", "pp. 45-67"), else null.
- material_ref (session readings only): the 0-based index of the same item in
  learning_materials, only when you are confident it is the same work; else null.

language: the syllabus's main language as an ISO 639-1 code, e.g. "uk" or "en".
notes: a short remark when something is missing or unclear, e.g. "No session plan found";
else null. If a section is absent, return an empty list for it. Do not invent content.
"""

PDF_PLUGINS = [{"id": "file-parser", "pdf": {"engine": "native"}}]


class EmptyDocument(Exception):
    pass


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema with $refs inlined, since not every provider resolves them."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {key: inline(value) for key, value in node.items()}
        if isinstance(node, list):
            return [inline(item) for item in node]
        return node

    return inline(schema)


def build_messages(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Chat messages for a syllabus file, plus the OpenRouter plugins it needs."""
    data = path.read_bytes()
    if not data:
        raise EmptyDocument("The file is empty")

    if path.suffix.lower() == ".pdf":
        encoded = base64.b64encode(data).decode()
        parts: list[dict[str, Any]] = [
            {"type": "text", "text": "Extract the reading plan from this syllabus."},
            {
                "type": "file",
                "file": {
                    "filename": path.name,
                    "file_data": f"data:application/pdf;base64,{encoded}",
                },
            },
        ]
        plugins = PDF_PLUGINS
    else:
        html = docx_to_html(path)
        parts = [
            {
                "type": "text",
                "text": "Extract the reading plan from this syllabus (converted from DOCX to HTML):"
                f"\n\n{html}",
            }
        ]
        plugins = None

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": parts}]
    return messages, plugins


def docx_to_html(path: Path) -> str:
    try:
        with path.open("rb") as file:
            html = mammoth.convert_to_html(file).value
    except Exception as error:
        raise EmptyDocument("Could not read the DOCX file") from error
    if not html.strip():
        raise EmptyDocument("No text found in the DOCX file")
    return html


def drop_bad_refs(extraction: SyllabusExtraction) -> None:
    count = len(extraction.learning_materials)
    for session in extraction.sessions:
        for reading in session.required_readings + session.optional_readings:
            if reading.material_ref is not None and not 0 <= reading.material_ref < count:
                reading.material_ref = None
