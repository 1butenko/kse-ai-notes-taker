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
    stage_and_render,
    warning_lines,
)
from app.note_taker.lecture_notes.readings import (
    LectureNotFound,
    brief_markdown,
    load_lecture,
    seed_files,
)
from app.note_taker.lecture_notes.tools import RunCancelled
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


def test_skill_examples_pass_the_validator() -> None:
    """The skills teach only what render_notes accepts."""
    import re

    assets = {f"assets/{n}.svg": SVG for n in ["projection", "picture", "before", "after"]}
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
        "assets/dot.svg",
        "index_files/libs/quarto.js",
    }


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
    record: dict[str, Any] = {"progress": []}
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
    assert len(skills) == 10
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

    with traced_run("x", session_id="s", input="i", metadata={}, tags=[], skills=[]) as trace:
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
