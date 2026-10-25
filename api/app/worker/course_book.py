"""Controlled, single-snapshot Quarto book project and immutable output."""

import asyncio
import json
import os
import re
import shutil
import signal
from pathlib import Path

from app.notes import NotesDocument, RenderedArtifact
from app.notes_artifacts import BOOK_SUFFIXES
from app.worker.quarto import QUARTO_TIMEOUT, QuartoError, subprocess_gate, validate_markdown
from app.worker.references import ReferenceContext, build_reference_data, reference_id
from app.worker.render import (
    bibliography,
    checked_document,
    footer,
    labels,
    quarto_language_lines,
    topic_body,
)

QUARTO_ES6_POLYFILL = (
    b'<script src="https://cdnjs.cloudflare.com/polyfill/v3/polyfill.min.js?features=es6"></script>'
)


def build_book_project(document: NotesDocument, directory: Path, language: str) -> Path:
    """Write only validated notes and server-owned assets into an isolated project."""
    if language not in ("uk", "en") or document.language != language:
        raise ValueError("Book language must match the saved document")
    directory.mkdir(parents=True, exist_ok=True)
    # A failed topic can lack labels referenced by a later chapter. Preserve its status
    # page and the later chapter instead of failing the whole book.
    references = build_reference_data(document)
    for item in references:
        validate_markdown(item["title"])
    validate_markdown(document.title)
    topics = [(section, topic) for section in document.sections for topic in section.topics]
    ids = [topic.topic_id for _, topic in topics]
    if len(ids) != len(set(ids)):
        raise ValueError("Book topic IDs must be distinct")
    # reference_id is a reversible filename-safe encoding of the stable topic ID.
    chapters = {item: f"{reference_id(item)[4:]}.html" for item in ids}
    context = ReferenceContext(book_chapters=chapters)
    text = labels(language)
    index = checked_document("", [footer(document, text)], document.title)
    (directory / "index.qmd").write_text(
        "---\ntitle: " + json.dumps(document.title, ensure_ascii=False) + "\n---\n" + index
    )
    for section, topic in topics:
        validate_markdown(section.title)
        validate_markdown(topic.title)
        body = [f"# {topic.title} {{#{reference_id(topic.topic_id)}}}\n"]
        if topic.status == "failed":
            warning = (
                "Не вдалося створити тему. Її зміст відсутній у цій ревізії."
                if language == "uk"
                else "This topic could not be generated for this revision."
            )
            body.append(f"::: {{.callout-caution}}\n## {warning}\n:::\n")
        else:
            body += topic_body(topic, text, document, "html", topic.topic_id, context)
        (directory / chapters[topic.topic_id].replace(".html", ".qmd")).write_text(
            checked_document("", body, topic.title, assets={a.path for a in document.assets})
        )
    if references:
        (directory / "references.qmd").write_text(
            checked_document("", bibliography(text), text["references"])
        )
    from app.worker.templates import __path__ as template_paths

    template = Path(next(iter(template_paths)))
    shutil.copyfile(template / "notes-head.html", directory / "notes-head.html")
    # Book layout is provided by Quarto; keep only the server-owned accessibility rules.
    (directory / "book.css").write_text(
        ".callout-body{overflow-wrap:anywhere} img{max-width:100%} pre{overflow-x:auto}\n"
    )
    config = [
        "project:",
        "  type: book",
        "  output-dir: _book",
        "book:",
        f"  title: {json.dumps(document.title, ensure_ascii=False)}",
        "  search: true",
        "  chapters:",
        "    - index.qmd",
        *(f"    - {chapters[topic.topic_id].replace('.html', '.qmd')}" for _, topic in topics),
        *(["    - references.qmd"] if references else []),
        f"lang: {json.dumps(language)}",
        *quarto_language_lines(language),
        "citeproc: true",
        "references: " + json.dumps(references, ensure_ascii=False),
        "from: markdown+lists_without_preceding_blankline-raw_html-raw_tex-"
        "raw_attribute-yaml_metadata_block",
        "execute:",
        "  enabled: false",
        "format:",
        "  html:",
        "    theme: default",
        "    html-math-method:",
        "      method: mathjax",
        "      url: https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml-full.js",
        "    include-in-header: notes-head.html",
        "    css: book.css",
    ]
    path = directory / "_quarto.yml"
    path.write_text("\n".join(config) + "\n")
    return path


async def render_book(
    directory: Path, revision: int, quarto: str, concurrency: int = 4
) -> RenderedArtifact:
    """Render in this job's private source directory; publish a complete allowlist last."""
    artifact = RenderedArtifact(format="book", path="book", revision=revision, status="failed")
    binary = shutil.which(quarto)
    if binary is None:
        artifact.error = f"Quarto is not installed ({quarto!r} not found)"
        return artifact
    log = ""
    try:
        async with subprocess_gate(concurrency):
            process = await asyncio.create_subprocess_exec(
                binary,
                "render",
                ".",
                "--to",
                "html",
                "--no-execute",
                cwd=directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            communication = asyncio.create_task(process.communicate())
            try:
                output, _ = await asyncio.wait_for(asyncio.shield(communication), QUARTO_TIMEOUT)
            except (TimeoutError, asyncio.CancelledError) as error:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                output, _ = await communication
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise QuartoError(f"Quarto took longer than {QUARTO_TIMEOUT} s") from error
        log = output.decode(errors="replace")
        if process.returncode != 0:
            tail = re.sub(r"\s+", " ", log[-600:]).strip()
            raise QuartoError(f"Quarto failed (exit {process.returncode}): {tail}")
        rendered = directory / "_book"
        if not (rendered / "index.html").is_file() or not (rendered / "search.json").is_file():
            raise QuartoError("Quarto did not produce a searchable book")
        destination = directory.parent / "book"
        if destination.exists():
            raise QuartoError("Book publication destination already exists")
        # Publish only approved generated file types, never the QMD project or hidden metadata.
        approved = []
        for source in rendered.rglob("*"):
            if source.is_symlink():
                raise QuartoError("Book output contains a symlink")
            if not source.is_file():
                continue
            relative = source.relative_to(rendered)
            if (
                any(part.startswith(".") or part.startswith("_") for part in relative.parts)
                or source.suffix.lower() not in BOOK_SUFFIXES
            ):
                continue
            approved.append(relative.as_posix())
        if "index.html" not in approved or "search.json" not in approved:
            raise QuartoError("Book publication is incomplete")
        destination.mkdir()
        for name in approved:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix == ".html":
                # Quarto's fixed ES6 polyfill URL is unnecessary in the supported
                # modern browsers. Remove only that generated tag from public HTML.
                target.write_bytes((rendered / name).read_bytes().replace(QUARTO_ES6_POLYFILL, b""))
            else:
                shutil.copyfile(rendered / name, target)
        (destination / "publication.json").write_text(json.dumps(sorted(approved)))
        artifact.status = "ready"
    except (OSError, QuartoError) as error:
        artifact.error = str(error)
    (directory.parent / "quarto-book.log").write_text(log or artifact.error or "")
    return artifact
