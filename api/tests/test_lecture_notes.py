"""The lecture-notes agent: readings, the note validator, rendering, the agent's run, skills."""

# ruff: noqa: F401, F811

import shutil
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult

from app.note_taker.lecture_notes import runs, skill_library
from app.note_taker.lecture_notes.agent import build_lecture_notes_agent
from app.note_taker.lecture_notes.build import (
    RenderOutcome,
    front_matter,
    page_chrome,
    stage_and_render,
    warning_lines,
)
from app.note_taker.lecture_notes.readings import (
    LectureNotFound,
    brief_markdown,
    load_lecture,
    seed_files,
)
from app.note_taker.lecture_notes.tools import RunCancelled, check_sign_off, render
from app.note_taker.lecture_notes.validate import validate_body
from app.worker.config import WorkerSettings
from tests.courses import course

SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img">'
    b'<title>Dot</title><circle cx="5" cy="5" r="4" fill="#4a78b5"/></svg>'
)

GOOD_BODY = """::: {.callout-note title="What you will learn"}
- Solve linear systems.
:::

## Why it matters {#sec-why}

Systems appear everywhere [@r1, p. 10]. See @fig-map and @tbl-cmp.

::: {#def-system}
## Linear system
A set of linear equations $a x + b y = c$.
:::

$$
x = \\frac{c - b y}{a}, \\qquad \\bar{y} = \\frac{1}{T} \\sum_{t=1}^{T} y_t
$$ {#eq-x}

The mean $\\sum_{i=1}^{n} x_i$ inline, and $$\\hat{y}_{T+h|T} = y_{T}$$ on one line.

```{dot}
//| label: fig-map
//| fig-cap: "Map"
digraph { "Рівняння" -> "Розв'язок" }
```

```{mermaid}
%%| fig-cap: "Flow"
flowchart LR
  A["Start"] --> B["End"]
```

```{ojs}
//| echo: false
viewof k = Inputs.range([0, 5], {value: 1, step: 0.1, label: "k"})
```

```python
print("shown, not run")
```

::: {.panel-tabset group="views"}
## Intuition
Lines crossing.
## Formal
$Ax = b$.
:::

:::: {.columns}
::: {.column width="50%"}
Text.
:::
::: {.column width="50%"}
![A dot](assets/dot.svg){#fig-dot width=60%}
:::
::::

| A | B |
|---|---|
| 1 | 2 |

: Comparison {#tbl-cmp tbl-colwidths="[50,50]"}

::: {.callout-note collapse="true" title="Solution"}
Use <kbd>Enter</kbd>, x<sub>1</sub>. A footnote.^[In the margin.]
:::

[Docs](https://quarto.org) and [back](#sec-why).

***
"""


# Readings


def test_lecture_bundle_holds_only_its_readings(tmp_path: Path) -> None:
    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s1")

    assert bundle.topic == "Linear systems" and bundle.language == "en"
    [reading] = bundle.readings
    assert reading.key == "r1" and reading.label == "Ch. 1"
    assert [p.pdf_page for p in reading.pages] == [1, 2]
    assert bundle.references() == [
        {"id": "r1", "type": "document", "title": f"{reading.title}: Ch. 1"}
    ]
    files = seed_files(bundle)
    assert set(files) == {"/lecture/brief.md", "/lecture/references.json", reading.path}
    assert "<!-- PDF p. 1" in files[reading.path]["content"]
    assert "`@r1`" in brief_markdown(bundle)

    other = load_lecture(tmp_path, "1", "s2")
    assert [r.file for r in other.readings] == ["1/reading/handout.md"]
    assert other.readings[0].pages[0].pdf_page is None


def test_reading_text_is_capped(tmp_path: Path) -> None:
    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s2", max_chars=20)

    assert bundle.readings[0].chars == 20 and bundle.readings[0].truncated
    assert any("was cut" in w for w in bundle.warnings)


def test_unknown_lecture(tmp_path: Path) -> None:
    course(tmp_path)
    with pytest.raises(LectureNotFound):
        load_lecture(tmp_path, "1", "nope")


# Validator


def test_validator_accepts_every_allowed_feature() -> None:
    assert validate_body(GOOD_BODY, {"assets/dot.svg": SVG}) == []


@pytest.mark.parametrize(
    "body",
    [
        "---\ntitle: x\n---",
        "```{python}\nprint(1)\n```",
        "```{r}\n1\n```",
        "```{.python .cell}\nx\n```",
        "{{< include secrets.qmd >}}",
        "```{=html}\n<script>x</script>\n```",
        "Text `x`{=html}.",
        "<script>alert(1)</script>",
        '<span style="x">a</span>',
        "<!-- hidden -->",
        "[x](javascript:alert(1))",
        "[x](file:///etc/passwd)",
        "[x](other.html)",
        "[x]: data:text/html,hi",
        "![x](https://evil.test/a.png)",
        "![x](assets/missing.svg)",
        "::: {.custom-class}\nx\n:::",
        '::: {.callout-note onclick="x"}\nx\n:::',
        "## Title {#weird-id}",
        'Text [x]{style="color:red"}.',
        "$\\href{javascript:x}{y}$",
        "```{ojs}\nd = fetch('https://evil.test')\n```",
        '```{ojs}\nimport {x} from "@user/notebook"\n```',
        "```{ojs}\nwindow.parent.postMessage(1)\n```",
        "```{ojs}\nFileAttachment('a.csv')\n```",
        "```{ojs}\n//| file: secret.js\n```",
        "```{dot}\n//| label: map\ndigraph {}\n```",
        '```{dot}\ndigraph { a [image="/etc/passwd"] }\n```',
        "```{mermaid}\nflowchart LR\n  A --> B\n  click A callback\n```",
        "```{mermaid}\n%%{init: {'securityLevel': 'loose'}}%%\nflowchart LR\n```",
        "```python\nunterminated",
    ],
)
def test_validator_rejects(body: str) -> None:
    assert validate_body(body), body


@pytest.mark.parametrize(
    "svg",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink">'
        b'<use x:href="https://evil.test/a.svg#x"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(https://e.test/x)"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import "x.css";</style></svg>',
        b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
        b"<html/>",
        b"not xml",
    ],
)
def test_validator_rejects_unsafe_svg(svg: bytes) -> None:
    assert validate_body("![x](assets/a.svg)", {"assets/a.svg": svg})


def test_validator_reports_lines() -> None:
    [issue] = validate_body("ok\n\n```{python}\n1\n```")
    assert issue.line == 3 and str(issue).startswith("line 3:")


