"""Course members (one lecturer, any number of TAs) and the course's activity log.

Members are kept by email (`course_members`), so a TA can be added before their first
sign-in; a user is a member when their `users.email` matches. Admins (`PLATFORM_ADMINS`) are not
members: app/auth.py gives them a lecturer's rights on every course.

Every function that takes `conn` runs inside the caller's transaction.
"""

from typing import Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb

from app import db

MemberRole = Literal["lecturer", "ta"]

# Activity kinds, as the web shows them.
EventKind = Literal[
    "material_uploaded",
    "material_deleted",
    "moodle_synced",
    "notes_generated",
    "readings_approved",
    "readings_approval_revoked",
    "member_added",
    "member_removed",
    "lecturer_changed",
    "course_started_over",
]


class TeamError(ValueError):
    """A change the team rules refuse; the message is shown to the user."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def course_id(conn: Any, course: str) -> UUID | None:
    row = conn.execute("SELECT id FROM courses WHERE course_key = %s", (course,)).fetchone()
    return row["id"] if row else None


def course_access(course: str, user_id: UUID) -> tuple[str | None, MemberRole | None]:
    """The user's email, and their role on the course (None: not a member). The email is None
    when the user is unknown."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT u.email, m.role FROM users u"
            " LEFT JOIN courses c ON c.course_key = %s"
            " LEFT JOIN course_members m ON m.course_id = c.id AND m.email = u.email"
            " WHERE u.id = %s",
            (course, user_id),
        ).fetchone()
    return (row["email"], row["role"]) if row else (None, None)


def member_courses(email: str) -> dict[str, MemberRole]:
    """Course key -> role, for every course this email is a member of."""
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT c.course_key, m.role FROM course_members m"
            " JOIN courses c ON c.id = m.course_id"
            " WHERE m.email = %s AND c.course_key IS NOT NULL",
            (normalize_email(email),),
        ).fetchall()
    return {row["course_key"]: row["role"] for row in rows}


def role_of(conn: Any, course_uuid: UUID, email: str) -> MemberRole | None:
    row = conn.execute(
        "SELECT role FROM course_members WHERE course_id = %s AND email = %s",
        (course_uuid, normalize_email(email)),
    ).fetchone()
    return row["role"] if row else None


def lecturer(conn: Any, course_uuid: UUID) -> dict[str, Any] | None:
    """The lecturer's email and, once they have signed in, their names."""
    return conn.execute(
        "SELECT m.email, u.first_name, u.last_name FROM course_members m"
        " LEFT JOIN users u ON u.email = m.email"
        " WHERE m.course_id = %s AND m.role = 'lecturer'",
        (course_uuid,),
    ).fetchone()


def display_name(row: dict[str, Any]) -> str:
    name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
    return name or row["email"]


def members(conn: Any, course_uuid: UUID) -> list[dict[str, Any]]:
    """The lecturer first, then TAs in the order they were added."""
    return conn.execute(
        "SELECT m.email, m.role, m.added_at, u.id AS user_id, u.first_name, u.last_name,"
        " u.avatar_url FROM course_members m LEFT JOIN users u ON u.email = m.email"
        " WHERE m.course_id = %s ORDER BY m.role = 'lecturer' DESC, m.added_at, m.email",
        (course_uuid,),
    ).fetchall()


def add_member(
    conn: Any, course_uuid: UUID, email: str, role: MemberRole, added_by: UUID | None
) -> None:
    email = normalize_email(email)
    if role_of(conn, course_uuid, email) is not None:
        raise TeamError(f"{email} is already on this course")
    if role == "lecturer" and lecturer(conn, course_uuid) is not None:
        raise TeamError("This course already has a lecturer")
    conn.execute(
        "INSERT INTO course_members (course_id, email, role, added_by) VALUES (%s, %s, %s, %s)",
        (course_uuid, email, role, added_by),
    )


def remove_member(conn: Any, course_uuid: UUID, email: str) -> MemberRole:
    """The removed member's role. The lecturer stays until they hand the role over."""
    email = normalize_email(email)
    role = role_of(conn, course_uuid, email)
    if role is None:
        raise TeamError(f"{email} is not on this course")
    if role == "lecturer":
        raise TeamError("Hand the lecturer role to someone else before removing the lecturer")
    conn.execute(
        "DELETE FROM course_members WHERE course_id = %s AND email = %s", (course_uuid, email)
    )
    return role


def set_lecturer(conn: Any, course_uuid: UUID, email: str, by: UUID | None) -> str | None:
    """Make this email the lecturer, adding them if needed; the previous lecturer stays on as a
    TA. Returns the previous lecturer's email."""
    email = normalize_email(email)
    previous = lecturer(conn, course_uuid)
    if previous is not None and previous["email"] == email:
        raise TeamError(f"{email} is already the lecturer")
    conn.execute(
        "UPDATE course_members SET role = 'ta' WHERE course_id = %s AND role = 'lecturer'",
        (course_uuid,),
    )
    conn.execute(
        "INSERT INTO course_members (course_id, email, role, added_by)"
        " VALUES (%s, %s, 'lecturer', %s)"
        " ON CONFLICT (course_id, email) DO UPDATE SET role = 'lecturer'",
        (course_uuid, email, by),
    )
    return previous["email"] if previous else None


def clear_members(conn: Any, course_uuid: UUID) -> None:
    """Start over: nobody is on the course, so anyone may set it up again."""
    conn.execute("DELETE FROM course_members WHERE course_id = %s", (course_uuid,))
    conn.execute("UPDATE courses SET owner_id = NULL WHERE id = %s", (course_uuid,))


def add_event(
    conn: Any,
    course_uuid: UUID,
    actor: UUID | None,
    kind: EventKind,
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO course_events (course_id, actor_id, kind, details) VALUES (%s, %s, %s, %s)",
        (course_uuid, actor, kind, Jsonb(details or {})),
    )


def record(
    course: str, actor: UUID | None, kind: EventKind, details: dict[str, Any] | None = None
) -> None:
    """Log an event on the course, best effort: the action it describes already happened, so a
    database problem here must not fail the request. A course without a row is not logged."""
    try:
        with db.transaction() as conn:
            course_uuid = course_id(conn, course)
            if course_uuid is not None:
                add_event(conn, course_uuid, actor, kind, details)
    except db.DatabaseNotConfigured:
        return
    except Exception as error:  # noqa: BLE001 - logging must never break the action
        print(f"Could not log {kind} on course {course}: {error!r}")


def events(conn: Any, course_uuid: UUID, limit: int) -> list[dict[str, Any]]:
    """Newest first, with who did it (NULL: the worker, or before the log existed)."""
    return conn.execute(
        "SELECT e.id, e.kind, e.details, e.created_at, u.email, u.first_name, u.last_name"
        " FROM course_events e LEFT JOIN users u ON u.id = e.actor_id"
        " WHERE e.course_id = %s ORDER BY e.created_at DESC, e.id LIMIT %s",
        (course_uuid, limit),
    ).fetchall()
