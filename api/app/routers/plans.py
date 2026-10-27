import re
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from pypdf import PdfReader

from app.books import cut_excerpt, load_index, printed_range
from app.config import Settings, get_settings
from app.plan import (
    BookMatch,
    Plan,
    PlanSession,
    Proposal,
    load_plan,
    materials_fingerprint,
    merge_proposals,
    new_id,
    save_plan,
    session_fingerprint,
    sync,
)
from app.routers.syllabus import load_transcript, syllabus_file
from app.routers.uploads import SavedFile, safe_name
from app.storage import sha256
from app.syllabus import Session, Transcript
from app.worker_client import WorkerClient, get_worker_client
from app.worker_contract import MapRequest

router = APIRouter(prefix="/plans", tags=["plans"])

COURSE = re.compile(r"^(local|\d+)$")
EXACT_METHODS = {"pages", "bookmarks"}


class PathRequest(BaseModel):
    path: str


class BookRequest(BaseModel):
    file: str | None


class PagesRequest(BaseModel):
    pdf_start: int | None = None
    pdf_end: int | None = None


class ExcerptRequest(BaseModel):
    path: str
    pdf_start: int
    pdf_end: int


class Excerpt(BaseModel):
    book: str
    label: str
    pdf_start: int
    pdf_end: int
    printed: str | None


class FileView(SavedFile):
    excerpt: Excerpt | None = None
    # Uploaded for one lecture only: never a course reading, never matched to other lectures.
    lecture_only: bool = False


class SessionView(BaseModel):
    id: str
    session: Session
    files: list[FileView]
    proposals: list[Proposal]
    # This lecture's readings; a lecture run records the one it was written from.
    materials: str


class BookView(BaseModel):
    material: int
    raw: str
    file: str | None
    confirmed: bool


class PlanView(BaseModel):
    course: str
    primary: str | None
    transcript: Transcript | None
    sessions: list[SessionView]
    unassigned: list[FileView]
    books: list[BookView]
    mapped: bool
    # Changes whenever a file is attached to or detached from a session.
    materials: str


def course_dir(settings: Settings, course: str) -> Path:
    if not COURSE.match(course):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid course: {course!r}")
    return settings.uploads_dir / course


