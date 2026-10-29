"""Notes generation: plan globally, synthesize each topic across sources, verify, compose."""

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from app.note_assets import asset_resources
from app.notes import (
    CourseNotation,
    CoursePlan,
    Inputs,
    NotesDocument,
    NotesRun,
    NotesSection,
    RenderedArtifact,
    TopicNote,
    append_notation,
    load_course_notation,
    notation_file,
    now,
    run_dir,
    topic_filename,
    validate_topic_ids,
)
from app.notes_revisions import RevisionConflict, run_lock
from app.plan import Plan, materials_fingerprint, session_fingerprint
from app.storage import sha256
from app.syllabus import Transcript
from app.worker.artifacts import RunStore
from app.worker.composition import collect, harmonize
from app.worker.config import WorkerSettings
from app.worker.models import NotesModels
from app.worker.openrouter import Opener, OpenRouterClient
from app.worker.planning import plan_course
from app.worker.quarto import QuartoError, render_document
from app.worker.references import revision_context
from app.worker.render import to_quarto, topic_to_quarto
from app.worker.sources import Retriever, build_inputs, session_materials
from app.worker.topics import generate_topic

ACTIVE: set[str] = set()
COMPLETED_RUN = (
    "This notes run is complete, and resuming it would overwrite its published notes. "
    "Start a new run to regenerate them, or rerender this run to rebuild its outputs."
)


COURSE_NOTATION = "course-notation.json"
STOPPED = "Stopped; resume to continue"
OTHER_LECTURE = "This run belongs to another lecture; resume it from that lecture."


RESUME_PROVENANCE = (
    "This run's input/context provenance is changed or unknown. "
    "Start a new run; the existing run and its cached files have been preserved."
)


class GenerationProvenance(BaseModel):
    version: int = 1
    fingerprint: str
    inputs_sha256: str
    plan: Plan
    transcript: Transcript


def input_fingerprint(course_dir: Path, plan: Plan, transcript: Transcript) -> str:
    """Include ordering, context, language and all bytes used by extraction, not source IDs."""
    uploads_dir = course_dir.parent
    files = {}
    for material, _ in session_materials(plan, transcript):
        path = uploads_dir / material.file
        files[material.file] = sha256(path) if path.is_file() else None
    value = {"plan": plan.model_dump(), "transcript": transcript.model_dump(), "files": files}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def inputs_digest(inputs: Inputs) -> str:
    return hashlib.sha256(inputs.model_dump_json().encode()).hexdigest()


def fail_interrupted(uploads_dir: Path) -> list[str]:
    """Runs left queued or running by a previous worker process can never finish: mark them
    failed so they can be resumed."""
    interrupted = []
    for file in uploads_dir.glob("*/notes/*/run.json"):
        try:
            run = NotesRun.model_validate_json(file.read_text())
        except (OSError, ValueError):
            continue
        if run.status in ("queued", "running"):
            store = RunStore(file.parent, run)
            run.status = "failed"
            run.error = "Interrupted by a worker restart; resume the run to continue"
            store.log("failed", run.error)
            interrupted.append(f"{run.course}/{run.id}")
    return interrupted


