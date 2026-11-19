import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints

from app import db, team, users
from app.auth import (
    CurrentPrincipal,
    Role,
    actor,
    lectured_course,
    owned_course,
    storage_unavailable,
)
from app.config import Settings, get_settings
from app.course import CourseInfo, load_info, save_info
from app.routers.agent import ensure_course
from app.routers.plans import COURSE, course_dir

router = APIRouter(prefix="/course-info", tags=["course-info"])


class CourseInfoRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class CourseListItem(CourseInfo):
    """A course in the list, with the caller's role on it (for its badge)."""

    role: Role


def visible_courses(settings: Settings, user_id: UUID) -> dict[str, Role]:
    """Course key -> role: the user's courses, or every course for an admin."""
    user = users.get_user(user_id)
    email = user["email"] if user else None
    mine: dict[str, Role] = dict(team.member_courses(email)) if email else {}
    if not settings.is_admin(email):
        return mine
    root = settings.uploads_dir
    every = [d.name for d in root.iterdir() if d.is_dir()] if root.is_dir() else []
    return {key: mine.get(key, "admin") for key in every}


@router.get("")
def list_course_info(
    settings: Annotated[Settings, Depends(get_settings)], principal: CurrentPrincipal
) -> list[CourseListItem]:
    """The signed-in teacher's courses (every course for an admin), newest first."""
    with storage_unavailable():
        roles = visible_courses(settings, principal.user_id)
    found = [
        (load_info(course_dir(settings, key)), role)
        for key, role in roles.items()
        if COURSE.match(key)
    ]
    items = [CourseListItem(**info.model_dump(), role=role) for info, role in found if info]
    return sorted(items, key=lambda i: i.created_at, reverse=True)


def claim(course: str, name: str, user_id: UUID, settings: Settings) -> None:
    """Link the course to its row. Whoever sets up a course with no lecturer becomes its
    lecturer; members and admins may rename it. Anyone else gets 409, naming the lecturer."""
    moodle_id = int(course) if course.isdigit() else None
    with db.transaction() as conn:
        row = ensure_course(conn, course, name, moodle_id, user_id)
        user = conn.execute("SELECT email FROM users WHERE id = %s", (user_id,)).fetchone()
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again")
        if team.role_of(conn, row["id"], user["email"]) is not None:
            return
        current = team.lecturer(conn, row["id"])
        if current is None:
            team.add_member(conn, row["id"], user["email"], "lecturer", user_id)
            return
        if settings.is_admin(user["email"]):
            return
        # Raised inside the transaction, so the title change rolls back too.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This course is already set up by {team.display_name(current)}."
            " Ask them to add you to it.",
        )


def release(course: str, user_id: UUID | None) -> None:
    """Start over: the course no longer has members, so anyone may set it up again."""
    with db.transaction() as conn:
        course_uuid = team.course_id(conn, course)
        if course_uuid is None:
            return
        team.add_event(conn, course_uuid, user_id, "course_started_over")
        team.clear_members(conn, course_uuid)


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
        claim(course, body.name, principal.user_id, settings)
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
    course: str, settings: Annotated[Settings, Depends(get_settings)], principal: CurrentPrincipal
) -> CourseInfo:
    """The lecturer or a TA approved the readings per lecture."""
    info = approval(settings, course, datetime.now(UTC).isoformat(timespec="seconds"))
    team.record(course, actor(principal), "readings_approved")
    return info


@router.delete("/{course}/readings-approval", dependencies=[Depends(owned_course)])
def revoke_readings_approval(
    course: str, settings: Annotated[Settings, Depends(get_settings)], principal: CurrentPrincipal
) -> CourseInfo:
    info = approval(settings, course, None)
    team.record(course, actor(principal), "readings_approval_revoked")
    return info


def trash_dir(settings: Settings) -> Path:
    """Where Start over puts a course. Not a course key, so it is never listed."""
    return settings.uploads_dir / ".trash"


@router.delete(
    "/{course}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(lectured_course)]
)
def delete_course(
    course: str, settings: Annotated[Settings, Depends(get_settings)], principal: CurrentPrincipal
) -> None:
    """Start over (the lecturer or an admin): the course folder and its uploads move to the
    trash, and the course has no members any more. Visual notes live in S3 and Aurora and are
    not touched; a run going on keeps the readings it already read."""
    with storage_unavailable():
        release(course, actor(principal))
    directory = course_dir(settings, course)
    if not directory.is_dir():
        return
    trash_dir(settings).mkdir(parents=True, exist_ok=True)
    target = trash_dir(settings) / f"{course}-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}"
    shutil.move(directory, target)
    print(f"Moved course storage to the trash: {course} -> {target.name}")
