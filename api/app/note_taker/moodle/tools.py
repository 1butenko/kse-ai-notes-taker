"""Tools of the `moodle` subagent.

`course_id` and `moodle_course_id` are bound here by closure, never passed by the LLM, so
everything the agent can touch is scoped to one course. Files stream Moodle -> S3 and never enter
agent state; only S3 keys come back. With a `project`, the chosen files also go into the app's
course (syllabus or readings), and the subagent can read the syllabus into lectures and attach
readings to them. Every tool reports what it does to `progress`, which the course page shows.
"""

import io
import json
from collections.abc import Callable, Iterator
from typing import BinaryIO, Literal
from uuid import UUID, uuid4

import httpx
from deepagents.backends import StateBackend
from langchain.tools import tool
from pydantic import BaseModel, Field

from app import storage
from app.links import MAX_BYTES, html_to_markdown, is_video
from app.note_taker.moodle.catalog import (
    SKIP_MODNAMES,
    Catalog,
    CatalogFile,
    CatalogItem,
    normalize_contents,
    outline,
)
from app.note_taker.moodle.client import MoodleClient
from app.note_taker.moodle.store import MaterialRecord, MaterialsStore
from app.note_taker.progress import Progress
from app.note_taker.project import Project, ProjectError

CATALOG_PATH = "/moodle/catalog.json"
MANIFEST_PATH = "/materials/manifest.json"
LECTURES_PATH = "/course/lectures.json"

Upload = Callable[[str, BinaryIO, str | None], None]
# Modules saved as Markdown readings through the app, not downloaded as files.
WEB_PAGE_MODNAMES = frozenset({"url", "page", "book"})
PREVIEW_HEADERS = {"user-agent": "kse-ai-notes-taker (course materials import)"}


def preview_link(url: str, max_chars: int, http: httpx.Client | None = None) -> str:
    """What a link holds, for judging it: a video, a PDF, or the page's start as Markdown."""
    if is_video(url):
        return "A video: it cannot be saved as a reading."
    if not url.startswith(("http://", "https://")):
        return "Not a web page."
    client = http or httpx.Client(timeout=20, follow_redirects=True, headers=PREVIEW_HEADERS)
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            kind = response.headers.get("content-type", "")
            if "pdf" in kind:
                return "A PDF document."
            if "html" not in kind and "text/plain" not in kind:
                return f"Not a readable page ({kind or 'unknown type'})."
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    return "A page over 20 MB: too large to save."
            final_url = str(response.url)
    except httpx.HTTPError as error:
        return f"Could not open it: {error}"
    finally:
        if http is None:
            client.close()
    text = body.decode(errors="replace")
    text = html_to_markdown(text, final_url) if "html" in kind else text
    return text[:max_chars] or "(no text)"


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


class FetchItem(BaseModel):
    module_id: int = Field(description="Moodle module id from the course outline, the [number].")
    filename: str | None = Field(
        default=None, description="Fetch only this file of the module. Omit for all its files."
    )
    category: Literal["syllabus", "reading"] = Field(
        default="reading",
        description="`syllabus` for the course syllabus (exactly one file), else `reading`.",
    )
    reason: str = Field(description="One line: why this is relevant for study notes.")


class Attachment(BaseModel):
    session_id: str = Field(description="Lecture id from prepare_lectures.")
    path: str = Field(description="Reading file path from prepare_lectures.")


