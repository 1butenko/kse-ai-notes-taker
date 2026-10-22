"""Notes generation artifacts, stored under uploads/<course>/notes/<run>/ by the worker."""

import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.plan import load_plan
from app.schemas import Strict
from app.syllabus import Transcript

RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


# Inputs: mapped chunks with stable ids, page metadata and the source they came from.


class Chunk(BaseModel):
    id: str
    source: int
    file: str
    pdf_page: int | None
    printed_page: str | None
    text: str


class Source(BaseModel):
    """A session material: an excerpt (book pages) or a whole uploaded file."""

    id: int
    file: str
    title: str
    label: str | None
    pdf_start: int | None
    pdf_end: int | None
    sessions: list[int]
    outline: list[str]
    chunk_ids: list[str]


class Inputs(BaseModel):
    sources: list[Source]
    chunks: list[Chunk]
    skipped: list[str]


# Planning.


class PlannedTopic(Strict):
    id: str
    title: str
    sessions: list[int]
    objectives: list[str]
    success_criteria: list[str]
    prerequisites: list[str]
    sources: list[int]
    key_terms: list[str]


class PlannedSection(Strict):
    title: str
    topics: list[PlannedTopic]


class NotationEntry(Strict):
    symbol: str
    meaning: str


class TermEntry(Strict):
    term: str
    definition: str


class CoursePlan(Strict):
    title: str
    sections: list[PlannedSection]
    notation: list[NotationEntry]
    terminology: list[TermEntry]
    conventions: list[str]

    def topics(self) -> list[tuple[PlannedSection, PlannedTopic]]:
        return [(section, topic) for section in self.sections for topic in section.topics]


class CoverageIssue(Strict):
    kind: Literal[
        "missing_topic", "duplicate", "granularity", "weak_evidence", "ordering", "objectives"
    ]
    severity: Literal["blocking", "minor"]
    topics: list[str]
    detail: str
    fix: str


class CoverageReview(Strict):
    approved: bool
    issues: list[CoverageIssue]

    def blocking(self) -> list[CoverageIssue]:
        return [i for i in self.issues if i.severity == "blocking" and i.kind != "weak_evidence"]

    def evidence_gaps(self) -> list[CoverageIssue]:
        return [i for i in self.issues if i.kind == "weak_evidence"]


# Topic generation.

Role = Literal[
    "definition",
    "theorem",
    "proof",
    "example",
    "intuition",
    "exercise",
    "background",
    "complementary",
]


class EvidenceItem(BaseModel):
    chunk_id: str
    source: int
    title: str
    page: str | None
    role: Role
    relevance: int
    reason: str
    text: str


BlockKind = Literal[
    "overview",
    "definition",
    "theorem",
    "proof",
    "example",
    "intuition",
    "explanation",
    "remark",
    "summary",
]


class NoteBlock(BaseModel):
    id: str
    kind: BlockKind
    title: str | None
    content: str
    citations: list[str]


class VerificationIssue(Strict):
    block: int | None
    kind: Literal[
        "unsupported_claim",
        "math_error",
        "missing_objective",
        "notation",
        "assumption",
        "citation",
        "clarity",
    ]
    severity: Literal["major", "minor"]
    detail: str
    fix: str


class Verification(BaseModel):
    round: int
    model: str
    passed: bool
    issues: list[VerificationIssue]
    escalate: bool
    escalation_reason: str | None


TopicStatus = Literal["verified", "unresolved", "no_evidence", "failed"]


class TopicNote(BaseModel):
    topic_id: str
    title: str
    status: TopicStatus
    blocks: list[NoteBlock]
    evidence: list[EvidenceItem]
    rounds: int
    verifier: str | None
    open_issues: list[VerificationIssue]
    error: str | None = None
    verification_stale: bool = False


# The finished document.


class NotesSection(BaseModel):
    title: str
    topics: list[TopicNote]


class NotesDocument(BaseModel):
    schema_version: int = 1
    language: Literal["uk", "en"] | None = None
    course: str
    run: str
    title: str
    created_at: str
    sections: list[NotesSection]
    sources: list[Source]
    notation: list[NotationEntry]
    terminology: list[TermEntry]
    models: dict[str, str]


# The run.

RunState = Literal["queued", "running", "done", "failed"]


class RunEvent(BaseModel):
    at: str
    stage: str
    message: str


class NotesRun(BaseModel):
    id: str
    course: str
    status: RunState
    stage: str
    created_at: str
    updated_at: str
    models: dict[str, str]
    topics_total: int = 0
    topics_done: int = 0
    warnings: list[str] = []
    error: str | None = None
    events: list[RunEvent] = []


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def notes_dir(course_dir: Path) -> Path:
    return course_dir / "notes"


def run_dir(course_dir: Path, run: str) -> Path:
    return notes_dir(course_dir) / run


def topic_pdf(course_dir: Path, run: str, topic: str) -> Path:
    return run_dir(course_dir, run) / "topics" / topic / "note.pdf"


def load_run(course_dir: Path, run: str) -> NotesRun | None:
    target = run_dir(course_dir, run) / "run.json"
    if not RUN_ID.match(run) or not target.is_file():
        return None
    return NotesRun.model_validate_json(target.read_text())


def list_runs(course_dir: Path) -> list[NotesRun]:
    directory = notes_dir(course_dir)
    if not directory.is_dir():
        return []
    runs = [load_run(course_dir, d.name) for d in sorted(directory.iterdir(), reverse=True)]
    return [r for r in runs if r]


def load_document(course_dir: Path, run: str) -> NotesDocument | None:
    target = run_dir(course_dir, run) / "notes.json"
    if not RUN_ID.match(run) or not target.is_file():
        return None
    document = NotesDocument.model_validate_json(target.read_text())
    if document.schema_version == 1 and document.language is None:
        document.language = legacy_language(course_dir)
    return document


def legacy_language(course_dir: Path) -> Literal["uk", "en"] | None:
    """Read-only fallback: the current primary transcript is not historical provenance."""
    try:
        primary = load_plan(course_dir).primary
        if primary is None:
            return None
        target = (course_dir.parent / f"{primary}.transcript.json").resolve()
        if target.parent != course_dir.resolve() / "syllabus" or not target.is_file():
            return None
        transcript = Transcript.model_validate_json(target.read_text())
    except (OSError, ValidationError):
        return None
    return transcript.language if transcript.language in ("uk", "en") else None
