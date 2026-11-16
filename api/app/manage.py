"""Database tasks: `uv run python -m app.manage init-db | list | claim-course <key> <email>`."""

import argparse

from app import db, users


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the AI Note Taker database.")
    parser.add_argument("command", choices=["init-db", "list", "claim-course"])
    parser.add_argument("course_key", nargs="?", help="claim-course: the course key")
    parser.add_argument("email", nargs="?", help="claim-course: the teacher's email")
    args = parser.parse_args()

    if args.command == "init-db":
        db.apply_schema()
        print("Schema applied.")
        return

    if args.command == "claim-course":
        if not args.course_key or not args.email:
            parser.error("claim-course needs a course key and an email")
        if not users.claim_course(args.course_key, args.email):
            raise SystemExit("No such course, or that teacher has not signed in yet.")
        print(f"Course {args.course_key} now belongs to {args.email}.")
        return

    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT c.s3_prefix, c.course_key, c.title, u.email FROM courses c"
            " LEFT JOIN users u ON u.id = c.owner_id ORDER BY c.created_at DESC"
        ).fetchall()
    for row in rows:
        owner = row["email"] or "(no owner)"
        print(f"{row['s3_prefix']}  {row['course_key'] or '-'}  {row['title']}  {owner}")


if __name__ == "__main__":
    main()
