"""One lecture's readings, as the agent sees them: a brief and one Markdown file per reading.

Reuses the read path of the notes pipeline (`app.worker.sources`): PDF text per page, replaced by
the vision transcription where one exists; Markdown, text and Word readings as one page. Only the
lecture's own files and excerpts are read, so the agent can never reach another lecture's
sources. Total text is capped; what does not fit is cut and the brief says so.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from deepagents.backends.utils import create_file_data

from app.books import load_index, printed_label
from app.plan import aligned, scope_to_session, session_fingerprint
from app.storage import sha256
from app.worker.sources import (
    NEAR_EMPTY,
    load_transcripts,
    page_ranges,
    page_texts,
    session_materials,
    untranscribed,
)

DEFAULT_MAX_CHARS = 400_000


class LectureNotFound(LookupError):
    pass


@dataclass
class Page:
    pdf_page: int | None
    printed: str | None
    text: str


@dataclass
class Reading:
    key: str  # citation key, r1, r2, ...
    title: str
    file: str  # relative to the uploads directory
    label: str | None  # an excerpt's chapter or section
    pdf_start: int | None
    pdf_end: int | None
    pages: list[Page]
    truncated: bool = False

    @property
    def chars(self) -> int:
        return sum(len(p.text) for p in self.pages)

    @property
    def path(self) -> str:
        """Where the agent reads it."""
        slug = re.sub(r"[^a-z0-9]+", "-", Path(self.file).stem.lower()).strip("-")[:40]
        return f"/readings/{self.key[1:].zfill(2)}-{slug or 'reading'}.md"


@dataclass
class LectureBundle:
    course: str
    session_id: str
    label: str
    number: int | None
    date: str | None
    topic: str
    subtopics: list[str]
    language: str  # "uk" or "en"
    syllabus_readings: list[str]
    readings: list[Reading]
    warnings: list[str] = field(default_factory=list)
    fingerprint: str = ""

    @property
    def subtitle(self) -> str:
        return " · ".join(part for part in (self.label, self.date or "") if part)

    def references(self) -> list[dict]:
        """CSL items for Quarto, so the notes can cite `[@r1, p. 34]`."""
        return [
            {
                "id": r.key,
                "type": "document",
                "title": f"{r.title}: {r.label}" if r.label else r.title,
            }
            for r in self.readings
        ]


def language_code(value: str | None) -> str:
    text = (value or "").strip().lower()
    return "uk" if text.startswith(("uk", "ua")) else "en"


def load_lecture(
    uploads_dir: Path, course: str, session_id: str, max_chars: int = DEFAULT_MAX_CHARS
) -> LectureBundle:
    """Read one lecture's readings. Raises `LectureNotFound` for an unknown course or lecture."""
    plan, transcript, _ = aligned(uploads_dir, course)
    if transcript is None:
        raise LectureNotFound(f"Course {course} has no syllabus")
    try:
        scoped, scoped_transcript = scope_to_session(plan, transcript, session_id)
    except LookupError as error:
        raise LectureNotFound(f"Unknown lecture {session_id}") from error
    session = scoped_transcript.sessions[0]
    course_dir = uploads_dir / course

    readings: list[Reading] = []
    warnings: list[str] = []
    seen: set[tuple] = set()
    budget = max_chars
    for material, _ in session_materials(scoped, scoped_transcript):
        key = (material.file, material.pdf_start, material.pdf_end)
        if key in seen:
            continue
        seen.add(key)
        file = uploads_dir / material.file
        if not file.is_file():
            warnings.append(f"{material.file}: the file is missing")
            continue
        digest = sha256(file)
        try:
            texts = page_texts(course_dir, file, digest, material.pdf_start or 1, material.pdf_end)
        except Exception as error:
            print(f"Can't read {material.file}: {error!r}")
            warnings.append(f"{material.file}: could not read the text")
            continue

        is_pdf = file.suffix.lower() == ".pdf"
        index = None
        if is_pdf:
            read = load_transcripts(course_dir, digest)
            transcribed = read.pages if read else {}
            if material.pdf_start is not None:
                garbled = untranscribed(file, texts, transcribed)
                if garbled:
                    warnings.append(
                        f"{material.file}: {page_ranges(garbled)} have formulas their PDF text "
                        "garbles; read them with care"
                    )
            texts = {page: transcribed.get(page, text) for page, text in texts.items()}
            index = load_index(course_dir, file, digest)
            blank = [p for p, t in texts.items() if len(t.strip()) < NEAR_EMPTY]
            if blank and len(blank) < len(texts):
                warnings.append(
                    f"{material.file}: {page_ranges(blank)} have no extractable text "
                    "(scanned or blank)"
                )

        pages = [
            Page(
                pdf_page=page if is_pdf else None,
                printed=printed_label(index, page) if index else None,
                text=text.strip(),
            )
            for page, text in sorted(texts.items())
            if text.strip()
        ]
        if not pages:
            warnings.append(f"{material.file}: no extractable text (scanned or unsupported)")
            continue

        reading = Reading(
            key=f"r{len(readings) + 1}",
            title=material.title,
            file=material.file,
            label=material.label,
            pdf_start=material.pdf_start,
            pdf_end=material.pdf_end,
            pages=[],
        )
        for page in pages:
            if budget <= 0:
                reading.truncated = True
                break
            if len(page.text) > budget:
                page = Page(page.pdf_page, page.printed, page.text[:budget])
                reading.truncated = True
            reading.pages.append(page)
            budget -= len(page.text)
        if reading.truncated:
            warnings.append(
                f"{reading.key} ({material.file}) was cut to fit the reading limit; "
                "the rest is not available"
            )
        if reading.pages:
            readings.append(reading)

    return LectureBundle(
        course=course,
        session_id=session_id,
        label=session.label,
        number=session.number,
        date=session.date,
        topic=session.topic,
        subtopics=list(session.subtopics),
        language=language_code(transcript.language),
        syllabus_readings=[r.raw for r in [*session.required_readings, *session.optional_readings]],
        readings=readings,
        warnings=warnings,
        fingerprint=session_fingerprint(plan, session_id),
    )


