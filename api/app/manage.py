"""Database tasks: `uv run python -m app.manage init-db | list | set-lecturer <key> <email>`."""

import argparse

from app import db, team


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the AI Note Taker database.")
    parser.add_argument("command", choices=["init-db", "list", "set-lecturer"])
    parser.add_argument("course_key", nargs="?", help="set-lecturer: the course key")
    parser.add_argument("email", nargs="?", help="set-lecturer: the lecturer's email")
    args = parser.parse_args()

    if args.command == "init-db":
        db.apply_schema()
        print("Schema applied.")
        return

    if args.command == "set-lecturer":
        # For a course with no lecturer (made before sign-in); admins can also do it in the app.
        if not args.course_key or not args.email:
            parser.error("set-lecturer needs a course key and an email")
        with db.transaction() as conn:
            course_uuid = team.course_id(conn, args.course_key)
            if course_uuid is None:
                raise SystemExit("No such course.")
            try:
                team.set_lecturer(conn, course_uuid, args.email, None)
            except team.TeamError as error:
                raise SystemExit(str(error)) from error
        print(f"{args.email} is now the lecturer of course {args.course_key}.")
        return

    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT c.s3_prefix, c.course_key, c.title, m.email FROM courses c"
            " LEFT JOIN course_members m ON m.course_id = c.id AND m.role = 'lecturer'"
            " ORDER BY c.created_at DESC"
        ).fetchall()
    for row in rows:
        owner = row["email"] or "(no lecturer)"
        print(f"{row['s3_prefix']}  {row['course_key'] or '-'}  {row['title']}  {owner}")


if __name__ == "__main__":
    main()