def reading_file(settings: Settings, course: str, path: str) -> str:
    root = settings.uploads_dir.resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root) or file.relative_to(root).parts[:2] != (course, "reading"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a reading file of this course")
    if len(file.relative_to(root).parts) != 3 or not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reading file not found")
    return file.relative_to(root).as_posix()


def reading_paths(settings: Settings, course: str) -> list[str]:
    directory = settings.uploads_dir / course / "reading"
    if not directory.is_dir():
        return []
    return [f"{course}/reading/{f.name}" for f in sorted(directory.iterdir()) if f.is_file()]


def is_excerpt(path: str) -> bool:
    return path.split("/")[1:2] == ["excerpts"]


def is_lecture_file(path: str) -> bool:
    return path.split("/")[1:2] == ["lecture"]


SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def file_views(settings: Settings, plan: Plan, paths: list[str]) -> list[FileView]:
    excerpts = {p.excerpt: p for p in plan.proposals if p.excerpt}
    result = []
    for path in paths:
        file = settings.uploads_dir / path
        if not file.is_file():
            continue
        proposal = excerpts.get(path)
        excerpt = (
            Excerpt(
                book=proposal.book,
                label=proposal.label,
                pdf_start=proposal.pdf_start,
                pdf_end=proposal.pdf_end,
                printed=proposal.printed,
            )
            if proposal and proposal.pdf_start is not None and proposal.pdf_end is not None
            else None
        )
        result.append(
            FileView(
                path=path,
                size=file.stat().st_size,
                excerpt=excerpt,
                lecture_only=is_lecture_file(path),
            )
        )
    return result


def current(settings: Settings, course: str) -> tuple[Plan, Transcript | None]:
    """Load the course plan, re-aligned with its primary transcript."""
    directory = course_dir(settings, course)
    plan = load_plan(directory)
    transcript = load_transcript(settings.uploads_dir / plan.primary) if plan.primary else None
    if transcript and sync(plan, transcript):
        save_plan(directory, plan)
    return plan, transcript


def book_views(plan: Plan, transcript: Transcript | None) -> list[BookView]:
    if not transcript:
        return []
    matches = {(b.material, b.raw): b for b in plan.books}
    views = []
    for i, material in enumerate(transcript.learning_materials):
        match = matches.get((i, material.raw))
        views.append(
            BookView(
                material=i,
                raw=material.raw,
                file=match.file if match else None,
                confirmed=match.confirmed if match else False,
            )
        )
    return views


def render(settings: Settings, course: str, plan: Plan, transcript: Transcript | None) -> PlanView:
    sessions = (
        [
            SessionView(
                id=entry.id,
                session=session,
                files=file_views(settings, plan, entry.files),
                proposals=[p for p in plan.proposals if p.session_id == entry.id],
                materials=session_fingerprint(plan, entry.id),
            )
            for entry, session in zip(plan.sessions, transcript.sessions, strict=True)
        ]
        if transcript
        else []
    )
    return PlanView(
        course=course,
        primary=plan.primary,
        transcript=transcript,
        sessions=sessions,
        unassigned=file_views(settings, plan, plan.unassigned),
        books=book_views(plan, transcript),
        mapped=bool(plan.books),
        materials=materials_fingerprint(plan),
    )


def find_session(plan: Plan, session_id: str) -> PlanSession:
    for entry in plan.sessions:
        if entry.id == session_id:
            return entry
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")


def find_proposal(plan: Plan, proposal_id: str) -> Proposal:
    for proposal in plan.proposals:
        if proposal.id == proposal_id:
            return proposal
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")


def delete_excerpt(settings: Settings, plan: Plan, path: str, *, forget: bool) -> None:
    """Remove an excerpt file. Its proposal goes back to review, or away with `forget`."""
    (settings.uploads_dir / path).unlink(missing_ok=True)
    if forget:
        plan.proposals = [p for p in plan.proposals if p.excerpt != path]
        return
    plan.proposals = [p for p in plan.proposals if not (p.excerpt == path and not p.reading)]
    for proposal in plan.proposals:
        if proposal.excerpt == path:
            proposal.excerpt = None
            proposal.status = "proposed"


def excerpt_name(directory: Path, book: str, label: str) -> str:
    stem = Path(book).stem[:60]
    base = safe_name(f"{stem} - {label}"[:120])
    name, n = f"{base}.pdf", 2
    while (directory / name).exists():
        name, n = f"{base} ({n}).pdf", n + 1
    return name


def check_pages(book: Path, start: int, end: int) -> None:
    count = len(PdfReader(book).pages) if book.is_file() else 0
    if not 1 <= start <= end <= count:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Pages must be within 1-{count}, start ≤ end"
        )


def printed_pages(settings: Settings, course: str, book: Path, start: int, end: int) -> str | None:
    index = load_index(course_dir(settings, course), book, sha256(book))
    return printed_range(index, start, end) if index else None


def approve(settings: Settings, course: str, plan: Plan, proposal: Proposal) -> None:
    if proposal.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, "This proposal is already decided")
    if proposal.pdf_start is None or proposal.pdf_end is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter the pages first")
    entry = find_session(plan, proposal.session_id)
    book = settings.uploads_dir / proposal.book
    if not book.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The book file is gone")

    directory = course_dir(settings, course) / "excerpts" / entry.id
    name = excerpt_name(directory, proposal.book, proposal.label)
    cut_excerpt(book, proposal.pdf_start, proposal.pdf_end, directory / name)

    path = f"{course}/excerpts/{entry.id}/{name}"
    entry.files.append(path)
    proposal.status = "approved"
    proposal.excerpt = path
    print(f"Cut excerpt {path} (PDF pages {proposal.pdf_start}-{proposal.pdf_end})")


