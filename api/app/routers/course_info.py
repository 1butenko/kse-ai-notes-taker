import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints

from app import db, users
from app.auth import (
    CurrentPrincipal,
    course_owner,
    owned_course,
    shared_course,
    storage_unavailable,
)
from app.config import Settings, get_settings
from app.course import CourseInfo, load_info, save_info
from app.routers.agent import ensure_course
from app.routers.plans import COURSE, course_dir

router = APIRouter(prefix="/course-info", tags=["course-info"])


class CourseInfoRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


@router.get("")
def list_course_info(
    settings: Annotated[Settings, Depends(get_settings)], principal: CurrentPrincipal
) -> list[CourseInfo]:
    """The signed-in teacher's courses and the shared ones, newest first."""
    with storage_unavailable():
        keys = set(users.owned_course_keys(principal.user_id)) | set(settings.shared_courses)
    found = [load_info(course_dir(settings, key)) for key in keys if COURSE.match(key)]
    return sorted((i for i in found if i), key=lambda i: i.created_at, reverse=True)


def claim(course: str, name: str, user_id: UUID) -> None:
    """Link the course to its row, owned by this teacher. 409 when another teacher has it,
    unless the course is shared."""
    moodle_id = int(course) if course.isdigit() else None
    with db.transaction() as conn:
        row = ensure_course(conn, course, name, moodle_id, user_id)
        if row["owner_id"] != user_id and not shared_course(course):
            # Raised inside the transaction, so the title change rolls back too.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This Moodle course is already set up by another teacher",
            )


def release(course: str) -> None:
    """Start over: the course no longer belongs to anyone, so anyone may set it up again."""
    with db.transaction() as conn:
        conn.execute("UPDATE courses SET owner_id = NULL WHERE course_key = %s", (course,))


@router.get("/{course}", dependencies=[Depends(owned_course)])
def get_course_info(
    course: str, settings: Annotated[Settings, Depends(get_settings)]
) -> CourseInfo:
    info = load_info(course_dir(settings, course))
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return info


@router.put("/{course}")
def put_course_info(
    course: str,
    body: CourseInfoRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    principal: CurrentPrincipal,
) -> CourseInfo:
    """Create the course for the signed-in teacher, or rename theirs."""
    directory = course_dir(settings, course)
    with storage_unavailable():
        claim(course, body.name, principal.user_id)
    previous = load_info(directory)
    info = CourseInfo(
        course=course,
        name=body.name,
        created_at=previous.created_at if previous else datetime.now(UTC).isoformat(),
        readings_approved_at=previous.readings_approved_at if previous else None,
    )
    save_info(directory, info)
    return info


def approval(settings: Settings, course: str, approved_at: str | None) -> CourseInfo:
    directory = course_dir(settings, course)
    info = load_info(directory)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    info = info.model_copy(update={"readings_approved_at": approved_at})
    save_info(directory, info)
    return info


@router.post("/{course}/readings-approval", dependencies=[Depends(owned_course)])
def approve_readings(
    course: str, settings: Annotated[Settings, Depends(get_settings)]
) -> CourseInfo:
    """The lecturer approved the readings per lecture."""
    return approval(settings, course, datetime.now(UTC).isoformat(timespec="seconds"))


@router.delete("/{course}/readings-approval", dependencies=[Depends(owned_course)])
def revoke_readings_approval(
    course: str, settings: Annotated[Settings, Depends(get_settings)]
) -> CourseInfo:
    return approval(settings, course, None)


def trash_dir(settings: Settings) -> Path:
    """Where Start over puts a course. Not a course key, so it is never listed."""
    return settings.uploads_dir / ".trash"


@router.delete(
    "/{course}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(owned_course)]
)
def delete_course(
    course: str, settings: Annotated[Settings, Depends(get_settings)], principal: CurrentPrincipal
) -> None:
    """Start over: the course folder and its uploads move to the trash, and the course is no
    longer the teacher's. Visual notes live in S3 and Aurora and are not touched; a run going on
    keeps the readings it already read. A shared course is only its owner's to start over."""
    with storage_unavailable():
        if (
            principal.kind == "user"
            and shared_course(course)
            and course_owner(course) != principal.user_id
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only the course's owner can start a shared course over"
            )
        release(course)
    directory = course_dir(settings, course)
    if not directory.is_dir():
        return
    trash_dir(settings).mkdir(parents=True, exist_ok=True)
    target = trash_dir(settings) / f"{course}-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}"
    shutil.move(directory, target)
    print(f"Moved course storage to the trash: {course} -> {target.name}")