def test_validator_refuses_long_lines_before_its_slow_checks() -> None:
    import time

    # Crafted to be quadratic in the line checks (CodeQL py/polynomial-redos).
    crafted = "![" * 20_000 + "\n" + "<A" + "-" * 50_000
    start = time.monotonic()
    issues = validate_body("ok\n" + crafted)
    assert time.monotonic() - start < 1
    assert [i.line for i in issues] == [2, 3]
    assert "characters" in issues[0].message
    assert validate_body("x" * 400_000)[0].message.startswith("the note is over")


def test_line_checks_are_fast_on_crafted_lines_under_the_cap() -> None:
    import time

    from app.note_taker.lecture_notes.validate import MAX_LINE_CHARS, line_issues

    n = MAX_LINE_CHARS // 4
    crafted = [
        "`" * MAX_LINE_CHARS,
        "``` " + " " * (MAX_LINE_CHARS - 5) + "x",
        "::: " + " " * (MAX_LINE_CHARS - 5) + "x",
        "![" * n,
        "![](" * n,
        "<http:" * n,
        "<a" * n,
        'a="' * n,
    ]
    start = time.monotonic()
    for line in crafted:
        validate_body(line)
        line_issues(1, line, {})
    assert time.monotonic() - start < 1


def test_linear_rewrites_match_the_old_regexes() -> None:
    import re

    from app.note_taker.lecture_notes.validate import html_tags, strip_code_spans

    for text in ["<b>x</b>", "a <span class='x'>b", "<b <i>", "<em>", "1 < 2 > 0", "<a", "</q >"]:
        assert html_tags(text) == re.findall(r"</?([A-Za-z][\w-]*)([^>]*)>", text)
    assert strip_code_spans("a `{x}` b ``c ` d`` e") == "a   b   e"
    assert strip_code_spans("a ` b") == "a ` b"
    assert strip_code_spans("``a` `b``") == " "


