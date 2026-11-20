"""Render a finished run's note again, without the model: for changes to our page (the front
matter, theme, CSS, header and footer), not to what the agent wrote. `render_and_publish` is
also how a teacher's edit is rendered (runs.execute_edit).

The CLI takes the body and assets the run published, renders them with the current templates and
replaces the run's published files. The note keeps its agent sign-off, read from the old page.

    docker compose exec worker python -m app.note_taker.lecture_notes.rerender <run-id>
"""

import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app import db, storage
from app.note_taker.lecture_notes.build import CHROME_TEXT, Runner, default_runner
from app.note_taker.lecture_notes.readings import load_lecture
from app.note_taker.lecture_notes.runs import publish
from app.note_taker.lecture_notes.tools import render


def split_front_matter(qmd: str) -> tuple[str, str]:
    """The published `index.qmd` is our front matter, a blank line and the agent's body."""
    match = re.match(r"---\n(.*?)\n---\n\n?", qmd, re.S)
    if match is None:
        raise ValueError("index.qmd has no front matter")
    return match[1], qmd[match.end() :]


def old_sign_off(page: str) -> str | None:
    """The agent's sign-off on the old page; None for none or a default line."""
    match = re.search(r'class="kse-footer-sign-off">(.*?)</p>', page, re.S)
    if match is None:
        return None
    line = html.unescape(match[1]).strip()
    defaults = {text["sign_off"] for text in CHROME_TEXT.values()}
    return None if line in defaults else line


def front_references(front: str) -> list[dict] | None:
    """The CSL references a published front matter carries (`references: [...]`, one line)."""
    match = re.search(r"^references: (.*)$", front, re.M)
    return None if match is None else json.loads(match[1])


@dataclass
class Published:
    """What a succeeded run published, read back from S3."""

    front: str
    body: str
    assets: dict[str, bytes]
    sign_off: str | None


def read_published(prefix: str, files: list[str], read: Any = None) -> Published:
    read = read or (lambda key: storage.get_object(key)["Body"].read())
    front, body = split_front_matter(read(prefix + "index.qmd").decode("utf-8"))
    assets = {name: read(prefix + name) for name in files if name.startswith("assets/")}
    sign_off = old_sign_off(read(prefix + "index.html").decode("utf-8", errors="replace"))
    return Published(front, body, assets, sign_off)


def render_and_publish(
    course: str,
    session_id: str,
    front: str,
    body: str,
    assets: dict[str, bytes],
    sign_off: str | None,
    prefix: str,
    *,
    runner: Runner | None = None,
    publisher: Any = publish,
) -> list[str]:
    """Render a body without the model and publish it under `prefix`; returns the files.

    `front` is the front matter of the version it comes from: its citations must still point at
    the lecture's readings. Raises ValueError with the validator's or Quarto's message."""
    from app.worker.config import get_worker_settings

    settings = get_worker_settings()
    bundle = load_lecture(
        settings.uploads_dir, course, session_id, settings.lecture_notes_max_chars
    )
    if front_references(front) != bundle.references():
        raise ValueError(
            "The lecture's readings changed since this version, so its citations would point at "
            "other readings. Write the notes again instead."
        )
    with TemporaryDirectory(prefix="lecture-notes-rerender-") as temporary:
        output = Path(temporary) / "build"
        result, message = render(bundle, body, assets, runner or default_runner(), output, sign_off)
        if result is None:
            raise ValueError(message)
        return publisher(output, prefix)


def rerender_run(
    run_id: UUID,
    *,
    runner: Runner | None = None,
    publisher: Any = publish,
    read: Any = None,
) -> list[str]:
    """Re-render and re-publish one succeeded run. Returns its new file list."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT r.id, r.course_id, r.session_id, r.status, r.files, c.course_key"
            " FROM lecture_note_runs r JOIN courses c ON c.id = r.course_id WHERE r.id = %s",
            (run_id,),
        ).fetchone()
    if row is None or row["status"] != "succeeded":
        raise ValueError(f"Run {run_id} is not a succeeded run")
    prefix = storage.lecture_notes_prefix(row["course_id"], row["session_id"], row["id"])
    old = read_published(prefix, row["files"], read)
    files = render_and_publish(
        row["course_key"],
        row["session_id"],
        old.front,
        old.body,
        old.assets,
        old.sign_off,
        prefix,
        runner=runner,
        publisher=publisher,
    )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lecture_note_runs SET files = %s WHERE id = %s", (Jsonb(files), run_id)
        )
    return files


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        published = rerender_run(UUID(argument))
        print(f"{argument}: re-rendered, {len(published)} files")