class _IterReader(io.RawIOBase):
    """Adapts a byte iterator to a file object, counting the bytes that pass through."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._buffer = b""
        self.size = 0

    def readable(self) -> bool:
        return True

    def readinto(self, target) -> int:  # type: ignore[no-untyped-def]
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        count = min(len(target), len(self._buffer))
        target[:count] = self._buffer[:count]
        self._buffer = self._buffer[count:]
        self.size += count
        return count


def lectures_outline(plan: dict) -> tuple[dict, str]:
    """The plan's lectures and reading files, as JSON for the state and as a short outline."""
    attached = {f["path"] for s in plan["sessions"] for f in s["files"]}
    lectures = [
        {
            "session_id": s["id"],
            "label": s["session"]["label"],
            "topic": s["session"]["topic"],
            "readings": [f["path"] for f in s["files"]],
        }
        for s in plan["sessions"]
    ]
    unattached = [f["path"] for f in plan["unassigned"] if f["path"] not in attached]
    data = {"lectures": lectures, "unattached_readings": unattached}
    lines = [
        f"- [{lec['session_id']}] {lec['label']}: {lec['topic']}"
        f" ({plural(len(lec['readings']), 'reading')})"
        for lec in lectures
    ]
    lines += ["", "Readings not attached to any lecture:"]
    lines += [f"- {path}" for path in unattached] or ["- none"]
    return data, "\n".join(lines)


