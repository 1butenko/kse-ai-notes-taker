"""Notes generation artifacts, stored under uploads/<course>/notes/<run>/ by the worker."""

import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from app.plan import load_plan
from app.schemas import Strict
from app.syllabus import Transcript

RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


SAFE_TOPIC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def topic_filename(topic_id: str) -> str:
    """A single reversible filesystem component, including for readable legacy IDs."""
    if not topic_id:
        raise ValueError("Empty topic ID")
    encoded = quote(topic_id, safe="")
    return encoded.replace(".", "%2E") if encoded in (".", "..") else encoded


def validate_topic_ids(ids: list[str]) -> None:
    if any(not SAFE_TOPIC_ID.fullmatch(item) for item in ids):
        raise ValueError("Unsafe topic ID in course plan; start a new run")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate topic IDs in course plan; start a new run")


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


class CourseNotation(BaseModel):
    """The notation sheet lecture runs share: seeded by the first, only ever appended to."""

    notation: list[NotationEntry] = []
    terminology: list[TermEntry] = []


def notation_file(course_dir: Path) -> Path:
    return course_dir / "notation.json"


def load_course_notation(course_dir: Path) -> CourseNotation:
    """A missing or unreadable sheet is an empty one."""
    try:
        return CourseNotation.model_validate_json(notation_file(course_dir).read_text())
    except (OSError, UnicodeError, ValueError):
        return CourseNotation()


def _key(text: str) -> str:
    return " ".join(text.split())


def bind_notation(plan: CoursePlan, sheet: CourseNotation) -> CoursePlan:
    """The plan with the sheet's meaning for every symbol and term the sheet already has."""
    symbols = {_key(e.symbol): e for e in sheet.notation}
    terms = {_key(e.term).casefold(): e for e in sheet.terminology}
    return plan.model_copy(
        update={
            "notation": [symbols.get(_key(e.symbol), e) for e in plan.notation],
            "terminology": [terms.get(_key(e.term).casefold(), e) for e in plan.terminology],
        }
    )


def append_notation(sheet: CourseNotation, plan: CoursePlan) -> CourseNotation:
    """The sheet plus the plan's new symbols and terms; existing meanings never change."""
    notation, terminology = list(sheet.notation), list(sheet.terminology)
    symbols = {_key(e.symbol) for e in notation}
    terms = {_key(e.term).casefold() for e in terminology}
    for entry in plan.notation:
        if _key(entry.symbol) not in symbols:
            symbols.add(_key(entry.symbol))
            notation.append(entry)
    for entry in plan.terminology:
        if _key(entry.term).casefold() not in terms:
            terms.add(_key(entry.term).casefold())
            terminology.append(entry)
    return CourseNotation(notation=notation, terminology=terminology)


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


class TeacherDecision(BaseModel):
    decision: Literal["approved", "revoked"]
    reviewer: str
    at: str
    comment: str | None = None
    fingerprint: str | None = None


class TopicNote(BaseModel):
    objectives: list[str] = []
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
    teacher_decision: TeacherDecision | None = None


# The finished document.

RenderFormat = Literal["html", "pdf", "docx", "book"]


class RenderedArtifact(BaseModel):
    format: RenderFormat
    path: str
    revision: int
    status: Literal["ready", "failed"]
    error: str | None = None
    topic_id: str | None = None


class NotesSection(BaseModel):
    title: str
    topics: list[TopicNote]


class NoteAsset(BaseModel):
    id: str
    name: str
    path: str
    media_type: Literal["image/png", "image/jpeg"]
    sha256: str
    width: int
    height: int


class NotesDocument(BaseModel):
    assets: list[NoteAsset] = []
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
    # The course plan's materials when the run started (see `materials_fingerprint`); for a
    # lecture run, that lecture's (see `session_fingerprint`).
    materials: str | None = None
    # The plan session a lecture run writes the note of; None for whole-course runs.
    session_id: str | None = None
    session_label: str | None = None


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


def load_course_plan(course_dir: Path, run: str) -> CoursePlan | None:
    """The run's planned topics, once planning is done; None before that or if unreadable."""
    target = run_dir(course_dir, run) / "plan.json"
    if not RUN_ID.match(run) or not target.is_file():
        return None
    try:
        return CoursePlan.model_validate_json(target.read_text())
    except (OSError, ValidationError):
        return None


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
    except (OSError, UnicodeError, ValidationError):
        return None
    return transcript.language if transcript.language in ("uk", "en") else None
