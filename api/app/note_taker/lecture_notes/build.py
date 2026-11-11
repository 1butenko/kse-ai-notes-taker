"""Render a lecture note to HTML with Quarto: our front matter, a staged project, a subprocess.

The agent writes only the body. The front matter, CSS and header are ours, so a note cannot turn
on code execution, filters or includes. Quarto runs in a fresh temporary directory with its own
project boundary, `--no-execute`, a time limit, and an environment without our secrets.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

from app.note_taker.lecture_notes.readings import LectureBundle

QUARTO_TIMEOUT = 300
TEMPLATES = Path(__file__).parent / "templates"
# Variables Quarto, Pandoc and Deno need; nothing else (no API keys) reaches the subprocess.
SAFE_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "XDG_CACHE_HOME",
    "SYSTEMROOT",
    "QUARTO_DENO_DOM",
)

CALLOUT_TITLES = {
    "uk": {
        "callout-note-title": "Примітка",
        "callout-tip-title": "Порада",
        "callout-important-title": "Важливо",
        "callout-warning-title": "Увага",
        "callout-caution-title": "Обережно",
        "crossref-def-title": "Означення",
        "crossref-thm-title": "Теорема",
        "crossref-lem-title": "Лема",
        "crossref-exm-title": "Приклад",
        "crossref-exr-title": "Вправа",
        "crossref-rem-title": "Зауваження",
        "proof-title-prefix": "Доведення",
        "section-title-footnotes": "Примітки",
    }
}


def yaml(value: str) -> str:
    """A YAML scalar: JSON strings are valid YAML and escape everything."""
    return json.dumps(value, ensure_ascii=False)


def quarto_language_lines(language: str) -> list[str]:
    """Quarto's labels for the page. Its Ukrainian file is `ua`, not `uk`, so `uk` needs its
    own labels."""
    uk = language == "uk"
    return [
        f"toc-title: {yaml('Зміст' if uk else 'Table of contents')}",
        "language:",
        f"  title-block-published: {yaml('Створено' if uk else 'Created')}",
        f"  section-title-references: {yaml('Джерела' if uk else 'References')}",
        *(
            [
                '  crossref-fig-title: "Рисунок"',
                '  crossref-tbl-title: "Таблиця"',
                '  crossref-sec-prefix: "Розділ"',
                '  crossref-eq-prefix: "Рівняння"',
            ]
            if uk
            else []
        ),
    ]


def front_matter(bundle: LectureBundle) -> str:
    language = bundle.language
    titles = CALLOUT_TITLES.get(language, {})
    return "\n".join(
        [
            "---",
            f"title: {yaml(bundle.topic)}",
            *([f"subtitle: {yaml(bundle.subtitle)}"] if bundle.subtitle else []),
            f"lang: {yaml(language)}",
            *quarto_language_lines(language),
            *[f"  {key}: {yaml(value)}" for key, value in titles.items()],
            "engine: markdown",
            "execute:",
            "  enabled: false",
            "citeproc: true",
            "references: " + json.dumps(bundle.references(), ensure_ascii=False),
            "format:",
            "  html:",
            "    toc: true",
            "    toc-location: left",
            "    toc-depth: 3",
            "    number-sections: true",
            "    html-math-method: mathjax",
            "    reference-location: margin",
            "    citation-location: margin",
            "    embed-resources: false",
            "    anchor-sections: true",
            "    css: lecture-notes.css",
            "    include-in-header: notes-head.html",
            "    mermaid:",
            "      theme: neutral",
            "---",
        ]
    )


@dataclass
class RenderOutcome:
    returncode: int
    log: str


Runner = Callable[[Path], RenderOutcome]
"""Renders `index.qmd` in the given directory to `index.html` next to it."""


class QuartoRunner:
    """`quarto render` in a subprocess. Shared by all runs in the worker, `concurrency` at once."""

    def __init__(self, binary: str = "quarto", concurrency: int = 2, timeout: int = QUARTO_TIMEOUT):
        self.binary = binary
        self.timeout = timeout
        self.gate = threading.BoundedSemaphore(max(1, concurrency))

    def __call__(self, stage: Path) -> RenderOutcome:
        binary = shutil.which(self.binary)
        if binary is None:
            return RenderOutcome(127, f"Quarto is not installed ({self.binary!r} not found)")
        env = {key: os.environ[key] for key in SAFE_ENV if key in os.environ}
        with self.gate:
            process = subprocess.Popen(
                [binary, "render", "index.qmd", "--to", "html", "--no-execute"],
                cwd=stage,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                output, _ = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, AttributeError):
                    process.kill()
                output, _ = process.communicate()
                return RenderOutcome(124, f"Quarto took longer than {self.timeout} s")
        return RenderOutcome(process.returncode, output.decode(errors="replace"))


@lru_cache
def default_runner() -> QuartoRunner:
    """The worker's one runner, so its gate limits every run's renders together."""
    from app.worker.config import get_worker_settings

    settings = get_worker_settings()
    return QuartoRunner(settings.quarto_bin, settings.quarto_concurrency)


@dataclass
class BuildResult:
    ok: bool
    log: str
    warnings: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)  # relative to the output directory


def warning_lines(log: str) -> list[str]:
    found = []
    for line in log.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        if re.match(r"(?:\[?WARN(?:ING)?\]?|WARNING)", line, re.I) and line not in found:
            found.append(line)
    return found


def stage_and_render(
    qmd: str, assets: dict[str, bytes], runner: Runner, output: Path
) -> BuildResult:
    """Render the full `qmd` with its assets. On success, `output` holds the site (replaced
    whole); on failure it is left as it was."""
    with TemporaryDirectory(prefix="lecture-notes-") as temporary:
        stage = Path(temporary) / "site"
        stage.mkdir()
        (stage / "_quarto.yml").write_text("project:\n  type: default\n")
        (stage / "index.qmd").write_text(qmd, encoding="utf-8")
        shutil.copyfile(TEMPLATES / "lecture-notes.css", stage / "lecture-notes.css")
        shutil.copyfile(TEMPLATES / "notes-head.html", stage / "notes-head.html")
        for name, data in assets.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        outcome = runner(stage)
        page = stage / "index.html"
        if outcome.returncode != 0 or not page.is_file():
            tail = outcome.log.strip()[-2500:]
            return BuildResult(False, f"Quarto failed (exit {outcome.returncode}):\n{tail}")
        warnings = warning_lines(outcome.log)
        if "?@" in page.read_text(encoding="utf-8", errors="replace"):
            refs = sorted(set(re.findall(r"\?@[\w-]+", page.read_text(errors="replace"))))
            warnings.append(f"Unresolved cross-references: {', '.join(refs)}")

        for leftover in ("_quarto.yml", "notes-head.html", ".quarto"):
            path = stage / leftover
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(stage, output)
    files = sorted(p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file())
    return BuildResult(True, outcome.log, warnings, files)
