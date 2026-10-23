"""Worker-owned revisions and durable, model-free rendering of immutable snapshots."""

import asyncio
import fcntl
import shutil
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, status

from app.note_assets import asset_resources
from app.notes import NotesRun, RenderFormat
from app.notes_artifacts import (
    artifact_path,
    atomic_json,
    manifest,
    new_job,
    read_job,
    revision_folder,
    revision_jobs,
    write_job,
)
from app.notes_revisions import (
    EditResult,
    InvalidEdit,
    RenderJob,
    RevisionConflict,
    RevisionNotFound,
    RevisionStore,
    RevisionView,
    TopicPatch,
    run_lock,
)
from app.worker.config import WorkerSettings
from app.worker.quarto import render_document
from app.worker.references import revision_context
from app.worker.render import to_quarto, topic_to_quarto


async def transact(change: Callable[[], RevisionView]) -> EditResult:
    try:
        view = await asyncio.to_thread(change)
    except RevisionConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except RevisionNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except InvalidEdit as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return EditResult(revision=view.info)


async def revise(directory: Path, topic: str, patch: TopicPatch) -> EditResult:
    result = await transact(lambda: RevisionStore(directory).commit_topic(topic, patch))
    if result.revision.revision != patch.base_revision:
        result.render = revision_jobs(directory, result.revision.revision)[0]
    return result


async def restore(directory: Path, revision: int, base_revision: int) -> EditResult:
    result = await transact(lambda: RevisionStore(directory).restore(revision, base_revision))
    if result.revision.revision != base_revision:
        result.render = revision_jobs(directory, result.revision.revision)[0]
    return result


def enqueue_render(directory: Path, revision: int, formats: list[RenderFormat]) -> RenderJob:
    if not formats:
        raise InvalidEdit("Choose at least one render format")
    store = RevisionStore(directory)
    metadata = directory / "run.json"
    if not metadata.is_file():
        raise RevisionNotFound("Notes run not found")
    with run_lock(directory):
        if NotesRun.model_validate_json(metadata.read_text()).status != "done":
            raise RevisionConflict("Only completed notes runs can be rendered")
        view = store.read(revision)
        # Freeze virtual baseline before rendering, so generation/resume cannot overwrite it.
        if revision == 0 and store._baseline() is None:
            store._publish(view)
        job = new_job(revision, formats)
        write_job(directory, job)
        return job


@asynccontextmanager
async def render_lock(directory: Path):
    """Nonblocking flock probes: waiting yields, and cancellation always closes the fd.

    No run lock is acquired while this lock is held. The descriptor owns the lock for
    the complete render+merge transaction, across awaits and across processes.
    """
    with (directory / ".render.lock").open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


async def render_revision(directory: Path, job_id: str, settings: WorkerSettings) -> RenderJob:
    job = read_job(directory, job_id)
    folder = revision_folder(directory, job.revision)
    async with render_lock(folder):
        job = read_job(directory, job_id)
        if job.status != "queued":
            return job
        job.status = "running"
        write_job(directory, job)
        try:
            document = RevisionStore(directory).read(job.revision).document
            if document.language is None:
                raise ValueError(
                    "Select Ukrainian or English in the editor before rendering these notes"
                )
            root = folder / "artifacts"
            output = root / job.id
            output.mkdir()  # Unique immutable output; never overwrite an earlier manifest's files.
            context = revision_context(settings.public_api_url, document, job.revision)
            ready = []

            async def one(section=None, note=None):
                prefix = f"topics/{quote(note.topic_id, safe='')}/" if note else ""
                destination = output / prefix
                destination.mkdir(parents=True, exist_ok=True)
                sources, resources = {}, {}
                for kind in job.formats:
                    try:
                        source = (
                            topic_to_quarto(
                                document, section, note, document.language, kind, context
                            )
                            if note
                            else to_quarto(document, document.language, kind, context)
                        )
                        resources.update(asset_resources(directory, document.assets, source))
                        path = destination / "sources" / kind / "notes.qmd"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(source)
                        sources[kind] = path
                    except Exception as error:
                        job.errors.append(
                            f"{note.topic_id if note else 'Full notes'} {kind}: {error}"
                        )
                results = await render_document(
                    sources,
                    destination,
                    job.revision,
                    settings.quarto_bin,
                    resources,
                    concurrency=settings.quarto_concurrency,
                )
                for artifact in results:
                    if artifact.status == "ready":
                        artifact.path = f"{job.id}/{prefix}{artifact.path}"
                        artifact.topic_id = note.topic_id if note else None
                        ready.append(artifact)
                    else:
                        job.errors.append(
                            f"{note.topic_id if note else 'Full notes'} {artifact.format}: "
                            f"{artifact.error}"
                        )

            outcomes = await asyncio.gather(
                one(),
                *(
                    one(section, note)
                    for section in document.sections
                    for note in section.topics
                    if note.status in ("verified", "unresolved")
                ),
                return_exceptions=True,
            )
            job.errors.extend(str(error) for error in outcomes if isinstance(error, Exception))
            previous = manifest(directory, job.revision)
            if job.revision == 0 and not (root / "manifest.json").exists():
                # Legacy manifest paths belong to the run root. Copy into this unique
                # output before publishing a revision-root manifest, including keys
                # not requested by this job. Generation files remain untouched.
                retained = []
                for artifact in previous:
                    if artifact.status != "ready":
                        continue
                    try:
                        source = artifact_path(directory, 0, artifact.format, artifact.topic_id)
                        target = output / "previous" / artifact.path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
                        retained.append(
                            artifact.model_copy(
                                update={"path": target.relative_to(root).as_posix()}
                            )
                        )
                    except (OSError, RevisionNotFound):
                        continue
                previous = retained
            merged = {(a.topic_id, a.format): a for a in previous if a.status == "ready"}
            merged.update({(a.topic_id, a.format): a for a in ready})
            atomic_json(root / "manifest.json", [a.model_dump() for a in merged.values()])
            job.status = "failed" if job.errors else "done"
        except asyncio.CancelledError:
            job.status = "failed"
            job.errors.append("Rendering interrupted; retry this revision")
            write_job(directory, job)
            raise
        except Exception as error:
            job.status = "failed"
            job.errors.append(str(error))
        write_job(directory, job)
        return job


def fail_interrupted_renders(uploads: Path) -> None:
    """Only committed revisions; malformed runs/records cannot stop global recovery."""
    for directory in uploads.glob("*/notes/*"):
        if not directory.is_dir() or not (directory / "notes.json").is_file():
            continue
        try:
            history = RevisionStore(directory).list()
        except Exception as error:  # Corrupt HEAD/snapshot: leave it, recover the others.
            print(f"Render recovery skipped {directory}: {error!r}")
            continue
        for info in history:
            for job in revision_jobs(directory, info.revision):
                if job.status not in ("queued", "running"):
                    continue
                job.status = "failed"
                job.errors.append(
                    "Worker restarted before rendering completed; retry this revision"
                )
                try:
                    write_job(directory, job)
                except OSError as error:
                    print(f"Render recovery could not update job {job.id}: {error!r}")
