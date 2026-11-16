"""Teachers (`users` rows) and the courses they own."""

from typing import Any
from uuid import UUID

from app import db

USER_COLUMNS = "id, email, first_name, last_name, avatar_url, created_at"


def upsert_from_google(
    google_sub: str, email: str, first_name: str, last_name: str, avatar_url: str | None
) -> dict[str, Any]:
    """Record a sign-in. A returning teacher keeps the names they edited; Google's names fill
    them only while they are empty."""
    with db.transaction() as conn:
        row = conn.execute(
            "INSERT INTO users (google_sub, email, first_name, last_name, avatar_url,"
            " last_login_at) VALUES (%s, %s, %s, %s, %s, now())"
            " ON CONFLICT (google_sub) DO UPDATE SET email = EXCLUDED.email,"
            " avatar_url = EXCLUDED.avatar_url, last_login_at = now(),"
            " first_name = CASE WHEN users.first_name = '' THEN EXCLUDED.first_name"
            "   ELSE users.first_name END,"
            " last_name = CASE WHEN users.last_name = '' THEN EXCLUDED.last_name"
            "   ELSE users.last_name END"
            f" RETURNING {USER_COLUMNS}",
            (google_sub, email.lower(), first_name, last_name, avatar_url),
        ).fetchone()
    assert row is not None
    return row


def get_user(user_id: UUID) -> dict[str, Any] | None:
    with db.transaction() as conn:
        return conn.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE id = %s", (user_id,)
        ).fetchone()


def update_names(user_id: UUID, first_name: str, last_name: str) -> dict[str, Any] | None:
    with db.transaction() as conn:
        return conn.execute(
            f"UPDATE users SET first_name = %s, last_name = %s WHERE id = %s"
            f" RETURNING {USER_COLUMNS}",
            (first_name, last_name, user_id),
        ).fetchone()


def owned_course_keys(user_id: UUID) -> list[str]:
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT course_key FROM courses WHERE owner_id = %s AND course_key IS NOT NULL",
            (user_id,),
        ).fetchall()
    return [row["course_key"] for row in rows]


def claim_course(course_key: str, email: str) -> bool:
    """Give an existing course (made before sign-in) to the teacher with this email."""
    with db.transaction() as conn:
        row = conn.execute(
            "UPDATE courses SET owner_id = u.id FROM users u"
            " WHERE courses.course_key = %s AND u.email = %s RETURNING courses.id",
            (course_key, email.lower()),
        ).fetchone()
    return row is not None