def open_run(
    course_dir: Path,
    course: str,
    run_id: str,
    models: NotesModels,
    plan: Plan | None = None,
    transcript: Transcript | None = None,
    session_id: str | None = None,
) -> RunStore:
    """The store of a new run, or of an earlier unpublished run being resumed.

    Admission takes the run lock that edits use: a completed run's notes are published
    (and may be edited), so resuming it would silently replace them. A lecture run
    (`session_id`) gets a plan and transcript already scoped to its session.
    """
    directory = run_dir(course_dir, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    with run_lock(directory):
        previous = directory / "run.json"
        if previous.is_file():
            run = NotesRun.model_validate_json(previous.read_text())
            if run.status == "done" or (directory / "revisions").exists():
                raise RevisionConflict(COMPLETED_RUN)
            if run.session_id != session_id:
                raise RevisionConflict(OTHER_LECTURE)
            # Refuse before changing even run.json: positional source IDs only have
            # meaning under the exact frozen input inventory and original context.
            store = RunStore(directory, run)
            try:
                provenance = store.read("provenance.json", GenerationProvenance)
                inputs = store.read("inputs.json", Inputs)
                if (
                    plan is None
                    or transcript is None
                    or provenance is None
                    or inputs is None
                    or provenance.version != 1
                    or provenance.fingerprint != input_fingerprint(course_dir, plan, transcript)
                    or provenance.inputs_sha256 != inputs_digest(inputs)
                ):
                    raise ValueError(RESUME_PROVENANCE)
                cached = store.read("plan.json", CoursePlan)
                if cached is not None:
                    validate_topic_ids([topic.id for _, topic in cached.topics()])
            except (OSError, ValueError) as error:
                raise RevisionConflict(RESUME_PROVENANCE) from error
            run.status, run.error, run.warnings = "queued", None, []
        else:
            stamp = now()
            run = NotesRun(
                id=run_id,
                course=course,
                status="queued",
                stage="queued",
                created_at=stamp,
                updated_at=stamp,
                models=models.summary(),
                materials=(
                    None
                    if plan is None
                    else session_fingerprint(plan, session_id)
                    if session_id
                    else materials_fingerprint(plan)
                ),
                session_id=session_id,
                session_label=plan.sessions[0].label if session_id and plan else None,
            )
        store = RunStore(directory, run)
        if not previous.is_file():
            if plan is None or transcript is None:
                raise ValueError("Generation requires the source plan and syllabus context")
            fingerprint = input_fingerprint(course_dir, plan, transcript)
            inputs = build_inputs(course_dir.parent, course_dir, plan, transcript)
            if input_fingerprint(course_dir, plan, transcript) != fingerprint:
                raise RevisionConflict(RESUME_PROVENANCE)
            store.write("inputs.json", inputs)
            if session_id:
                # Frozen with the inputs, so resuming plans against the same sheet.
                store.write(COURSE_NOTATION, load_course_notation(course_dir))
            store.write(
                "provenance.json",
                GenerationProvenance(
                    fingerprint=fingerprint,
                    inputs_sha256=inputs_digest(inputs),
                    plan=plan,
                    transcript=transcript,
                ),
            )
        store.save()
    return store


def seed_retry(course_dir: Path, source: NotesRun, run_id: str, models: NotesModels) -> None:
    """A new run holding a finished lecture run's frozen inputs, plan and the sections that
    did not fail, waiting to be resumed: resuming writes only the failed sections.

    The finished run is only read. Its edits and approvals stay with it.
    """
    old = run_dir(course_dir, source.id)
    new = run_dir(course_dir, run_id)
    new.mkdir(parents=True)
    store = RunStore(old, source)
    for name in ("inputs.json", "provenance.json", "plan.json", COURSE_NOTATION):
        if store.path(name).is_file():
            shutil.copyfile(store.path(name), new / name)
    plan = store.read("plan.json", CoursePlan)
    for _, topic in plan.topics() if plan else []:
        name = f"topics/{topic_filename(topic.id)}/note.json"
        note = store.read(name, TopicNote)
        if note is not None and note.status != "failed":
            (new / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(store.path(name), new / name)
    stamp = now()
    run = NotesRun(
        id=run_id,
        course=source.course,
        status="failed",
        stage="queued",
        created_at=stamp,
        updated_at=stamp,
        models=models.summary(),
        error="Waiting to write the failed sections again",
        materials=source.materials,
        session_id=source.session_id,
        session_label=source.session_label,
        retried_from=source.id,
    )
    RunStore(new, run).save()


async def topic_notes(
    client: OpenRouterClient,
    models: NotesModels,
    store: RunStore,
    plan: CoursePlan,
    inputs: Inputs,
    language: str | None,
    settings: WorkerSettings,
) -> dict[str, TopicNote]:
    """One job per topic, at most `notes_concurrency` at a time; finished topics are reused."""
    retriever = Retriever(inputs.chunks)
    gate = asyncio.Semaphore(settings.notes_concurrency)
    notes: dict[str, TopicNote] = {}
    topics = plan.topics()
    validate_topic_ids([topic.id for _, topic in topics])
    store.run.topics_total = len(topics)

    async def job(section, topic) -> None:
        name = f"topics/{topic_filename(topic.id)}/note.json"
        done = store.read(name, TopicNote)
        if done is None or done.status == "failed":
            async with gate:
                try:
                    done = await generate_topic(
                        client,
                        models,
                        store,
                        plan,
                        section,
                        topic,
                        inputs,
                        retriever,
                        language,
                        settings.notes_revision_rounds,
                    )
                    store.write(name, done)
                except Exception as error:
                    print(f"Topic {topic.id} failed: {error!r}")
                    done = TopicNote(
                        topic_id=topic.id,
                        objectives=list(topic.objectives),
                        title=topic.title,
                        status="failed",
                        blocks=[],
                        evidence=[],
                        rounds=0,
                        verifier=None,
                        open_issues=[],
                        error=str(getattr(error, "detail", None) or error),
                    )
                    store.write(name, done)
        notes[topic.id] = done
        store.run.topics_done += 1
        store.log("topics", f"{topic.id} {topic.title}: {done.status}")

    store.run.topics_done = 0
    await asyncio.gather(*(job(section, topic) for section, topic in topics))
    return notes


async def run_notes(
    opener: Opener,
    settings: WorkerSettings,
    store: RunStore,
    plan: Plan,
    transcript: Transcript,
) -> None:
    course = store.run.course
    models = NotesModels.from_settings(settings)
    store.run.status = "running"
    store.run.models = models.summary()
    try:
        async with opener() as client:
            store.log("inputs", "Collecting mapped chunks")
            provenance = store.read("provenance.json", GenerationProvenance)
            inputs = store.read("inputs.json", Inputs)
            if (
                provenance is None
                or inputs is None
                or inputs_digest(inputs) != provenance.inputs_sha256
            ):
                raise ValueError(RESUME_PROVENANCE)
            # Use the context saved alongside these exact source IDs, even if a
            # caller's in-memory request was modified after admission.
            transcript = provenance.transcript
            for skipped in inputs.skipped:
                store.warn(skipped)
            if not inputs.chunks:
                raise ValueError("No session material has extractable text")
            store.log("inputs", f"{len(inputs.sources)} sources, {len(inputs.chunks)} chunks")

            sheet = (
                store.read(COURSE_NOTATION, CourseNotation) or CourseNotation()
                if store.run.session_id
                else None
            )
            course_plan = store.read("plan.json", CoursePlan)
            if course_plan is None:
                store.log("planning", "Drafting the course plan")
                course_plan = await plan_course(
                    client,
                    models,
                    store,
                    transcript,
                    inputs,
                    settings.notes_plan_rounds,
                    sheet,
                )
            validate_topic_ids([topic.id for _, topic in course_plan.topics()])
            store.log("planning", f"Plan ready: {len(course_plan.topics())} topics")

            notes = await topic_notes(
                client, models, store, course_plan, inputs, transcript.language, settings
            )
            failed = [n.topic_id for n in notes.values() if n.status == "failed"]
            if failed:
                store.warn(f"Topics failed and can be retried by resuming: {failed}")

            store.log("composition", "Harmonizing notation and cross-references")
            sections = collect(course_plan, notes)
            edits = await harmonize(client, models, course_plan, sections)
            store.log("composition", f"Applied {edits} consistency edits")

        document = NotesDocument(
            schema_version=2,
            language=transcript.language if transcript.language in ("uk", "en") else None,
            course=course,
            run=store.run.id,
            title=course_plan.title,
            created_at=now(),
            sections=sections,
            sources=inputs.sources,
            notation=course_plan.notation,
            terminology=course_plan.terminology,
            models=store.run.models,
        )
        store.write("notes.json", document)
        await render_notes_outputs(document, store, settings)
        if store.run.session_id:
            extend_course_notation(store, course_plan)
        store.run.status = "done"
        store.log("done", "Notes are ready")
    except Exception as error:
        print(f"Notes run {course}/{store.run.id} failed: {error!r}")
        store.run.status = "failed"
        store.run.error = str(getattr(error, "detail", None) or error)
        store.log("failed", store.run.error)
    except asyncio.CancelledError:
        # Stop: finished topics stay on disk and are reused when the run resumes. Nothing
        # half-written is published: Quarto is killed and its outputs never replace files,
        # and a run that is not done never shows its artifact manifest.
        mark_stopped(store)


def mark_stopped(store: RunStore) -> None:
    print(f"Notes run {store.run.course}/{store.run.id} stopped")
    store.run.status = "failed"
    store.run.error = STOPPED
    store.log("failed", STOPPED)


def extend_course_notation(store: RunStore, plan: CoursePlan) -> None:
    """Append a finished lecture's new symbols and terms to the course sheet.

    Only the worker writes the sheet, and it runs one job per course at a time.
    """
    course_dir = store.directory.parents[1]
    try:
        sheet = append_notation(load_course_notation(course_dir), plan)
        target = notation_file(course_dir)
        partial = target.with_name(f".{target.name}.partial")
        partial.write_text(sheet.model_dump_json(indent=2))
        partial.replace(target)
    except OSError as error:
        store.warn(f"The course notation sheet was not updated: {error}")


async def render_notes_outputs(
    document: NotesDocument, store: RunStore, settings: WorkerSettings
) -> list[RenderedArtifact]:
    """Save format sources and a manifest even when individual renders fail.

    The run directory is the artifacts root. Revision zero keeps the established
    notes.qmd and topics/<id>/note.pdf download locations; the full document is
    rendered as HTML only (older runs may still hold a notes.pdf).
    """
    artifacts: list[RenderedArtifact] = []
    store.log("rendering", "Rendering HTML and PDF with Quarto")
    store.write("artifacts.json", "[]")

    async def one(section: NotesSection | None = None, note: TopicNote | None = None):
        prefix = f"topics/{topic_filename(note.topic_id)}/" if note else ""
        stem = "note" if note else "notes"
        prepared = {}
        resources = {}
        # Generation output is revision 0; links must not follow newer revisions.
        context = revision_context(settings.public_api_url, document, 0)
        results = []
        for target in ("html", "pdf"):
            try:
                source = (
                    topic_to_quarto(document, section, note, document.language, target, context)
                    if note
                    else to_quarto(document, document.language, target, context)
                )
                resources.update(asset_resources(store.directory, document.assets, source))
                name = (
                    f"{prefix}{stem}.qmd"
                    if target == "pdf"
                    else (f"{prefix}sources/html/{stem}.qmd")
                )
                prepared[target] = store.write(name, source)
            except (QuartoError, OSError, ValueError) as error:
                results.append(
                    RenderedArtifact(
                        format=target,
                        path=f"{stem}.{target}",
                        revision=0,
                        status="failed",
                        error=str(error),
                    )
                )
        if note is None:
            # The whole course is read as HTML; only topics get a PDF. notes.qmd is still
            # written: it is the run's downloadable Quarto source.
            prepared.pop("pdf", None)
        results += await render_document(
            prepared,
            store.path(prefix),
            0,
            settings.quarto_bin,
            resources=resources,
            concurrency=settings.quarto_concurrency,
        )
        for artifact in results:
            artifact.path = prefix + artifact.path
            artifact.topic_id = note.topic_id if note else None
            if artifact.status == "failed":
                label = artifact.format.upper() + (f" of {note.topic_id}" if note else "")
                store.warn(f"{label} not rendered: {artifact.error}")
        artifacts.extend(results)
        store.write("artifacts.json", json.dumps([a.model_dump() for a in artifacts], indent=2))

    await one()
    await asyncio.gather(
        *(
            one(section, note)
            for section in document.sections
            for note in section.topics
            if note.status in ("verified", "unresolved")
        )
    )
    return artifacts
