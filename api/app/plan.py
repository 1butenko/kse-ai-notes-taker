import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.syllabus import Transcript


class PlanSession(BaseModel):
    id: str
    label: str
    number: int | None
    files: list[str] = []


class BookMatch(BaseModel):
    """Which uploaded file holds a course material. `raw` guards against a changed list."""

    material: int
    raw: str
    file: str | None
    confirmed: bool = False


Method = Literal["pages", "bookmarks", "toc", "manual"]


class Proposal(BaseModel):
    id: str
    session_id: str
    reading: str
    book: str
    label: str
    pdf_start: int | None
    pdf_end: int | None
    printed: str | None
    method: Method
    note: str | None = None
    status: Literal["proposed", "approved", "rejected"] = "proposed"
    excerpt: str | None = None


class Plan(BaseModel):
    primary: str | None = None
    sessions: list[PlanSession] = []
    unassigned: list[str] = []
    books: list[BookMatch] = []
    proposals: list[Proposal] = []


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def plan_file(course_dir: Path) -> Path:
    return course_dir / "plan.json"


def load_plan(course_dir: Path) -> Plan:
    target = plan_file(course_dir)
    if not target.is_file():
        return Plan()
    return Plan.model_validate_json(target.read_text())


def save_plan(course_dir: Path, plan: Plan) -> None:
    course_dir.mkdir(parents=True, exist_ok=True)
    plan_file(course_dir).write_text(plan.model_dump_json(indent=2))


def materials_fingerprint(plan: Plan) -> str:
    """Which files, excerpts included, are attached to which session; order doesn't count."""
    value = {session.id: sorted(set(session.files)) for session in plan.sessions}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def session_fingerprint(plan: Plan, session_id: str) -> str:
    """One lecture's readings: its files and, for excerpts, the book pages they were cut from.

    Pages count because an excerpt cut again from other pages may reuse its file name.
    """
    entry = next(s for s in plan.sessions if s.id == session_id)
    excerpts = {p.excerpt: p for p in plan.proposals if p.excerpt}
    value = sorted(
        [path]
        + (
            [excerpts[path].book, excerpts[path].pdf_start, excerpts[path].pdf_end]
            if path in excerpts
            else []
        )
        for path in set(entry.files)
    )
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


class UnknownSession(LookupError):
    pass


def scope_to_session(
    plan: Plan, transcript: Transcript, session_id: str
) -> tuple[Plan, Transcript]:
    """One lecture's slice of an aligned plan and transcript: its entry and syllabus session,
    with the excerpt proposals and book titles its files need. Inside, it is session S0.

    Only what this lecture reads is kept, so changes elsewhere in the course never alter
    the slice (and never block resuming the lecture's run).
    """
    index = next((i for i, s in enumerate(plan.sessions) if s.id == session_id), None)
    if index is None:
        raise UnknownSession(session_id)
    entry = plan.sessions[index]
    proposals = [p for p in plan.proposals if p.excerpt and p.excerpt in entry.files]
    read = {p.book for p in proposals} | set(entry.files)
    scoped = Plan(
        primary=plan.primary,
        sessions=[entry.model_copy(deep=True)],
        books=[b.model_copy() for b in plan.books if b.file in read],
        proposals=[p.model_copy() for p in proposals],
    )
    return scoped, transcript.model_copy(update={"sessions": [transcript.sessions[index]]})


def normalize(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip().casefold()


def sync(plan: Plan, transcript: Transcript) -> bool:
    """Align plan sessions with the transcript's, keeping ids and files of matched sessions.

    A new session takes the first unused old session with the same label, else the same
    number. Files of old sessions that no longer match anything move to `unassigned`.
    Returns whether the plan changed.
    """
    old = plan.sessions
    used: set[str] = set()

    def take(matches) -> PlanSession | None:
        for candidate in old:
            if candidate.id not in used and matches(candidate):
                used.add(candidate.id)
                return candidate
        return None

    sessions = []
    for session in transcript.sessions:
        match = take(lambda o, s=session: normalize(o.label) == normalize(s.label)) or (
            take(lambda o, s=session: o.number is not None and o.number == s.number)
            if session.number is not None
            else None
        )
        sessions.append(
            PlanSession(
                id=match.id if match else new_id(),
                label=session.label,
                number=session.number,
                files=match.files if match else [],
            )
        )

    unassigned = list(plan.unassigned)
    for leftover in old:
        if leftover.id not in used:
            unassigned += [f for f in leftover.files if f not in unassigned]

    # Open proposals of vanished sessions go; approved ones stay to describe their excerpts.
    ids = {s.id for s in sessions}
    proposals = [p for p in plan.proposals if p.session_id in ids or p.status == "approved"]

    changed = sessions != old or unassigned != plan.unassigned or proposals != plan.proposals
    plan.sessions = sessions
    plan.unassigned = unassigned
    plan.proposals = proposals
    return changed


def drop_primary(plan: Plan) -> None:
    """Forget the plan's syllabus; files attached to its sessions move to `unassigned`."""
    for session in plan.sessions:
        plan.unassigned += [f for f in session.files if f not in plan.unassigned]
    plan.primary = None
    plan.sessions = []
    plan.proposals = [p for p in plan.proposals if p.status == "approved"]


def merge_proposals(plan: Plan, fresh: list[Proposal]) -> None:
    """Replace open proposals with fresh ones; never touch approved or rejected ones."""
    kept = [p for p in plan.proposals if p.status != "proposed"]
    decided = {(p.session_id, p.reading, p.book) for p in kept}
    plan.proposals = kept + [p for p in fresh if (p.session_id, p.reading, p.book) not in decided]
