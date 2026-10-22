"""Render prepared, format-specific notes without invoking a model."""

import asyncio
import html
import json
import os
import re
import shutil
import signal
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote

from app.notes import RenderedArtifact, RenderFormat

QUARTO_TIMEOUT = 600


class QuartoError(Exception):
    pass


def validate_markdown(value: str) -> None:
    """Accept text/math/displayed code, never executable Quarto or raw resources.

    This deliberately supports a smaller Markdown vocabulary than arbitrary QMD.
    The controlled reader also disables raw HTML/TeX/attributes and YAML blocks.
    Source text is never rewritten to make a rejected document appear valid.
    """
    if re.search(r"\{\{\s*[<%]|\{\s*=", value):
        raise QuartoError("Unsafe Markdown: shortcodes and raw attributes are not supported")
    # Resource/cell syntax is forbidden even inside displayed examples. Markdown
    # quotes/lists can end an apparent fence earlier than a line scanner expects.
    if re.search(r"!\s*\[|(?:`{3,}|~{3,})[^\n]*\{|^\s*(?:---|\.\.\.)\s*$", value, re.M):
        raise QuartoError(
            "Unsafe Markdown: images, executable cells and metadata are not supported"
        )
    decoded = re.sub(r"\s+", "", unquote(html.unescape(value)))
    if re.search(r"(?:[({<]|\]:)(?:javascript|vbscript|data|file):", decoded, re.I):
        raise QuartoError("Unsafe Markdown: active or local resource links are not supported")
    visible = []
    fence = None
    for line in value.splitlines():
        # Only top-level fences can hide arbitrary displayed code here. Nested
        # quote/list fences have context-sensitive endings, so inspect their text.
        match = re.match(r"^(`{3,}|~{3,})(.*)$", line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence):
                fence = None
            continue
        if match:
            if not re.fullmatch(r"[\w+.-]*", match[2].strip()):
                raise QuartoError("Unsafe Markdown: use a plain language name for displayed code")
            fence = match[1]
        else:
            visible.append(line)
    value = "\n".join(visible)
    value = re.sub(r"(`+)(.+?)\1", "", value, flags=re.S)
    if re.search(
        r"\\(?:input|include|includegraphics|write|openin|openout|read|usepackage)\b", value
    ):
        raise QuartoError("Unsafe Markdown: external TeX resources are not supported")
    prose = re.sub(r"\$\$.+?\$\$|\$[^$\n]+?\$", "", value, flags=re.S)
    if re.search(r"<\s*(?:/?[A-Za-z][^>\n]*>|!|\?)", prose):
        raise QuartoError("Unsafe Markdown: raw HTML is not supported")
    if re.search(r"\\[A-Za-z]+|\{[^{}]*=", prose):
        raise QuartoError("Unsafe Markdown: raw TeX and custom attributes are not supported")


def validated_source(source: str, target: RenderFormat) -> str:
    """Accept only our canonical, quoted configuration, including on rerenders."""
    from app.worker.render import front_matter

    if not source.startswith("---\n"):
        validate_markdown(source)
        return front_matter("Notes", "", "en", target=target) + "\n\n" + source
    try:
        header, body = source[4:].split("\n---\n", 1)
        values = {}
        for line in header.splitlines():
            key, _, raw = line.partition(": ")
            if key in ("title", "date", "lang", "subtitle"):
                values[key] = json.loads(raw)
                if not isinstance(values[key], str):
                    raise ValueError("Metadata must be text")
                validate_markdown(values[key])
        canonical = front_matter(
            values["title"],
            values["date"],
            values["lang"],
            values.get("subtitle"),
            outline="    toc: true" in header.splitlines(),
            target=target,
        )
        if "---\n" + header + "\n---" != canonical:
            raise ValueError("Only the server's rendering configuration is accepted")
        validate_markdown(body)
    except (KeyError, ValueError) as error:
        raise QuartoError(f"Unsafe QMD configuration: {error}") from error
    return source


async def render_document(
    sources: dict[RenderFormat, Path], output_dir: Path, revision: int, quarto: str
) -> list[RenderedArtifact]:
    """Publish only successful outputs; failures leave previous artifacts untouched.

    Paths in the result are relative to output_dir. Callers rendering topics under
    a run's artifacts root add that topic's directory prefix and topic_id.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    binary = shutil.which(quarto)
    artifacts = []
    with TemporaryDirectory(prefix=".quarto-", dir=output_dir) as temporary:
        for target, source in sources.items():
            destination = output_dir / f"{source.stem}.{target}"
            artifact = RenderedArtifact(
                format=target, path=destination.name, revision=revision, status="failed"
            )
            log = ""
            try:
                prepared = validated_source(source.read_text(), target)
                if binary is None:
                    raise QuartoError(f"Quarto is not installed ({quarto!r} not found)")
                stage = Path(temporary) / target
                stage.mkdir()
                # A controlled project boundary prevents parent project configuration,
                # extensions and metadata from being discovered by Quarto.
                (stage / "_quarto.yml").write_text("project:\n  type: default\n")
                staged_source = stage / source.name
                staged_source.write_text(prepared)
                if target == "html":
                    for asset in ("notes.css", "notes-head.html"):
                        shutil.copyfile(Path(__file__).parent / "templates" / asset, stage / asset)
                process = await asyncio.create_subprocess_exec(
                    binary,
                    "render",
                    staged_source.name,
                    "--to",
                    "typst" if target == "pdf" else target,
                    "--output",
                    destination.name,
                    "--no-execute",
                    cwd=stage,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
                communication = asyncio.create_task(process.communicate())
                try:
                    output, _ = await asyncio.wait_for(
                        asyncio.shield(communication), QUARTO_TIMEOUT
                    )
                except (TimeoutError, asyncio.CancelledError) as error:
                    # Quarto launches Pandoc/Typst: terminate the group, then drain
                    # pipes and reap the parent before cleaning its working files.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    output, _ = await communication
                    log = output.decode(errors="replace")
                    if isinstance(error, asyncio.CancelledError):
                        raise
                    raise QuartoError(f"Quarto took longer than {QUARTO_TIMEOUT} s") from error
                log = output.decode(errors="replace")
                rendered = stage / destination.name
                if process.returncode != 0 or not rendered.is_file():
                    tail = re.sub(r"\s+", " ", log[-600:]).strip()
                    raise QuartoError(f"Quarto failed (exit {process.returncode}): {tail}")
                os.replace(rendered, destination)
                artifact.status = "ready"
            except (OSError, QuartoError) as error:
                artifact.error = str(error)
            (output_dir / f"quarto-{target}.log").write_text(log or artifact.error or "")
            artifacts.append(artifact)
    return artifacts