def make_moodle_tools(
    client: MoodleClient,
    backend: StateBackend,
    store: MaterialsStore,
    course_id: str,
    moodle_course_id: int,
    upload: Upload = storage.upload_stream,
    *,
    project: Project | None = None,
    progress: Progress | None = None,
):
    course_uuid = UUID(course_id)
    progress = progress or Progress()
    state: dict[str, Catalog | None] = {"catalog": None}
    manifest: dict[str, list[dict]] = {"fetched": [], "skipped": [], "failed": [], "saved": []}

    def load_catalog() -> Catalog:
        if state["catalog"] is None:
            sections = client.get_course_contents(moodle_course_id)
            state["catalog"] = normalize_contents(sections)
        return state["catalog"]

    def write_json(path: str, data: object) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        backend.upload_files([(path, body)])

    @tool(parse_docstring=True)
    def list_course_contents() -> str:
        """List everything in the course: sections, activities and their files.

        The full catalog is saved to /moodle/catalog.json. Call this first.

        Returns:
            An outline, one line per module: [module_id] type: name | files.
        """
        with progress.action("Reading the course outline in Moodle") as action:
            state["catalog"] = None
            catalog = load_catalog()
            write_json(CATALOG_PATH, catalog.model_dump())
            store.save_topics(course_uuid, catalog.sections)
            action.detail = (
                f"{plural(len(catalog.items), 'activity', 'activities')} in "
                f"{plural(len(catalog.sections), 'section')}"
            )
        return f"{len(catalog.items)} modules, full catalog in {CATALOG_PATH}\n\n{outline(catalog)}"

    @tool(parse_docstring=True)
    def preview_module(module_id: int, max_chars: int = 2000) -> str:
        """Read a module's text to judge whether it is relevant, without downloading files.

        Gives page and book modules as Markdown, a url module's target and the start of the page
        it points to, and metadata only for file modules.

        Args:
            module_id: Moodle module id from the course outline.
            max_chars: Maximum characters of text to return.

        Returns:
            The module's text or metadata.
        """
        catalog = load_catalog()
        item = catalog.find(module_id)
        if item is None:
            return f"No module {module_id} in this course. Call list_course_contents."
        with progress.action(f"Looking at “{item.name}”"):
            header = f"{item.modname}: {item.name} (section {item.section}: {item.section_name})"
            if item.modname == "url":
                return f"{header}\nLink: {item.url}\n\n{preview_link(item.url, max_chars)}"
            if item.modname in {"page", "book"}:
                html_files = [
                    f for f in item.files if f.filename.lower().endswith((".html", ".htm"))
                ]
                text = "\n\n".join(
                    html_to_markdown(client.get_page_html(f.fileurl), f.fileurl) for f in html_files
                )
                return f"{header}\n\n{text[:max_chars]}" if text else f"{header}\n(no text)"
            if item.modname == "label":
                return f"{header}\n\n{item.description[:max_chars]}"
            files = "\n".join(
                f"- {f.filename} | {f.mimetype or '?'} | {f.filesize} bytes" for f in item.files
            )
            return f"{header}\n{files or '(no files)'}"

    def select_files(item: CatalogItem, filename: str | None) -> list[CatalogFile]:
        if filename is None:
            return item.files
        # The outline reads "name | file": a name copied with the file still means that file.
        names = {filename, filename.rsplit(" | ", 1)[-1].strip()}
        return [f for f in item.files if f.filename in names]

    def fetch_one(item: CatalogItem, file: CatalogFile, reason: str) -> dict:
        entry = {
            "module_id": item.module_id,
            "name": file.filename,
            "source_url": file.fileurl,
            "reason": reason,
        }
        if store.exists(course_uuid, file.fileurl, file.timemodified):
            return {"status": "skipped", **entry, "why": "already fetched, unchanged"}
        file_id = uuid4()
        key = storage.material_key(course_uuid, file_id, file.filename)
        reader = _IterReader(client.iter_download(file.fileurl))
        upload(key, io.BufferedReader(reader), file.mimetype or None)
        store.add(
            MaterialRecord(
                id=file_id,
                course_id=course_uuid,
                moodle_module_id=item.module_id,
                name=file.filename,
                mimetype=file.mimetype,
                size=reader.size,
                s3_key=key,
                source_url=file.fileurl,
                moodle_timemodified=file.timemodified,
                reason=reason,
                section=item.section,
                section_name=item.section_name,
            )
        )
        return {"status": "fetched", **entry, "s3_key": key, "size": reader.size}

    def save_to_course(to_course: dict[str, list[tuple[str, str]]], links: list[CatalogItem]):
        """Put the chosen files and link pages into the app's course."""
        if project is None:
            return
        for category, files in to_course.items():
            if not files:
                continue
            with progress.action(
                f"Adding {plural(len(files), category + ' file')} to the course"
            ) as action:
                try:
                    saved = project.save_files(category, files)  # type: ignore[arg-type]
                except ProjectError as error:
                    action.status, action.detail = "failed", str(error)
                    manifest["failed"].append({"name": f"{category} files", "error": str(error)})
                    continue
                manifest["saved"] += [s["path"] for s in saved]
                action.detail = ", ".join(s["path"].rsplit("/", 1)[-1] for s in saved)
        for item in links:
            with progress.action(f"Saving the web page “{item.name}”") as action:
                try:
                    saved = project.save_link(item.module_id)
                except ProjectError as error:
                    action.status, action.detail = "failed", str(error)
                    manifest["failed"].append(
                        {"module_id": item.module_id, "name": item.name, "error": str(error)}
                    )
                    continue
                manifest["saved"] += [s["path"] for s in saved]
                action.detail = ", ".join(s["path"].rsplit("/", 1)[-1] for s in saved)

    @tool(parse_docstring=True)
    def fetch_materials(items: list[FetchItem]) -> str:
        """Download the chosen course files from Moodle to storage and add them to the course.

        Only modules from the course catalog can be fetched. Files are stored and added to the
        course as its syllabus or readings. `url`, `page` and `book` modules are saved as
        Markdown readings of their web pages (videos cannot be). A file that is already stored
        and unchanged is not downloaded again. The results are saved to
        /materials/manifest.json.

        Args:
            items: The modules (and optionally files) to fetch, each with a category and a
                one-line reason.

        Returns:
            Counts and one line per fetched, skipped and failed file.
        """
        catalog = load_catalog()
        to_course: dict[str, list[tuple[str, str]]] = {"syllabus": [], "reading": []}
        links: list[CatalogItem] = []
        with progress.action(f"Downloading {plural(len(items), 'material')} from Moodle") as action:
            for fetch in items:
                item = catalog.find(fetch.module_id)
                if item is None:
                    manifest["failed"].append(
                        {"module_id": fetch.module_id, "error": "not in the course catalog"}
                    )
                    continue
                if item.modname in SKIP_MODNAMES:
                    manifest["skipped"].append(
                        {
                            "module_id": item.module_id,
                            "name": item.name,
                            "reason": fetch.reason,
                            "why": f"{item.modname} modules hold no study material",
                        }
                    )
                    continue
                if item.modname in WEB_PAGE_MODNAMES:
                    links.append(item)
                    continue
                files = select_files(item, fetch.filename)
                if not files:
                    manifest["failed"].append(
                        {
                            "module_id": item.module_id,
                            "name": fetch.filename or item.name,
                            "error": "no matching file in this module",
                        }
                    )
                    continue
                for file in files:
                    try:
                        result = fetch_one(item, file, fetch.reason)
                    except Exception as error:  # one bad file must not stop the rest
                        manifest["failed"].append(
                            {
                                "module_id": item.module_id,
                                "name": file.filename,
                                "reason": fetch.reason,
                                "error": str(error),
                            }
                        )
                        continue
                    status = result.pop("status")
                    manifest["fetched" if status == "fetched" else "skipped"].append(result)
                    # Unchanged files still go into the course: it may not have them yet.
                    to_course[fetch.category].append((file.fileurl, file.filename))
            action.detail = (
                f"{len(manifest['fetched'])} new, {len(manifest['skipped'])} skipped, "
                f"{len(manifest['failed'])} failed"
            )
        save_to_course(to_course, links)
        write_json(MANIFEST_PATH, manifest)
        lines = [
            f"fetched {len(manifest['fetched'])}, skipped {len(manifest['skipped'])}, "
            f"failed {len(manifest['failed'])}, added to the course {len(manifest['saved'])}. "
            f"Manifest: {MANIFEST_PATH}"
        ]
        lines += [
            f"- failed: {f['name'] if 'name' in f else f['module_id']}: {f['error']}"
            for f in manifest["failed"]
        ]
        return "\n".join(lines)

    tools = [list_course_contents, preview_module, fetch_materials]
    if project is None:
        return tools

    @tool(parse_docstring=True)
    def prepare_lectures() -> str:
        """Read the course syllabus into lectures and match its cited books to the readings.

        Call after fetch_materials has added the syllabus. Matching approves what it finds;
        there is no human review of the lectures. The lectures and reading files are saved to
        /course/lectures.json.

        Returns:
            The lectures with their ids and readings, and the readings attached to none.
        """
        with progress.action("Finding the syllabus in the course") as action:
            path = project.syllabus_path()
            if path is None:
                action.status, action.detail = "failed", "no PDF or DOCX syllabus"
                return (
                    "The course has no PDF or DOCX syllabus. Fetch it with category `syllabus` "
                    "first."
                )
            action.detail = path.rsplit("/", 1)[-1]
        with progress.action("Reading the syllabus into lectures") as action:
            transcript = project.read_syllabus(path)
            sessions = transcript.get("sessions", [])
            books = transcript.get("learning_materials", [])
            action.detail = f"{plural(len(sessions), 'lecture')}, {plural(len(books), 'book')}"
        with progress.action("Matching the cited books to the readings") as action:
            plan = project.map_readings()
            matched = sum(1 for b in plan["books"] if b["file"])
            action.detail = f"{matched} of {plural(len(plan['books']), 'book')} found"
        data, text = lectures_outline(plan)
        write_json(LECTURES_PATH, data)
        return f"{len(data['lectures'])} lectures, saved to {LECTURES_PATH}\n\n{text}"

    @tool(parse_docstring=True)
    def attach_readings(attachments: list[Attachment]) -> str:
        """Attach reading files to the lectures they belong to.

        Use the lecture ids and reading paths that prepare_lectures returned. A reading can be
        attached to several lectures.

        Args:
            attachments: Lecture id and reading path pairs.

        Returns:
            One line per failed attachment, then the updated lectures.
        """
        failures = []
        plan = None
        with progress.action(
            f"Attaching {plural(len(attachments), 'reading')} to lectures"
        ) as action:
            for attachment in attachments:
                try:
                    plan = project.attach(attachment.session_id, attachment.path)
                except ProjectError as error:
                    failures.append(f"- {attachment.path} -> {attachment.session_id}: {error}")
            done = len(attachments) - len(failures)
            action.detail = f"{done} attached" + (f", {len(failures)} failed" if failures else "")
        plan = plan or project.plan()
        data, text = lectures_outline(plan)
        write_json(LECTURES_PATH, data)
        return "\n".join([*failures, text]) if failures else text

    return [*tools, prepare_lectures, attach_readings]