def test_skill_examples_pass_the_validator() -> None:
    """The skills teach only what render_notes accepts."""
    import re

    names = ["projection", "picture", "before", "after", "queue"]
    assets = {f"assets/{n}.svg": SVG for n in names}
    for path in sorted(skill_library.SKILLS_DIR.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^(`{3,4})markdown\n(.*?)^\1\s*$", text, re.S | re.M):
            assert validate_body(match[2], assets) == [], (path.parent.name, match[2][:80])


# Rendering


class FakeRunner:
    """Writes a page the way Quarto would, and records each render."""

    def __init__(self, returncode: int = 0, log: str = "Output created: index.html") -> None:
        self.calls: list[str] = []
        self.returncode, self.log = returncode, log

    def __call__(self, stage: Path) -> RenderOutcome:
        qmd = (stage / "index.qmd").read_text(encoding="utf-8")
        self.calls.append(qmd)
        if self.returncode == 0:
            (stage / "index.html").write_text("<html>notes</html>")
            (stage / "index_files/libs").mkdir(parents=True)
            (stage / "index_files/libs/quarto.js").write_text("//")
        return RenderOutcome(self.returncode, self.log)


def test_render_adds_our_front_matter_and_keeps_only_the_site(tmp_path: Path) -> None:
    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s1")
    runner = FakeRunner(log="WARNING (x): Citeproc: citation r9 not found")
    output = tmp_path / "site"

    result = stage_and_render(
        front_matter(bundle) + "\n\nBody", {"assets/dot.svg": SVG}, runner, output
    )

    assert result.ok and result.warnings == ["WARNING (x): Citeproc: citation r9 not found"]
    qmd = runner.calls[0]
    assert qmd.startswith('---\ntitle: "Linear systems"')
    assert "engine: markdown" in qmd and "  enabled: false" in qmd
    assert '"id": "r1"' in qmd
    assert set(result.files) == {
        "index.html",
        "index.qmd",
        "lecture-notes.css",
        "fonts/KSE-SansRegular.woff2",
        "fonts/KSE-SansMedium.woff2",
        "fonts/KSE-SansBold.woff2",
        "assets/dot.svg",
        "index_files/libs/quarto.js",
    }
    assert "theme: [default, kse-theme.scss]" in qmd


def test_failed_render_keeps_the_previous_site(tmp_path: Path) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "index.html").write_text("old")

    result = stage_and_render("---\n---\nx", {}, FakeRunner(1, "ERROR: boom"), output)

    assert not result.ok and "boom" in result.log
    assert (output / "index.html").read_text() == "old"


def test_ukrainian_front_matter() -> None:
    from app.note_taker.lecture_notes.readings import LectureBundle

    bundle = LectureBundle("1", "s1", "Лекція 1", 1, None, "Матриці", [], "uk", [], [])
    text = front_matter(bundle)
    assert 'lang: "uk"' in text and 'callout-tip-title: "Порада"' in text


def test_page_chrome_has_the_logo_and_escapes_the_sign_off(tmp_path: Path) -> None:
    from app.note_taker.lecture_notes.readings import LectureBundle

    bundle = LectureBundle("1", "s1", "Lecture 1", 1, None, "Matrices", [], "en", [], [])
    runner = FakeRunner()
    chrome = page_chrome(bundle, "Stay curious & keep going")

    result = stage_and_render(
        front_matter(bundle) + "\n\nBody", {}, runner, tmp_path / "site", chrome
    )

    assert "include-before-body: notes-header.html" in runner.calls[0]
    assert 'aria-label="Kyiv School of Economics"' in chrome["notes-header.html"]
    assert "Stay curious &amp; keep going" in chrome["notes-footer.html"]
    assert "KSE Note Agent" in chrome["notes-footer.html"]
    assert not {"notes-header.html", "notes-footer.html"} & set(result.files)
    default = page_chrome(LectureBundle("1", "s1", "", 1, None, "М", [], "uk", [], []))
    assert "З вірою у ваше зростання" in default["notes-footer.html"]


def test_sign_off_rules() -> None:
    assert check_sign_off(None) == (None, [])
    assert check_sign_off("  \n") == (None, [])
    assert check_sign_off(" May all your equilibria be stable.\n") == (
        "May all your equilibria be stable.",
        [],
    )
    for bad in ["two\nlines", "x" * 121, "<b>hi</b>", "see https://x.y", "$x^2$"]:
        assert check_sign_off(bad)[1], bad


def test_an_invalid_sign_off_is_not_rendered(tmp_path: Path) -> None:
    from app.note_taker.lecture_notes.readings import LectureBundle

    bundle = LectureBundle("1", "s1", "Lecture 1", 1, None, "Matrices", [], "en", [], [])
    result, message = render(bundle, "Body", {}, FakeRunner(), tmp_path / "site", "<script>")
    assert result is None and "/notes/sign-off.txt" in message


def test_rerender_reads_back_the_body_and_the_agent_sign_off() -> None:
    from app.note_taker.lecture_notes.readings import LectureBundle
    from app.note_taker.lecture_notes.rerender import old_sign_off, split_front_matter

    bundle = LectureBundle("1", "s1", "Lecture 1", 1, None, "Matrices", [], "en", [], [])
    front, body = split_front_matter(front_matter(bundle) + "\n\n## One\n\nText\n")
    assert body == "## One\n\nText\n" and front.startswith('title: "Matrices"')

    footer = page_chrome(bundle, "Rank & file")["notes-footer.html"]
    assert old_sign_off(f"<html>{footer}</html>") == "Rank & file"
    assert old_sign_off(page_chrome(bundle)["notes-footer.html"]) is None
    assert old_sign_off("<html>old page</html>") is None


def test_warning_lines_strip_colours() -> None:
    assert warning_lines("\x1b[33mWARNING: x\x1b[0m\nfine") == ["WARNING: x"]


# The agent


class ScriptedModel(GenericFakeChatModel):
    """Replays a script; records the tools it was given and every prompt it saw."""

    tools_seen: list[list[str]] = []
    prompts: list[str] = []

    def bind_tools(self, tools, **kwargs) -> "ScriptedModel":
        self.tools_seen.append([getattr(t, "name", None) or t.get("name") for t in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.prompts.append("\n".join(str(m.content) for m in messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def call(name: str, args: dict, id_: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id_}])


SKILL = skill_library.Skill(
    "graphviz-diagrams",
    {"SKILL.md": "---\nname: graphviz-diagrams\ndescription: Draw with dot.\n---\n\n# Dot\n"},
)


def writer_script(note: str) -> list[AIMessage]:
    return [
        call("write_todos", {"todos": [{"content": "Write", "status": "in_progress"}]}, "w0"),
        call("write_file", {"file_path": "/notes/index.qmd", "content": note}, "w1"),
        call("render_notes", {}, "w2"),
        call(
            "edit_file",
            {
                "file_path": "/notes/index.qmd",
                "old_string": "```{python}\nprint(1)\n```",
                "new_string": "```python\nprint(1)\n```",
            },
            "w3",
        ),
        call("render_notes", {}, "w4"),
        call("task", {"subagent_type": "reviewer", "description": "Review the note"}, "w5"),
        # The reviewer (same model): it may not write.
        call("write_file", {"file_path": "/notes/evil.qmd", "content": "x"}, "r1"),
        AIMessage(content="1. should fix: add an example."),
        AIMessage(content="Report: 2 sections, 1 diagram."),
    ]


NOTE = "## Systems {#sec-s}\n\nText [@r1, p. 10].\n\n```{python}\nprint(1)\n```\n"


def test_writer_renders_fixes_and_gets_a_review(tmp_path: Path) -> None:
    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s1")
    model = ScriptedModel(messages=iter(writer_script(NOTE)))
    model.tools_seen, model.prompts = [], []
    runner = FakeRunner()
    built = build_lecture_notes_agent(
        bundle, tmp_path / "build", model=model, runner=runner, skills=[SKILL]
    )

    result = built.agent.invoke(
        {"messages": [("user", built.request)], "files": built.files},
        config={"recursion_limit": 60},
    )

    assert result["messages"][-1].text == "Report: 2 sections, 1 diagram."
    # The first render was refused by the validator; only the fixed note reached Quarto.
    assert len(runner.calls) == 1 and "```python" in runner.calls[0]
    assert built.state.renders == 2 and built.state.good is not None
    assert (tmp_path / "build/index.html").is_file()
    # Skills and readings were in the filesystem, and the reviewer could not write.
    assert "/skills/graphviz-diagrams/SKILL.md" in result["files"]
    assert any(p.startswith("/readings/") for p in result["files"])
    assert "/notes/evil.qmd" not in result["files"]
    writer_tools = built_tools = model.tools_seen[0]
    assert "render_notes" in writer_tools and "task" in writer_tools
    assert "execute" not in built_tools
    assert "graphviz-diagrams" in model.prompts[0] and "Quarto skills" in model.prompts[0]
    assert built.prompt_versions["note-taker/lecture-notes/writer"] is None  # fallback


def test_writer_may_not_overwrite_its_readings(tmp_path: Path) -> None:
    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s2")
    path = bundle.readings[0].path
    model = ScriptedModel(
        messages=iter(
            [
                call("write_file", {"file_path": path, "content": "x"}, "a"),
                AIMessage(content="done"),
            ]
        )
    )
    built = build_lecture_notes_agent(
        bundle, tmp_path / "b", model=model, runner=FakeRunner(), skills=[SKILL]
    )
    result = built.agent.invoke({"messages": [("user", "go")], "files": built.files})
    assert "Every vector space" in result["files"][path]["content"]


def test_render_limit(tmp_path: Path) -> None:
    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s2")
    model = ScriptedModel(
        messages=iter(
            [
                call("write_file", {"file_path": "/notes/index.qmd", "content": "## A"}, "a"),
                call("render_notes", {}, "b"),
                call("render_notes", {}, "c"),
                AIMessage(content="done"),
            ]
        )
    )
    built = build_lecture_notes_agent(
        bundle, tmp_path / "b", model=model, runner=FakeRunner(), skills=[SKILL], max_renders=1
    )
    result = built.agent.invoke({"messages": [("user", "go")], "files": built.files})
    replies = [m.text for m in result["messages"] if m.type == "tool"]
    assert replies[-1].startswith("Render limit reached")


def test_cancelled_run_stops_before_the_model(tmp_path: Path) -> None:
    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s2")
    cancelled = threading.Event()
    cancelled.set()
    built = build_lecture_notes_agent(
        bundle,
        tmp_path / "b",
        model=ScriptedModel(messages=iter([AIMessage(content="x")])),
        runner=FakeRunner(),
        skills=[SKILL],
        cancelled=cancelled,
    )
    with pytest.raises(RunCancelled):
        built.agent.invoke({"messages": [("user", "go")], "files": built.files})


# A whole run


@pytest.fixture
def run_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """execute_run with the course in tmp_path, the run row and S3 replaced by records."""
    course(tmp_path)
    settings = WorkerSettings(uploads_dir=tmp_path, openrouter_api_key="k")
    monkeypatch.setattr("app.worker.config.get_worker_settings", lambda: settings)
    record: dict[str, Any] = {"progress": [], "uploads": tmp_path}
    monkeypatch.setattr(runs, "save_progress", lambda *args: record["progress"].append(args))
    monkeypatch.setattr(
        runs, "finish_run", lambda run_id, status, **kw: record.update(status=status, **kw)
    )
    return record


def test_execute_run_publishes_the_last_good_build(run_env: dict, tmp_path: Path) -> None:
    published: dict[str, list[str]] = {}

    def publisher(build: Path, prefix: str) -> list[str]:
        files = sorted(p.relative_to(build).as_posix() for p in build.rglob("*") if p.is_file())
        published[prefix] = files
        return files

    run_id, course_id = uuid4(), uuid4()
    runs.execute_run(
        run_id,
        course_id,
        "1",
        "s1",
        model=ScriptedModel(messages=iter(writer_script(NOTE))),
        runner=FakeRunner(),
        skills=[SKILL],
        publisher=publisher,
    )

    assert run_env["status"] == "succeeded", run_env.get("error")
    [prefix] = published
    assert prefix == f"courses/{course_id}/lecture-notes/s1/{run_id}/"
    assert "index.html" in run_env["files"] and "index.qmd" in run_env["files"]
    assert run_env["renders"] == 2
    assert run_env["prompt_versions"]["skills"] == {"graphviz-diagrams": None}
    assert run_env["report"] == "Report: 2 sections, 1 diagram."
    assert not (tmp_path / ".lecture-notes" / str(run_id)).exists()
    assert run_id not in runs.CANCEL


def test_execute_run_fails_when_nothing_rendered(run_env: dict) -> None:
    runs.execute_run(
        uuid4(),
        uuid4(),
        "1",
        "s1",
        model=ScriptedModel(messages=iter([AIMessage(content="I give up.")])),
        runner=FakeRunner(),
        skills=[SKILL],
        publisher=lambda build, prefix: [],
    )
    assert run_env["status"] == "failed" and "never rendered" in run_env["error"]


def test_execute_run_records_an_unknown_lecture(run_env: dict) -> None:
    runs.execute_run(uuid4(), uuid4(), "1", "nope", model=object(), skills=[SKILL])
    assert run_env["status"] == "failed" and "LectureNotFound" in run_env["error"]


# Skills and prompts


def test_repo_skills_are_well_formed() -> None:
    skills = skill_library.local_skills()
    assert len(skills) == 11
    for name, files in skills.items():
        assert skill_library.valid(name, files), name


class FakeSkills:
    def __init__(self, stored: dict[str, Any]) -> None:
        self.stored = stored
        self.created: list[Any] = []

    def get(self, name, label=None, include_content=None):
        from langfuse.api import NotFoundError

        if name not in self.stored:
            raise NotFoundError(body="missing")
        return self.stored[name]

    def create_version(self, files, commit_message=None):
        from types import SimpleNamespace

        text = next(f.content for f in files if f.path == "SKILL.md")
        version = SimpleNamespace(name=skill_library.frontmatter_name(text), version=1)
        self.created.append((version.name, {f.path: f.content for f in files}))
        return version

    def set_labels(self, name, version, labels):
        self.labels = (name, version, labels)

    def update(self, name, tags):
        self.tags = (name, tags)


def skill_version(name: str, files: dict[str, str], version: int = 3):
    from types import SimpleNamespace

    return SimpleNamespace(
        version=version,
        files=[SimpleNamespace(path=p, content=c) for p, c in files.items()],
    )


def fake_client(stored: dict[str, Any]):
    from types import SimpleNamespace

    return SimpleNamespace(api=SimpleNamespace(skills=FakeSkills(stored)))


def skills_dir(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    (root / "dot").mkdir(parents=True)
    (root / "dot/SKILL.md").write_text("---\nname: dot\ndescription: d\n---\nlocal\n")
    return root


def test_skills_come_from_langfuse_with_the_repo_as_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = skills_dir(tmp_path)
    assert skill_library.load_skills(root)[0].version is None  # Langfuse off

    remote = {"SKILL.md": "---\nname: dot\ndescription: d\n---\nremote\n"}
    client = fake_client({"dot": skill_version("dot", remote)})
    monkeypatch.setattr("app.prompts.langfuse_client", lambda: client)
    [skill] = skill_library.load_skills(root)
    assert skill.version == 3 and "remote" in skill.files["SKILL.md"]
    assert skill_library.references([skill]) == [{"name": "dot", "version": 3}]
    assert "/skills/dot/SKILL.md" in skill_library.seed_files([skill])

    # A malformed Langfuse version falls back to the repo copy.
    bad = fake_client({"dot": skill_version("dot", {"SKILL.md": "no frontmatter"})})
    monkeypatch.setattr("app.prompts.langfuse_client", lambda: bad)
    assert skill_library.load_skills(root)[0].version is None


def test_skill_push_and_pull(tmp_path: Path) -> None:
    root = skills_dir(tmp_path)
    client = fake_client({})
    skill_library.push(client, root=root)
    [(name, files)] = client.api.skills.created
    assert name == "dot" and "local" in files["SKILL.md"]
    assert client.api.skills.labels == ("dot", 1, ["production"])
    assert client.api.skills.tags == ("dot", ["lecture-notes"])

    # An edited Langfuse version is not overwritten without force, and pull brings it home.
    remote = {"SKILL.md": "---\nname: dot\ndescription: d\n---\nedited\n", "examples.md": "e"}
    client = fake_client({"dot": skill_version("dot", remote)})
    skill_library.push(client, root=root)
    assert client.api.skills.created == []
    skill_library.pull(client, root=root)
    assert "edited" in (root / "dot/SKILL.md").read_text()
    assert (root / "dot/examples.md").read_text() == "e"


def test_every_lecture_notes_prompt_has_a_fallback() -> None:
    from app import prompts

    for name in [n for n in prompts.PROMPTS if n.startswith("note-taker/lecture-notes/")]:
        assert prompts.read_fallback(name)
    template = prompts.get_prompt("note-taker/lecture-notes/skills-system")
    for slot in ("{skills_locations}", "{skills_load_warnings}", "{skills_list}"):
        assert slot in template
    text, ref = prompts.get_prompt_ref(
        "note-taker/lecture-notes/request", topic="T", label="L", language="English"
    )
    assert '"T" (L) in English' in text and ref is None


def test_no_tracing_without_langfuse() -> None:
    from app.note_taker.lecture_notes.tracing import link_prompt, traced_run

    with traced_run(
        "x", user_id="u", session_id="s", input="i", metadata={}, tags=[], skills=[]
    ) as trace:
        assert trace.callbacks == [] and trace.trace_id is None
    assert link_prompt(object()) == []


def test_display_math_braces_are_not_attributes() -> None:
    body = "$$\n\\sum_{t=1}^{T} y_t\n= \\alpha_{i=0}\n$$ {#eq-sum}\n\nText {#weird}"
    issues = validate_body(body)
    # Only the prose after the math is checked as attributes.
    assert [i.line for i in issues] == [6]
    assert validate_body("$$\n\\href{x}{y}\n$$")


# Lecture scope (app.plan), which load_lecture and the readings-changed flag rely on


def test_scope_keeps_one_session_and_what_its_excerpts_need(tmp_path: Path) -> None:
    from app.plan import UnknownSession, load_plan, scope_to_session
    from app.syllabus import Transcript

    course(tmp_path)
    plan = load_plan(tmp_path / "1")
    transcript = Transcript.model_validate_json(
        (tmp_path / "1/syllabus/s.pdf.transcript.json").read_text()
    )

    one, syllabus = scope_to_session(plan, transcript, "s1")
    assert [s.id for s in one.sessions] == ["s1"]
    assert [s.label for s in syllabus.sessions] == ["Week 1"]
    assert [p.id for p in one.proposals] == ["p1"]
    assert [b.file for b in one.books] == ["1/reading/book.pdf"]

    two, syllabus = scope_to_session(plan, transcript, "s2")
    assert [s.files for s in two.sessions] == [["1/reading/handout.md"]]
    assert two.proposals == [] and two.books == []

    with pytest.raises(UnknownSession):
        scope_to_session(plan, transcript, "nope")


def test_session_fingerprint_follows_files_and_excerpt_pages(tmp_path: Path) -> None:
    from app.plan import load_plan, session_fingerprint

    course(tmp_path)
    plan = load_plan(tmp_path / "1")
    before = session_fingerprint(plan, "s1")
    other = session_fingerprint(plan, "s2")

    plan.proposals[0].pdf_end = 3
    assert session_fingerprint(plan, "s1") != before
    assert session_fingerprint(plan, "s2") == other

    plan.proposals[0].pdf_end = 2
    plan.sessions[0].files.append("1/reading/extra.md")
    assert session_fingerprint(plan, "s1") != before


# A teacher's edits


def test_execute_edit_renders_the_body_with_the_versions_figures(
    run_env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.note_taker.lecture_notes.readings import load_lecture

    bundle = load_lecture(run_env["uploads"], "1", "s1")
    parent_id, course_id, run_id = uuid4(), uuid4(), uuid4()
    stored = {
        "old/index.qmd": (front_matter(bundle) + "\n\nOld body\n").encode(),
        "old/index.html": page_chrome(bundle, "Kept sign-off")["notes-footer.html"].encode(),
        "old/assets/a.svg": SVG,
        "old/assets/gone.svg": SVG,
    }
    parent = {
        "id": parent_id,
        "course_id": course_id,
        "session_id": "s1",
        "status": "succeeded",
        "s3_prefix": "old/",
        "files": ["index.html", "index.qmd", "assets/a.svg", "assets/gone.svg"],
    }
    monkeypatch.setattr(runs, "load_run", lambda run: parent if run == parent_id else None)
    published: dict[str, list[str]] = {}

    def publisher(build: Path, prefix: str) -> list[str]:
        files = sorted(p.relative_to(build).as_posix() for p in build.rglob("*") if p.is_file())
        published[prefix] = files
        return files

    runner = FakeRunner()
    body = "## Edited\n\n![A figure](assets/a.svg)\n\n![New](assets/b.svg)\n"
    runs.execute_edit(
        run_id,
        parent_id,
        "1",
        body,
        {"assets/b.svg": SVG},
        runner=runner,
        publisher=publisher,
        read=lambda key: stored[key],
    )

    assert run_env["status"] == "succeeded", run_env.get("error")
    prefix = f"courses/{course_id}/lecture-notes/s1/{run_id}/"
    assert list(published) == [prefix] and run_env["s3_prefix"] == prefix
    assert "assets/a.svg" in run_env["files"] and "assets/b.svg" in run_env["files"]
    assert "assets/gone.svg" not in run_env["files"]
    assert "## Edited" in runner.calls[0]


def test_execute_edit_records_what_the_checker_refused(
    run_env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs, "load_run", lambda run: None)
    runs.execute_edit(uuid4(), uuid4(), "1", "Body", {}, runner=FakeRunner())
    assert run_env["status"] == "failed" and "no longer published" in run_env["error"]


def test_edit_assets_keep_only_what_the_body_shows() -> None:
    kept = runs.edit_assets("![x](assets/a.svg)", {"assets/a.svg": b"1", "assets/b.svg": b"2"}, {})
    assert kept == {"assets/a.svg": b"1"}


# The opening hook: validator rules, the scout's web tools, and the scout in a run

WEB_IMAGE = "https://upload.test/loom.png"
HOOK = (
    "::: {.hook}\n"
    "In 1804 a loom read punched cards.\n\n"
    f"![Jacquard's cards. Source: [Commons](https://commons.test/wiki/Loom)]({WEB_IMAGE})\n\n"
    "How can a list of symbols control a machine?\n"
    ":::\n"
)


def test_hook_opens_the_page_once() -> None:
    assert validate_body(HOOK + "\n## Programs {#sec-p}\n\nText.\n") == []
    [late] = validate_body("## A {#sec-a}\n\n" + HOOK)
    assert "before the first ## heading" in late.message
    [twice] = validate_body(HOOK + "\n" + HOOK)
    assert "only one .hook" in twice.message


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        (f"![A loom]({WEB_IMAGE})", "add its source"),
        ("![A. Source: [x](https://a.test)](http://upload.test/a.png)", "use your own"),
        ("![A. Source: [x](https://a.test)](data:image/png;base64,AAAA)", "use your own"),
        ("![A. Source: [x](javascript:alert(1))](https://a.test/a.png)", "only http(s)"),
    ],
)
def test_web_images_need_https_and_a_source_link(body: str, problem: str) -> None:
    issues = validate_body(body)
    assert any(problem in i.message for i in issues), issues


def test_web_images_must_be_checked_in_an_agent_run() -> None:
    assert validate_body(HOOK, web_images={WEB_IMAGE}) == []
    [issue] = validate_body(HOOK, web_images=set())
    assert "call check_image" in issue.message
    many = "\n\n".join(
        f"![P. Source: [s](https://s.test)](https://i.test/{n}.png)" for n in range(7)
    )
    assert any("at most 6 images" in i.message for i in validate_body(many))


def test_images_with_links_in_captions_are_read_in_linear_time() -> None:
    import time

    from app.note_taker.lecture_notes.validate import MAX_LINE_CHARS, images

    text = "x ![a [b](https://c.test) d](https://e.test/f.png){#fig-g} y"
    assert images(text) == [(2, 50, "a [b](https://c.test) d", "https://e.test/f.png")]
    start = time.monotonic()
    for line in ["![[" * (MAX_LINE_CHARS // 3), "![]" * (MAX_LINE_CHARS // 3), "![a](" * 1000]:
        validate_body(line)
    assert time.monotonic() - start < 1


ANIMATED = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="2">'
    b'<animate attributeName="r" values="1;4;1" dur="2s" repeatCount="indefinite"/>'
    b'<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="3s"/>'
    b"</circle></svg>"
)


@pytest.mark.parametrize(
    "svg",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><set attributeName="href" to="#a"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="xlink:href" '
        b'values="#a;#b"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><set attributeName="onclick" to="x"/></svg>',
    ],
)
def test_svg_may_animate_but_not_links_or_handlers(svg: bytes) -> None:
    assert validate_body("![x](assets/a.svg)", {"assets/a.svg": ANIMATED}) == []
    assert validate_body("![x](assets/a.svg)", {"assets/a.svg": svg})


def test_the_hook_skill_svg_examples_are_valid() -> None:
    import re

    from app.note_taker.lecture_notes.validate import svg_issues

    text = (skill_library.SKILLS_DIR / "motivation-hooks/SKILL.md").read_text(encoding="utf-8")
    examples = re.findall(r"^```xml\n(.*?)^```\s*$", text, re.S | re.M)
    assert examples
    for svg in examples:
        assert svg_issues("assets/queue.svg", svg.encode()) == []


def png(width: int = 400, height: int = 300) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "steelblue").save(buffer, "PNG")
    return buffer.getvalue()


HOSTS = {
    "upload.test": ["93.184.216.34"],
    "commons.test": ["93.184.216.35"],
    "inside.test": ["10.0.0.5"],
    "loop.test": ["127.0.0.1"],
}


def web_access(pages: dict[str, Any], **kwargs: Any) -> Any:
    """A fake web: `pages` maps a URL to its bytes, or to (status, headers) for a redirect."""
    import httpx

    from app.note_taker.lecture_notes.web import WebAccess

    def handler(request: httpx.Request) -> httpx.Response:
        page = pages.get(str(request.url))
        if page is None:
            return httpx.Response(404)
        if isinstance(page, tuple):
            return httpx.Response(page[0], headers=page[1])
        kind = "text/html" if page.startswith(b"<html") else "image/png"
        return httpx.Response(200, content=page, headers={"content-type": kind})

    def resolve(host: str) -> list[str]:
        if host not in HOSTS:
            raise OSError("unknown host")
        return HOSTS[host]

    options = {"search": None, "describe": lambda data: "A blue rectangle.", **kwargs}
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return WebAccess(client=client, resolve=resolve, **options)


def web_tools(access: Any) -> tuple[dict[str, Any], Any]:
    from app.note_taker.lecture_notes.tools import RenderState
    from app.note_taker.lecture_notes.web import make_web_tools

    state = RenderState()
    return {t.name: t for t in make_web_tools(state, access)}, state


def test_check_image_records_a_real_image_and_gives_its_markdown() -> None:
    tools, state = web_tools(web_access({WEB_IMAGE: png()}))
    reply = tools["check_image"].invoke(
        {
            "image_url": WEB_IMAGE,
            "source_page": "https://commons.test/wiki/Loom",
            "source_title": "Loom [Commons]",
        }
    )
    assert reply.startswith("OK: PNG 400x300") and "A blue rectangle." in reply
    markdown = reply.splitlines()[-1]
    assert markdown.endswith(f"(https://commons.test/wiki/Loom)]({WEB_IMAGE})")
    assert "Source: [Loom (Commons)]" in markdown
    assert WEB_IMAGE in state.web_images
    filled = markdown.replace("<what it shows and why it matters>", "Cards")
    assert validate_body(filled, web_images=set(state.web_images)) == []
    # Left as it came, the placeholder is refused, so the agent must write a caption.
    assert validate_body(markdown, web_images=set(state.web_images))


@pytest.mark.parametrize(
    ("pages", "url", "problem"),
    [
        ({}, "http://upload.test/a.png", "only https://"),
        ({}, "https://inside.test/a.png", "not a public host"),
        ({}, "https://loop.test/a.png", "not a public host"),
        ({}, "https://upload.test:8443/a.png", "no credentials or ports"),
        (
            {"https://upload.test/r.png": (302, {"location": "https://inside.test/a.png"})},
            "https://upload.test/r.png",
            "not a public host",
        ),
        ({"https://upload.test/a.png": b"<html>not an image</html>"}, "", "cannot identify"),
        ({"https://upload.test/a.png": png(50, 50)}, "", "too small"),
    ],
)
def test_check_image_refuses(pages: dict, url: str, problem: str) -> None:
    tools, state = web_tools(web_access(pages))
    reply = tools["check_image"].invoke(
        {
            "image_url": url or "https://upload.test/a.png",
            "source_page": "https://commons.test/p",
            "source_title": "P",
        }
    )
    assert reply.startswith("Cannot use this image") and problem in reply, reply
    assert state.web_images == {}


def test_check_image_refuses_large_files(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.note_taker.lecture_notes import web

    monkeypatch.setattr(web, "MAX_IMAGE_BYTES", 1000)
    tools, _ = web_tools(web_access({WEB_IMAGE: png(800, 600) + b"x" * 2000}))
    reply = tools["check_image"].invoke(
        {"image_url": WEB_IMAGE, "source_page": "https://commons.test/p", "source_title": "P"}
    )
    assert reply.startswith("Cannot use") and "MB" in reply


def test_page_images_lists_a_pages_images() -> None:
    page = (
        b'<html><head><title>Loom</title><meta property="og:image" content="/og.jpg">'
        b'</head><body><img src="cards.png" alt="Punched cards" width="640" height="480">'
        b'<img src="data:image/png;base64,AAAA"><img src="http://plain.test/x.png"></body></html>'
    )
    tools, _ = web_tools(web_access({"https://commons.test/wiki/Loom": page}))
    reply = tools["page_images"].invoke({"url": "https://commons.test/wiki/Loom"})
    assert "Page: Loom" in reply
    assert "https://commons.test/og.jpg" in reply
    assert "https://commons.test/wiki/cards.png (640x480) alt: 'Punched cards'" in reply
    assert "data:" not in reply and "plain.test" not in reply


def test_web_search_returns_sources_and_is_capped() -> None:
    from app.note_taker.lecture_notes.web import WebLimits

    queries = []

    def search(query: str) -> dict[str, Any]:
        queries.append(query)
        return {
            "answer": "Patented in 1804.",
            "sources": [{"url": "https://h.test/loom", "title": "Loom", "snippet": "1804"}],
        }

    tools, _ = web_tools(web_access({}, search=search, limits=WebLimits(searches=1)))
    reply = tools["web_search"].invoke({"query": "Jacquard loom year"})
    assert "Patented in 1804." in reply and "https://h.test/loom" in reply
    assert tools["web_search"].invoke({"query": "again"}).startswith("Search limit reached")
    assert queries == ["Jacquard loom year"]


def test_openrouter_search_reads_url_citations() -> None:
    import json

    import httpx

    from app.note_taker.lecture_notes.web import openrouter_search

    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        cited = {"type": "url_citation", "url_citation": {"url": "https://h.test", "title": "H"}}
        message = {"content": "In 1804.", "annotations": [cited, cited]}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    search = openrouter_search(
        httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://openrouter.test/api/v1",
        api_key="k",
        model="m",
    )
    found = search("When?")
    assert found["answer"] == "In 1804."
    assert [s["url"] for s in found["sources"]] == ["https://h.test"]
    assert sent[0]["plugins"] == [{"id": "web", "max_results": 5}] and sent[0]["model"] == "m"


def test_read_decision_keeps_known_bounded_fields() -> None:
    from app.note_taker.lecture_notes.motivation import read_decision

    assert read_decision(None) is None and read_decision("not json") is None
    decision = read_decision(
        '{"needed": true, "kind": "historical", "device": "teleport", "reason": "r",'
        ' "sources": [{"url": "https://a.test", "title": "A"}, {"url": "javascript:x"}],'
        ' "extra": 1}'
    )
    assert decision == {
        "needed": True,
        "kind": "historical",
        "reason": "r",
        "sources": [{"url": "https://a.test", "title": "A"}],
    }


NOTE_OK = "\n## Systems {#sec-s}\n\nText [@r1, p. 10].\n"
DECISION = '{"needed": true, "kind": "historical", "device": "web-image", "reason": "r"}'


def scout_script(hook: str, *, check: bool = True) -> list[AIMessage]:
    checked = call(
        "check_image",
        {
            "image_url": WEB_IMAGE,
            "source_page": "https://commons.test/wiki/Loom",
            "source_title": "Commons",
        },
        "s1",
    )
    return [
        call("task", {"subagent_type": "motivation", "description": "Find a hook"}, "m0"),
        # The scout (the same model).
        *([checked] if check else []),
        call("write_file", {"file_path": "/notes/index.qmd", "content": "by the scout"}, "s2"),
        call("write_file", {"file_path": "/notes/motivation.json", "content": DECISION}, "s3"),
        call("write_file", {"file_path": "/notes/motivation.md", "content": hook}, "s4"),
        AIMessage(content="Hook: historical, web image."),
        # The writer again.
        call("write_file", {"file_path": "/notes/index.qmd", "content": hook + NOTE_OK}, "w1"),
        call("render_notes", {}, "w2"),
        AIMessage(content="Report: a hook and 1 section."),
    ]


def test_the_scout_drafts_a_hook_with_a_checked_web_image(tmp_path: Path) -> None:
    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s1")
    model = ScriptedModel(messages=iter(scout_script(HOOK)))
    model.tools_seen, model.prompts = [], []
    runner = FakeRunner()
    built = build_lecture_notes_agent(
        bundle,
        tmp_path / "build",
        model=model,
        runner=runner,
        skills=[SKILL],
        web=web_access({WEB_IMAGE: png()}),
    )

    result = built.agent.invoke(
        {"messages": [("user", built.request)], "files": built.files},
        config={"recursion_limit": 60},
    )

    assert result["messages"][-1].text == "Report: a hook and 1 section."
    assert built.state.good is not None and len(runner.calls) == 1
    assert "::: {.hook}" in runner.calls[0] and WEB_IMAGE in runner.calls[0]
    assert "/notes/motivation.json" in result["files"]
    assert "by the scout" not in str(result["files"]["/notes/index.qmd"]["content"])
    # The scout had the web tools; the writer did not.
    scout_tools = [tools for tools in model.tools_seen if "check_image" in tools]
    writer_tools = [tools for tools in model.tools_seen if "render_notes" in tools]
    assert scout_tools and writer_tools
    assert all("check_image" not in tools for tools in writer_tools)
    assert {"web_search", "page_images"} <= set(scout_tools[0])
    assert built.prompt_versions["note-taker/lecture-notes/motivation"] is None  # fallback


def test_without_a_check_a_web_image_is_refused(tmp_path: Path) -> None:
    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s1")
    result, message = render(bundle, HOOK, {}, FakeRunner(), tmp_path / "b", None, set())
    assert result is None and "call check_image" in message


def test_execute_run_records_the_scouts_decision(run_env: dict) -> None:
    offline_hook = "::: {.hook}\nType 40 random digits.\n:::\n"
    runs.execute_run(
        uuid4(),
        uuid4(),
        "1",
        "s1",
        model=ScriptedModel(messages=iter(scout_script(offline_hook, check=False))),
        runner=FakeRunner(),
        skills=[SKILL],
        publisher=lambda build, prefix: ["index.html"],
    )
    assert run_env["status"] == "succeeded", run_env.get("error")
    assert run_env["motivation"] == {
        "needed": True,
        "kind": "historical",
        "device": "web-image",
        "reason": "r",
    }


# What the lecture page shows as the current step


def test_the_step_follows_the_writer_and_its_subagents(tmp_path: Path) -> None:
    from app.note_taker.lecture_notes.activity import NotesActivity
    from app.note_taker.progress import Progress

    course(tmp_path)
    bundle = load_lecture(tmp_path, "1", "s1")
    steps: list[str | None] = []
    progress = Progress(save=lambda todos, actions, step: steps.append(step))
    script = [
        call("read_file", {"file_path": "/lecture/brief.md"}, "r0"),
        call("read_file", {"file_path": bundle.readings[0].path}, "r1"),
        *writer_script(NOTE),
    ]
    built = build_lecture_notes_agent(
        bundle,
        tmp_path / "build",
        model=ScriptedModel(messages=iter(script)),
        runner=FakeRunner(),
        skills=[SKILL],
        progress=progress,
    )
    built.agent.invoke(
        {"messages": [("user", built.request)], "files": built.files},
        config={"recursion_limit": 60, "callbacks": [NotesActivity(progress)]},
    )

    shown = [s for i, s in enumerate(steps) if s and (i == 0 or steps[i - 1] != s)]
    assert shown[0] == "Reading the lecture brief"
    assert shown[1].startswith("Reading ") and "/" not in shown[1]  # the reading's name
    for expected in ["Writing the notes", "Rendering the notes (1)", "Revising the notes"]:
        assert expected in shown, shown
    assert "Reviewing the notes" in shown and "Working on the notes" in shown
    assert shown.index("Reviewing the notes") < shown.index("Working on the notes")
    # Once started, the step never falls back to nothing (the page's "Reading the lecture").
    first = steps.index("Reading the lecture brief")
    assert all(steps[first:]), steps
    # The writer's todo list is the one shown.
    assert progress.todo_list == [{"content": "Write", "status": "in_progress"}]


def test_a_subagents_todos_do_not_replace_the_writers() -> None:
    from app.note_taker.lecture_notes.activity import NotesActivity
    from app.note_taker.progress import Progress

    progress = Progress()
    activity = NotesActivity(progress)
    todos = {"todos": [{"content": "Plan", "status": "in_progress"}]}
    activity.on_tool_start({"name": "write_todos"}, "", inputs=todos, metadata={})
    activity.on_tool_start(
        {"name": "write_todos"},
        "",
        inputs={"todos": [{"content": "Check", "status": "pending"}]},
        metadata={"lc_agent_name": "reviewer"},
    )
    activity.on_tool_start(
        {"name": "read_file"},
        "",
        inputs={"file_path": "/readings/02-eigen-values.md"},
        metadata={"lc_agent_name": "reviewer"},
    )
    assert progress.todo_list[0]["content"] == "Plan"
    assert progress.step() == "Review: Reading eigen values"


SVG_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200" role="img" font-size="14">'
)


def layout(body: str) -> list[str]:
    from app.note_taker.lecture_notes.validate import svg_issues

    return svg_issues("assets/plot.svg", f"{SVG_HEAD}<title>t</title>{body}</svg>".encode())


def test_a_line_through_a_label_is_reported() -> None:
    issues = layout(
        '<line x1="80" y1="20" x2="80" y2="180" stroke="#333"/>'
        '<text x="92" y="58" text-anchor="middle">patient</text>'
    )
    assert len(issues) == 1
    assert '"patient" at (92, 58) is crossed by a <line>' in issues[0]


def test_a_curve_through_a_label_is_reported() -> None:
    issues = layout(
        '<path d="M 0 150 C 100 20 200 20 300 150" fill="none" stroke="#4a78b5"/>'
        '<text x="120" y="60">daily rhythm</text>'
    )
    assert "is crossed by a <path>" in issues[0]


def test_labels_clear_of_the_drawing_pass() -> None:
    assert (
        layout(
            '<line x1="40" y1="20" x2="40" y2="160" stroke="#333"/>'
            '<line x1="40" y1="160" x2="300" y2="160" stroke="#333"/>'
            '<path d="M 40 150 C 100 20 200 20 300 150" fill="none" stroke="#4a78b5"/>'
            '<text x="40" y="180" text-anchor="middle">0</text>'
            '<text x="310" y="150" fill="#4a78b5">daily rhythm</text>'
            '<rect x="100" y="100" width="120" height="40" fill="none" stroke="#333"/>'
            '<text x="160" y="125" text-anchor="middle">inside a box</text>'
        )
        == []
    )


def test_a_label_with_a_halo_may_sit_on_lines() -> None:
    assert (
        layout(
            '<line x1="80" y1="20" x2="80" y2="180" stroke="#333"/>'
            '<text x="92" y="58" text-anchor="middle" stroke="#fff" stroke-width="4" '
            'paint-order="stroke">peak</text>'
        )
        == []
    )


def test_a_moving_marker_over_a_label_is_reported() -> None:
    smil = layout(
        '<text x="200" y="66">label</text>'
        '<circle cx="20" cy="60" r="6"><animate attributeName="cx" values="20;380" dur="4s" '
        'repeatCount="indefinite"/></circle>'
    )
    css = layout(
        "<style>@keyframes scan { from { transform: translateX(0); } "
        "to { transform: translateX(300px); } } .scanner { animation: scan 6s linear infinite; }"
        "</style>"
        '<text x="200" y="66">label</text>'
        '<g class="scanner"><line x1="40" y1="20" x2="40" y2="180" stroke="#333"/></g>'
    )
    assert "passes over a <circle>" in smil[0]
    assert "passes over a <line>" in css[0]


def test_a_growing_bar_is_checked_frame_by_frame() -> None:
    # y and height move together, so the bar never reaches the label under the axis.
    bar = (
        '<rect x="105" y="158" width="28" height="32">'
        '<animate attributeName="height" values="32;128;32" dur="6s" repeatCount="indefinite"/>'
        '<animate attributeName="y" values="158;62;158" dur="6s" repeatCount="indefinite"/>'
        "</rect>"
    )
    assert layout(bar + '<text x="119" y="214" text-anchor="middle">now</text>') == []
    assert "passes over a <rect>" in layout(bar + '<text x="108" y="70">top</text>')[0]


def test_overlapping_labels_are_reported() -> None:
    issues = layout('<text x="100" y="50">weekly drift</text><text x="110" y="55">forecast</text>')
    assert "overlaps" in issues[0]


def test_rotated_text_is_not_checked() -> None:
    assert (
        layout(
            '<line x1="0" y1="100" x2="400" y2="100" stroke="#333"/>'
            '<text x="20" y="100" transform="rotate(-90 20 100)">calls</text>'
        )
        == []
    )
