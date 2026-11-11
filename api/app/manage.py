"""AI Note Taker database tasks: `uv run python -m app.manage init-db | list`."""

import argparse

from app import db


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the AI Note Taker database.")
    parser.add_argument("command", choices=["init-db", "list"])
    args = parser.parse_args()

    if args.command == "init-db":
        db.apply_schema()
        print("Schema applied.")
        return

    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT s3_prefix, course_key, title FROM courses ORDER BY created_at DESC"
        ).fetchall()
    for row in rows:
        print(f"{row['s3_prefix']}  {row['course_key'] or '-'}  {row['title']}")


if __name__ == "__main__":
    main()
