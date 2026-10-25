"""Read committed revision jobs and artifacts; all paths remain under their owner root."""

import json
import os
import re
from pathlib import Path
from time import time_ns
from urllib.parse import unquote
from uuid import uuid4

from pydantic import TypeAdapter

from app.notes import RenderedArtifact, RenderFormat
from app.notes_revisions import RenderJob, RevisionNotFound, RevisionStore

JOBS = re.compile(r"[0-9]+-[0-9a-f]{32}\Z")
BOOK_SUFFIXES = {
    ".html",
    ".css",
    ".js",
    ".json",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
}


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid4().hex}")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def new_job(revision: int, formats: list[RenderFormat]) -> RenderJob:
    return RenderJob(
        id=f"{time_ns()}-{uuid4().hex}",
        revision=revision,
        status="queued",
        formats=list(dict.fromkeys(formats)),
        errors=[],
    )


def revision_folder(directory: Path, revision: int) -> Path:
    return directory / "revisions" / f"{revision:06d}"


def write_job(directory: Path, job: RenderJob) -> None:
    atomic_json(
        revision_folder(directory, job.revision) / "jobs" / f"{job.id}.json", job.model_dump()
    )


def read_job(directory: Path, job_id: str) -> RenderJob:
    if not JOBS.fullmatch(job_id):
        raise RevisionNotFound("Render job not found")
    for info in reversed(RevisionStore(directory).list()):
        path = revision_folder(directory, info.revision) / "jobs" / f"{job_id}.json"
        if path.is_file():
            job = RenderJob.model_validate_json(path.read_text())
            if job.id == job_id and job.revision == info.revision:
                return job
    raise RevisionNotFound("Render job not found")


def revision_jobs(directory: Path, revision: int) -> list[RenderJob]:
    jobs = []
    for path in (revision_folder(directory, revision) / "jobs").glob("*.json"):
        try:
            job = RenderJob.model_validate_json(path.read_text())
            if job.revision == revision and path.stem == job.id and JOBS.fullmatch(job.id):
                jobs.append(job)
        except (OSError, ValueError):
            continue
    return sorted(jobs, key=lambda j: j.id)


def manifest(directory: Path, revision: int) -> list[RenderedArtifact]:
    root = revision_folder(directory, revision) / "artifacts"
    path = root / "manifest.json"
    if not path.is_file() and revision == 0:
        root, path = directory, directory / "artifacts.json"
    if not path.is_file():
        return []
    try:
        artifacts = TypeAdapter(list[RenderedArtifact]).validate_json(path.read_text())
    except (OSError, ValueError):
        return []  # An unreadable manifest serves nothing; the next render replaces it.
    return [
        a
        for a in artifacts
        if a.revision == revision and (root / a.path).resolve().is_relative_to(root.resolve())
    ]


def selected_artifacts(directory: Path, through: int | None = None) -> list[RenderedArtifact]:
    selected = {}
    for info in RevisionStore(directory).list():
        if through is not None and info.revision > through:
            continue
        for artifact in manifest(directory, info.revision):
            key = (artifact.topic_id, artifact.format)
            if artifact.status == "ready" or key not in selected:
                selected[key] = artifact
    return list(selected.values())


def artifact_path(directory: Path, revision: int, kind: str, topic: str | None) -> Path:
    RevisionStore(directory).read(revision)  # Explicit URLs never expose orphans or fallback.
    for artifact in manifest(directory, revision):
        if (artifact.format, artifact.topic_id, artifact.status) == (kind, topic, "ready"):
            root = revision_folder(directory, revision) / "artifacts"
            if revision == 0 and not (root / "manifest.json").is_file():
                root = directory
            path = (root / artifact.path).resolve()
            if path.is_relative_to(root.resolve()) and path.is_file():
                return path
    # Old runs predate manifests. Only their known revision-zero files are aliases.
    if revision == 0:
        root = directory.resolve()
        path = root / (f"topics/{topic}/note.{kind}" if topic else f"notes.{kind}")
        if (
            kind in ("html", "pdf", "docx")
            and path.resolve().is_relative_to(root)
            and path.is_file()
        ):
            return path
    raise RevisionNotFound(f"No {kind} for revision {revision}")


def book_asset_path(root: Path, asset_path: str) -> Path:
    """Only files explicitly published in a ready book, never its source tree."""
    decoded = unquote(asset_path)
    if decoded != asset_path or "\\" in decoded or decoded.startswith("/"):
        raise ValueError("Invalid book asset path")
    name = decoded.rstrip("/") or "index.html"
    parts = Path(name).parts
    if not parts or any(part in (".", "..") or part.startswith((".", "_")) for part in parts):
        raise ValueError("Invalid book asset path")
    if name == "publication.json" or Path(name).suffix.lower() not in BOOK_SUFFIXES:
        raise ValueError("Publication manifest is private")
    if (root / "publication.json").is_symlink():
        raise ValueError("Book publication is unavailable")
    try:
        published = json.loads((root / "publication.json").read_text())
    except (OSError, ValueError) as error:
        raise ValueError("Book publication is unavailable") from error
    if not isinstance(published, list) or name not in published:
        raise ValueError("Book asset is not published")
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Book asset leaves its published root")
    return path


def ready_book_root(directory: Path, revision: int) -> Path:
    RevisionStore(directory).read(revision)
    root = revision_folder(directory, revision) / "artifacts"
    for artifact in manifest(directory, revision):
        if (artifact.topic_id, artifact.format, artifact.status) == (None, "book", "ready"):
            path = (root / artifact.path).resolve()
            if path.is_relative_to(root.resolve()) and path.is_dir():
                return path
    raise RevisionNotFound("Book not published for this revision")
