"""`render_notes`: the writer's one custom tool. Validates and renders the note it wrote.

It reads `/notes/index.qmd` and `/notes/assets/*.svg` from the agent's virtual filesystem, checks
them against the allowlist (`validate.py`), adds our front matter and renders with Quarto. The
answer is either OK with a summary, or the problems to fix, so the agent can repair its note.
The last build that rendered is kept in the run's work directory; the run publishes it.

The lecture and the output directory are bound by closure; the tool takes no arguments.
"""

import base64
import hashlib
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from deepagents.backends import StateBackend
from langchain_core.tools import BaseTool, tool

from app.note_taker.lecture_notes.build import BuildResult, Runner, front_matter, stage_and_render
from app.note_taker.lecture_notes.readings import LectureBundle
from app.note_taker.lecture_notes.validate import validate_body
from app.note_taker.progress import Progress

NOTE = "/notes/index.qmd"
ASSETS = "/notes/assets/"
MAX_REPORT = 3000


class RunCancelled(Exception):
    """The lecture page stopped the run."""


@dataclass
class RenderState:
    """What the tool has rendered in this run."""

    renders: int = 0
    good_digest: str | None = None  # of the body and assets of the last good build
    good: BuildResult | None = None
    warnings: list[str] = field(default_factory=list)


def digest(body: str, assets: dict[str, bytes]) -> str:
    h = hashlib.sha256(body.encode())
    for name in sorted(assets):
        h.update(name.encode() + b"\0" + assets[name])
    return h.hexdigest()


def read_note(backend: StateBackend) -> tuple[str | None, dict[str, bytes]]:
    """The note's body and its assets (`assets/<name>.svg` -> bytes) from the agent's files."""
    [note] = backend.download_files([NOTE])
    body = note.content.decode("utf-8", errors="replace") if note.content is not None else None
    listing = backend.ls(ASSETS)
    paths = [e["path"] for e in listing.entries or [] if not e.get("is_dir")]
    assets = {}
    for response in backend.download_files(paths) if paths else []:
        if response.content is not None:
            assets["assets/" + response.path[len(ASSETS) :]] = response.content
    return body, assets


def file_bytes(data: dict) -> bytes:
    content = data["content"]
    if isinstance(content, list):  # older FileData kept lines
        content = "\n".join(content)
    if data.get("encoding") == "base64":
        return base64.b64decode(content)
    return content.encode()


def note_from_files(files: dict[str, dict]) -> tuple[str | None, dict[str, bytes]]:
    """The same, from an agent result's `files` state."""
    note = files.get(NOTE)
    body = file_bytes(note).decode("utf-8", errors="replace") if note else None
    assets = {
        "assets/" + path[len(ASSETS) :]: file_bytes(data)
        for path, data in files.items()
        if path.startswith(ASSETS)
    }
    return body, assets


def summary(body: str, assets: dict[str, bytes]) -> str:
    sections = len(re.findall(r"^## ", body, re.M))
    dot = len(re.findall(r"^\s*```+\s*\{dot\}", body, re.M))
    mermaid = len(re.findall(r"^\s*```+\s*\{mermaid\}", body, re.M))
    ojs = len(re.findall(r"^\s*```+\s*\{ojs\}", body, re.M))
    tables = len(re.findall(r"^:\s.*\{#tbl-", body, re.M))
    return (
        f"{sections} sections, {dot} Graphviz and {mermaid} Mermaid diagrams, {ojs} OJS cells, "
        f"{len(assets)} SVG figures, {tables} captioned tables"
    )


def render(
    bundle: LectureBundle, body: str, assets: dict[str, bytes], runner: Runner, output: Path
) -> tuple[BuildResult | None, str]:
    """Validate and render. Returns the build (None when invalid or failed) and the message for
    the agent."""
    issues = validate_body(body, assets)
    if issues:
        listed = "\n".join(f"- {issue}" for issue in issues[:40])
        more = f"\n- ... and {len(issues) - 40} more" if len(issues) > 40 else ""
        return None, f"NOT RENDERED. Fix these problems in {NOTE} and render again:\n{listed}{more}"
    result = stage_and_render(front_matter(bundle) + "\n\n" + body + "\n", assets, runner, output)
    if not result.ok:
        return None, f"RENDER FAILED. Fix the note and render again.\n{result.log}"[:MAX_REPORT]
    message = f"OK: rendered {summary(body, assets)}."
    if mermaid := len(re.findall(r"\{mermaid\}", body)):
        message += (
            f" {mermaid} Mermaid diagram(s) are drawn in the reader's browser; their syntax is "
            "not checked here, so re-read them."
        )
    if result.warnings:
        warnings = "\n".join(f"- {w}" for w in result.warnings[:20])
        message += f"\nQuarto warnings to fix (unresolved references or citations):\n{warnings}"
    return result, message[:MAX_REPORT]


def make_render_tool(
    backend: StateBackend,
    bundle: LectureBundle,
    runner: Runner,
    output: Path,
    state: RenderState,
    *,
    max_renders: int = 12,
    progress: Progress | None = None,
    cancelled: threading.Event | None = None,
) -> BaseTool:
    progress = progress or Progress()

    @tool
    def render_notes() -> str:
        """Validate /notes/index.qmd (and /notes/assets/*.svg) and render it to HTML with Quarto.

        Returns OK with a short summary and any warnings, or the list of problems to fix. Call it
        after writing the note and after every round of fixes."""
        if cancelled is not None and cancelled.is_set():
            raise RunCancelled
        if state.renders >= max_renders:
            return (
                f"Render limit reached ({max_renders}). Stop editing; the last version that "
                "rendered will be published. Finish with your report."
            )
        body, assets = read_note(backend)
        if not body or not body.strip():
            return f"Nothing to render: write the note's body to {NOTE} first."
        state.renders += 1
        with progress.action(f"Rendering the notes ({state.renders})") as action:
            result, message = render(bundle, body, assets, runner, output)
            if result is None:
                action.status = "failed"
                action.detail = " ".join(message.splitlines()[:4])[:400]
            else:
                state.good, state.good_digest = result, digest(body, assets)
                state.warnings = result.warnings
                action.detail = summary(body, assets)
        return message

    return render_notes