@router.get("/{course}")
def get_plan(course: str, settings: Annotated[Settings, Depends(get_settings)]) -> PlanView:
    return render(settings, course, *current(settings, course))


@router.put("/{course}/primary")
def put_primary(
    course: str, body: PathRequest, settings: Annotated[Settings, Depends(get_settings)]
) -> PlanView:
    file = syllabus_file(settings, body.path)
    if file.relative_to(settings.uploads_dir.resolve()).parts[0] != course:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Syllabus belongs to another course")
    if load_transcript(file) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Transcribe this syllabus first")
    directory = course_dir(settings, course)
    plan = load_plan(directory)
    plan.primary = file.relative_to(settings.uploads_dir.resolve()).as_posix()
    save_plan(directory, plan)
    return render(settings, course, *current(settings, course))


@router.post("/{course}/sessions/{session_id}/files")
def attach_file(
    course: str,
    session_id: str,
    body: PathRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlanView:
    plan, transcript = current(settings, course)
    entry = find_session(plan, session_id)
    path = reading_file(settings, course, body.path)
    if path not in entry.files:
        entry.files.append(path)
    plan.unassigned = [f for f in plan.unassigned if f != path]
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)


@router.post("/{course}/sessions/{session_id}/lecture-files")
async def upload_lecture_files(
    course: str,
    session_id: str,
    files: Annotated[list[UploadFile], File()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlanView:
    """Files for one lecture only, stored under <course>/lecture/<session>/ and attached to it."""
    plan, transcript = current(settings, course)
    entry = find_session(plan, session_id)
    if not SESSION_ID.match(entry.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This lecture can't hold its own files")
    directory = course_dir(settings, course) / "lecture" / entry.id
    directory.mkdir(parents=True, exist_ok=True)
    for upload in files:
        dest = directory / safe_name(upload.filename or "")
        with dest.open("wb") as out:
            shutil.copyfileobj(upload.file, out)
        path = f"{course}/lecture/{entry.id}/{dest.name}"
        if path not in entry.files:
            entry.files.append(path)
        print(f"Saved lecture file: {path} ({dest.stat().st_size} bytes)")
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)


@router.post("/{course}/sessions/{session_id}/excerpts")
def add_excerpt(
    course: str,
    session_id: str,
    body: ExcerptRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlanView:
    plan, transcript = current(settings, course)
    entry = find_session(plan, session_id)
    path = reading_file(settings, course, body.path)
    if not path.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files can be cropped")
    book = settings.uploads_dir / path
    start, end = body.pdf_start, body.pdf_end
    check_pages(book, start, end)
    proposal = Proposal(
        id=new_id(),
        session_id=entry.id,
        reading="",
        book=path,
        label=f"PDF p. {start}" if start == end else f"PDF pp. {start}–{end}",
        pdf_start=start,
        pdf_end=end,
        printed=printed_pages(settings, course, book, start, end),
        method="manual",
    )
    plan.proposals.append(proposal)
    approve(settings, course, plan, proposal)
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)


@router.delete("/{course}/sessions/{session_id}/files")
def detach_file(
    course: str,
    session_id: str,
    path: Annotated[str, Query()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlanView:
    plan, transcript = current(settings, course)
    entry = find_session(plan, session_id)
    if path in entry.files and is_excerpt(path):
        delete_excerpt(settings, plan, path, forget=False)
    if path in entry.files and is_lecture_file(path):
        # It belongs to this lecture alone.
        (settings.uploads_dir / path).unlink(missing_ok=True)
    entry.files = [f for f in entry.files if f != path]
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)


@router.delete("/{course}/unassigned")
def dismiss_unassigned(
    course: str,
    path: Annotated[str, Query()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlanView:
    plan, transcript = current(settings, course)
    if path in plan.unassigned and is_excerpt(path):
        delete_excerpt(settings, plan, path, forget=True)
    if path in plan.unassigned and is_lecture_file(path):
        (settings.uploads_dir / path).unlink(missing_ok=True)
    plan.unassigned = [f for f in plan.unassigned if f != path]
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)


@router.post("/{course}/map")
async def map_materials(
    course: str,
    settings: Annotated[Settings, Depends(get_settings)],
    worker: Annotated[WorkerClient, Depends(get_worker_client)],
) -> PlanView:
    plan, transcript = current(settings, course)
    if transcript is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Transcribe a syllabus first")

    directory = course_dir(settings, course)
    reply = await worker.map_materials(
        MapRequest(
            course=course,
            plan=plan,
            transcript=transcript,
            books=reading_paths(settings, course),
        )
    )
    matches, proposals = reply.matches, reply.proposals

    # The run takes a while: apply its results to the plan as it is now.
    plan, transcript = current(settings, course)
    confirmed = {(b.material, b.raw) for b in plan.books if b.confirmed}
    plan.books = [b for b in plan.books if b.confirmed] + [
        m for m in matches if (m.material, m.raw) not in confirmed
    ]
    merge_proposals(plan, proposals)
    save_plan(directory, plan)
    print(f"Mapped {course}: {len(proposals)} proposals")
    return render(settings, course, plan, transcript)


@router.put("/{course}/books/{material}")
def put_book(
    course: str,
    material: int,
    body: BookRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlanView:
    plan, transcript = current(settings, course)
    if transcript is None or not 0 <= material < len(transcript.learning_materials):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course material not found")
    path = reading_file(settings, course, body.file) if body.file else None
    if path and not path.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF books can be mapped")

    raw = transcript.learning_materials[material].raw
    old = next((b for b in plan.books if b.material == material and b.raw == raw), None)
    plan.books = [b for b in plan.books if b.material != material]
    plan.books.append(BookMatch(material=material, raw=raw, file=path, confirmed=True))
    if old and old.file and old.file != path:
        plan.proposals = [
            p for p in plan.proposals if not (p.status == "proposed" and p.book == old.file)
        ]
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)


@router.post("/{course}/proposals/approve-all")
def approve_all(course: str, settings: Annotated[Settings, Depends(get_settings)]) -> PlanView:
    plan, transcript = current(settings, course)
    for proposal in plan.proposals:
        if (
            proposal.status == "proposed"
            and proposal.method in EXACT_METHODS
            and proposal.pdf_start is not None
        ):
            approve(settings, course, plan, proposal)
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)


@router.post("/{course}/proposals/{proposal_id}/approve")
def approve_proposal(
    course: str,
    proposal_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    body: PagesRequest | None = None,
) -> PlanView:
    plan, transcript = current(settings, course)
    proposal = find_proposal(plan, proposal_id)
    if body and body.pdf_start is not None and body.pdf_end is not None:
        pages = (body.pdf_start, body.pdf_end)
        if pages != (proposal.pdf_start, proposal.pdf_end):
            book = settings.uploads_dir / proposal.book
            check_pages(book, *pages)
            proposal.pdf_start, proposal.pdf_end = pages
            proposal.printed = printed_pages(settings, course, book, *pages)
            proposal.method = "manual"
    approve(settings, course, plan, proposal)
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)


@router.post("/{course}/proposals/{proposal_id}/reject")
def reject_proposal(
    course: str, proposal_id: str, settings: Annotated[Settings, Depends(get_settings)]
) -> PlanView:
    plan, transcript = current(settings, course)
    proposal = find_proposal(plan, proposal_id)
    if proposal.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, "This proposal is already decided")
    proposal.status = "rejected"
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)


@router.post("/{course}/proposals/{proposal_id}/reopen")
def reopen_proposal(
    course: str, proposal_id: str, settings: Annotated[Settings, Depends(get_settings)]
) -> PlanView:
    plan, transcript = current(settings, course)
    proposal = find_proposal(plan, proposal_id)
    if proposal.status != "rejected":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only rejected proposals can be reopened")
    proposal.status = "proposed"
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)
