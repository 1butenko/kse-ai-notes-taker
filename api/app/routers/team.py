"""A course's team: its members (one lecturer, TAs) and its activity log (the Team tab).

Everyone on the course sees both; the lecturer and admins add and remove TAs and hand the
lecturer role over (app/auth.py).
"""

import asyncio
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, StringConstraints

from app import db, team
from app.auth import CurrentPrincipal, Role, actor, authorize_course, storage_unavailable
from app.config import Settings, get_settings
from app.course import load_info
from app.routers.agent import ensure_course
from app.routers.plans import course_dir

router = APIRouter(prefix="/team", tags=["team"])

Email = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]


class Member(BaseModel):
    email: str
    role: team.MemberRole
    # Empty until they have signed in.
    name: str
    signed_in: bool
    avatar_url: str | None
    added_at: datetime


class Team(BaseModel):
    my_role: Role
    members: list[Member]


class EmailRequest(BaseModel):
    email: Email


class Event(BaseModel):
    id: UUID
    kind: str
    details: dict[str, Any]
    at: datetime
    # None: the worker, or something that happened before the log existed.
    actor_email: str | None
    actor_name: str | None


def member_view(row: dict[str, Any]) -> Member:
    name = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
    return Member(
        email=row["email"],
        role=row["role"],
        name=name,
        signed_in=row["user_id"] is not None,
        avatar_url=row["avatar_url"],
        added_at=row["added_at"],
    )


def course_row(conn: Any, settings: Settings, course: str) -> UUID:
    """The course's row id, created from its course.json when it has none yet."""
    course_uuid = team.course_id(conn, course)
    if course_uuid is not None:
        return course_uuid
    info = load_info(course_dir(settings, course))
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    moodle_id = int(course) if course.isdigit() else None
    return ensure_course(conn, course, info.name, moodle_id)["id"]


def read_team(settings: Settings, course: str, role: Role) -> Team:
    with db.transaction() as conn:
        course_uuid = team.course_id(conn, course)
        rows = team.members(conn, course_uuid) if course_uuid else []
    return Team(my_role=role, members=[member_view(row) for row in rows])


def check_email(settings: Settings, email: str) -> str:
    email = team.normalize_email(email)
    local, _, domain = email.rpartition("@")
    if not local or domain not in {d.lower() for d in settings.member_email_domains}:
        allowed = ", ".join(f"@{d}" for d in settings.member_email_domains)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Use a {allowed} email")
    return email


def change(settings: Settings, course: str, apply: Any) -> None:
    """Run `apply(conn, course_uuid)` in one transaction; team rule errors become 409."""
    try:
        with db.transaction() as conn:
            apply(conn, course_row(conn, settings, course))
    except team.TeamError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


Config = Annotated[Settings, Depends(get_settings)]


@router.get("/{course}", response_model=Team)
async def get_team(course: str, principal: CurrentPrincipal, settings: Config) -> Team:
    role = await asyncio.to_thread(authorize_course, principal, course, settings)
    with storage_unavailable():
        return await asyncio.to_thread(read_team, settings, course, role)


@router.post("/{course}/members", response_model=Team, status_code=status.HTTP_201_CREATED)
async def add_member(
    course: str, body: EmailRequest, principal: CurrentPrincipal, settings: Config
) -> Team:
    """Add a TA by email; they see the course from their next sign-in."""
    role = await asyncio.to_thread(authorize_course, principal, course, settings, "lecturer")
    email = check_email(settings, body.email)
    by = actor(principal)

    def apply(conn: Any, course_uuid: UUID) -> None:
        team.add_member(conn, course_uuid, email, "ta", by)
        team.add_event(conn, course_uuid, by, "member_added", {"email": email, "role": "ta"})

    with storage_unavailable():
        await asyncio.to_thread(change, settings, course, apply)
        return await asyncio.to_thread(read_team, settings, course, role)


@router.delete("/{course}/members", response_model=Team)
async def remove_member(
    course: str,
    email: Annotated[str, Query(min_length=3, max_length=320)],
    principal: CurrentPrincipal,
    settings: Config,
) -> Team:
    """Remove a TA. Their past activity stays in the log."""
    role = await asyncio.to_thread(authorize_course, principal, course, settings, "lecturer")
    email = team.normalize_email(email)
    by = actor(principal)

    def apply(conn: Any, course_uuid: UUID) -> None:
        removed = team.remove_member(conn, course_uuid, email)
        team.add_event(conn, course_uuid, by, "member_removed", {"email": email, "role": removed})

    with storage_unavailable():
        await asyncio.to_thread(change, settings, course, apply)
        return await asyncio.to_thread(read_team, settings, course, role)


@router.put("/{course}/lecturer", response_model=Team)
async def hand_over(
    course: str, body: EmailRequest, principal: CurrentPrincipal, settings: Config
) -> Team:
    """Make someone the lecturer (added if not on the course yet); the previous lecturer stays
    on as a TA. Also how an admin gives a course with no lecturer one."""
    role = await asyncio.to_thread(authorize_course, principal, course, settings, "lecturer")
    email = check_email(settings, body.email)
    by = actor(principal)

    def apply(conn: Any, course_uuid: UUID) -> None:
        previous = team.set_lecturer(conn, course_uuid, email, by)
        details = {"email": email, "previous": previous}
        team.add_event(conn, course_uuid, by, "lecturer_changed", details)

    with storage_unavailable():
        await asyncio.to_thread(change, settings, course, apply)
        # The caller may have just handed their own role over.
        role = await asyncio.to_thread(authorize_course, principal, course, settings)
        return await asyncio.to_thread(read_team, settings, course, role)


@router.get("/{course}/activity", response_model=list[Event])
async def get_activity(
    course: str,
    principal: CurrentPrincipal,
    settings: Config,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Event]:
    """Who did what on the course, newest first."""
    await asyncio.to_thread(authorize_course, principal, course, settings)

    def read() -> list[dict[str, Any]]:
        with db.transaction() as conn:
            course_uuid = team.course_id(conn, course)
            return team.events(conn, course_uuid, limit) if course_uuid else []

    with storage_unavailable():
        rows = await asyncio.to_thread(read)
    return [
        Event(
            id=row["id"],
            kind=row["kind"],
            details=row["details"] or {},
            at=row["created_at"],
            actor_email=row["email"],
            actor_name=team.display_name(row) if row["email"] else None,
        )
        for row in rows
    ]
