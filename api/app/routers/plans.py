import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.plan import Plan, load_plan, save_plan, sync
from app.routers.syllabus import load_transcript, syllabus_file
from app.routers.uploads import SavedFile
from app.syllabus import Session, Transcript

router = APIRouter(prefix="/plans", tags=["plans"])

COURSE = re.compile(r"^(local|\d+)$")


class PathRequest(BaseModel):
    path: str


class SessionView(BaseModel):
    id: str
    session: Session
    files: list[SavedFile]


class PlanView(BaseModel):
    course: str
    primary: str | None
    transcript: Transcript | None
    sessions: list[SessionView]
    unassigned: list[SavedFile]


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


def saved_files(settings: Settings, paths: list[str]) -> list[SavedFile]:
    result = []
    for path in paths:
        file = settings.uploads_dir / path
        if file.is_file():
            result.append(SavedFile(path=path, size=file.stat().st_size))
    return result


def current(settings: Settings, course: str) -> tuple[Plan, Transcript | None]:
    """Load the course plan, re-aligned with its primary transcript."""
    directory = course_dir(settings, course)
    plan = load_plan(directory)
    transcript = load_transcript(settings.uploads_dir / plan.primary) if plan.primary else None
    if transcript and sync(plan, transcript):
        save_plan(directory, plan)
    return plan, transcript


def render(settings: Settings, course: str, plan: Plan, transcript: Transcript | None) -> PlanView:
    sessions = (
        [
            SessionView(id=entry.id, session=session, files=saved_files(settings, entry.files))
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
        unassigned=saved_files(settings, plan.unassigned),
    )


def find_session(plan: Plan, session_id: str):
    for entry in plan.sessions:
        if entry.id == session_id:
            return entry
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")


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


@router.delete("/{course}/sessions/{session_id}/files")
def detach_file(
    course: str,
    session_id: str,
    path: Annotated[str, Query()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlanView:
    plan, transcript = current(settings, course)
    entry = find_session(plan, session_id)
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
    plan.unassigned = [f for f in plan.unassigned if f != path]
    save_plan(course_dir(settings, course), plan)
    return render(settings, course, plan, transcript)