def reading_markdown(reading: Reading) -> str:
    where = (
        f"{page_ranges(list(range(reading.pdf_start, reading.pdf_end + 1)))}"
        if reading.pdf_start is not None and reading.pdf_end is not None
        else "the whole file"
    )
    lines = [
        f"# {reading.title}" + (f": {reading.label}" if reading.label else ""),
        "",
        f"Citation key: `@{reading.key}`. Source: {Path(reading.file).name}, {where}.",
        "Page markers below give the PDF page and, when known, the printed page to cite.",
        "",
    ]
    for page in reading.pages:
        if page.pdf_page is not None:
            printed = f" · printed p. {page.printed}" if page.printed else ""
            lines += [f"<!-- PDF p. {page.pdf_page}{printed} -->", ""]
        lines += [page.text, ""]
    if reading.truncated:
        lines.append("<!-- The rest of this reading was cut to fit the reading limit. -->")
    return "\n".join(lines).strip() + "\n"


def brief_markdown(bundle: LectureBundle) -> str:
    language = "Ukrainian" if bundle.language == "uk" else "English"
    lines = [
        f"# Lecture: {bundle.topic}",
        "",
        f"- Label: {bundle.label}" + (f" (number {bundle.number})" if bundle.number else ""),
        *([f"- Date: {bundle.date}"] if bundle.date else []),
        f"- Write the notes in {language}.",
        "",
        "## Subtopics from the syllabus",
        "",
        *([f"- {s}" for s in bundle.subtopics] or ["- (none listed)"]),
        "",
        "## Readings listed in the syllabus",
        "",
        *([f"- {r}" for r in bundle.syllabus_readings] or ["- (none listed)"]),
        "",
        "## Your readings",
        "",
        "| Key | File | Covers | Characters |",
        "|-----|------|--------|-----------|",
    ]
    for r in bundle.readings:
        covers = r.label or ("PDF pages " + f"{r.pdf_start}–{r.pdf_end}" if r.pdf_start else "")
        lines.append(f"| `@{r.key}` | `{r.path}` | {covers or r.title} | {r.chars} |")
    if bundle.warnings:
        lines += ["", "## Warnings", "", *[f"- {w}" for w in bundle.warnings]]
    return "\n".join(lines) + "\n"


def seed_files(bundle: LectureBundle) -> dict[str, dict]:
    """The lecture's files for the agent's virtual filesystem."""
    files = {"/lecture/brief.md": create_file_data(brief_markdown(bundle))}
    for reading in bundle.readings:
        files[reading.path] = create_file_data(reading_markdown(reading))
    files["/lecture/references.json"] = create_file_data(
        json.dumps(bundle.references(), ensure_ascii=False, indent=2)
    )
    return files
