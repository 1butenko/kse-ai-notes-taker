"""Renderer contract tests with real subprocesses and no model requests."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

from app.worker.openrouter import OpenRouterClient
from app.worker.quarto import render_document


def fake_cli(tmp_path: Path, body: str) -> str:
    executable = tmp_path / "fake-quarto"
    executable.write_text(f"#!{sys.executable}\n" + body)
    executable.chmod(0o755)
    return str(executable)


def sources(tmp_path: Path) -> dict:
    paths = {}
    for target in ("html", "pdf"):
        path = tmp_path / f"{target}.qmd"
        path.write_text("# Notes\n\nA vector space.")
        paths[target] = path
    return paths


def test_render_html_and_pdf_without_llm(tmp_path, monkeypatch):
    llm = AsyncMock(side_effect=AssertionError("Rendering must not call a model"))
    monkeypatch.setattr(OpenRouterClient, "complete_json", llm)
    quarto = fake_cli(
        tmp_path,
        """
import json, pathlib, sys
args = sys.argv[1:]
assert "--no-execute" in args
fmt = args[args.index("--to") + 1]
source = pathlib.Path(args[1])
out = pathlib.Path(args[args.index("--output") + 1])
assert out.suffix == (".pdf" if fmt == "typst" else ".html")
out.write_text("rendered " + source.read_text())
print(json.dumps({"args": args, "cwd": str(pathlib.Path.cwd())}))
""",
    )
    output = tmp_path / "artifacts"
    result = asyncio.run(render_document(sources(tmp_path), output, 0, quarto))
    assert {a.format for a in result if a.status == "ready"} == {"html", "pdf"}
    assert all(a.revision == 0 and a.error is None for a in result)
    assert all(not Path(a.path).is_absolute() and (output / a.path).is_file() for a in result)
    assert llm.call_count == 0
    logs = [json.loads((output / f"quarto-{fmt}.log").read_text()) for fmt in ("html", "pdf")]
    assert logs[0]["cwd"] != logs[1]["cwd"]


def test_renderer_timeout_kills_and_reaps_process(tmp_path, monkeypatch):
    import os
    import signal

    import pytest

    from app.worker import quarto as runner

    monkeypatch.setattr(runner, "QUARTO_TIMEOUT", 1)
    pid_file = tmp_path / "pid"
    quarto = fake_cli(
        tmp_path,
        f"""
import os, pathlib, time
pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))
print("started slow renderer", flush=True)
time.sleep(30)
""",
    )
    try:
        result = asyncio.run(
            render_document({"html": sources(tmp_path)["html"]}, tmp_path, 2, quarto)
        )
        assert result[0].status == "failed"
        assert "longer than" in result[0].error
        pid = int(pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        with pytest.raises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        assert "started slow renderer" in (tmp_path / "quarto-html.log").read_text()
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_failed_html_keeps_successful_pdf(tmp_path):
    quarto = fake_cli(
        tmp_path,
        """
import pathlib, sys
args = sys.argv[1:]
out = pathlib.Path(args[args.index("--output") + 1])
out.write_text("partial" if out.suffix == ".html" else "new PDF")
if out.suffix == ".html":
    print("HTML failed")
    sys.exit(1)
""",
    )
    output = tmp_path / "artifacts"
    output.mkdir()
    (output / "html.html").write_text("previous HTML")
    qmds = sources(tmp_path)
    before = {key: p.read_bytes() for key, p in qmds.items()}
    result = asyncio.run(render_document(qmds, output, 3, quarto))
    assert [(a.format, a.status) for a in result] == [("html", "failed"), ("pdf", "ready")]
    assert "HTML failed" in result[0].error
    assert (output / "html.html").read_text() == "previous HTML"
    assert (output / "pdf.pdf").read_text() == "new PDF"
    assert {key: p.read_bytes() for key, p in qmds.items()} == before


def document(content=r"$(a)^T x$", language="uk"):
    from app.notes import NotesDocument

    return NotesDocument.model_validate(
        {
            "schema_version": 2,
            "language": language,
            "course": "1",
            "run": "run",
            "title": "Лінійна алгебра",
            "created_at": "2026-10-22",
            "sources": [],
            "notation": [],
            "terminology": [],
            "models": {},
            "sections": [
                {
                    "title": "Матриці",
                    "topics": [
                        {
                            "topic_id": "T1",
                            "title": "Означення",
                            "status": "verified",
                            "rounds": 1,
                            "verifier": None,
                            "open_issues": [],
                            "evidence": [],
                            "blocks": [
                                {
                                    "id": "T1.1",
                                    "kind": "definition",
                                    "title": None,
                                    "content": content,
                                    "citations": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def test_each_target_preserves_its_math_and_saved_language():
    from app.worker.render import to_quarto, topic_to_quarto

    notes = document()
    section = notes.sections[0]
    for render in (
        lambda target: to_quarto(notes, "en", target),
        lambda target: topic_to_quarto(notes, section, section.topics[0], "en", target),
    ):
        html = render("html")
        pdf = render("pdf")
        word = render("docx")
        assert r"$(a)^T x$" in html and r"$(a)^T x$" in word
        assert r"$(a)^{T}{} x$" in pdf
        assert "  html:" in html and "html-math-method: mathjax" in html
        assert "  typst:" in pdf and "  docx:" in word
        assert all('lang: "uk"' in qmd for qmd in (html, pdf, word))
        assert "Означення" in html


def test_unsafe_markdown_is_rejected_before_cli_and_content_is_retained(tmp_path):
    import pytest

    from app.worker.quarto import QuartoError
    from app.worker.render import to_quarto

    attacks = [
        "{{< include /etc/passwd >}}",
        "{{< embed https://example.invalid/a.qmd >}}",
        '```{python}\nprint("run")\n```',
        '```{=typst}\n#read("/etc/passwd")\n```',
        '`#read("/etc/passwd")`{=typst}',
        "<script>alert(1)</script>",
        '<img src="file:///etc/passwd">',
        r"\input{/etc/passwd}",
        "![read](file:///etc/passwd)",
        "![read][x]\n\n[x]: /etc/passwd",
        "---\nfilters: [/tmp/evil.lua]\n---",
        "[click](javascript:alert%281%29)",
        r"$\href{javascript:alert(1)}{x}$",
        '::: {include="/etc/passwd"}\ncontent\n:::',
    ]
    for attack in attacks:
        notes = document(attack)
        before = notes.model_dump_json()
        with pytest.raises(QuartoError, match="Unsafe"):
            to_quarto(notes, "uk", "html")
        assert notes.model_dump_json() == before

    marker = tmp_path / "executed"
    executable = fake_cli(tmp_path, f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    qmd = tmp_path / "notes.qmd"
    qmd.write_text("---\nfilters: [/tmp/evil.lua]\n---\nText")
    result = asyncio.run(render_document({"html": qmd}, tmp_path / "out", 0, executable))
    assert result[0].status == "failed" and "Unsafe" in result[0].error
    assert not marker.exists()


def test_displayed_code_and_math_are_supported_without_executing():
    from app.worker.render import to_quarto

    content = """An inequality $a<b$.

```python
print("<script>displayed code</script>")
```

$\\begin{pmatrix}1 & 2 \\\\ 3 & 4\\end{pmatrix}$
"""
    rendered = to_quarto(document(content), "uk", "html")
    assert content in rendered
    assert ":::: {.callout-note}" in rendered


def test_generation_retains_unsafe_text_and_manifest(mock_openrouter, tmp_uploads):
    from app.worker.config import WorkerSettings, get_worker_settings
    from app.worker.main import app as worker_app
    from tests.test_notes import course, model_stub

    course(tmp_uploads)
    stub, _ = model_stub()
    worker_app.dependency_overrides[get_worker_settings] = lambda: WorkerSettings(
        uploads_dir=tmp_uploads, quarto_bin="not-installed-quarto"
    )

    def unsafe(request):
        response = stub(request)
        payload = response.json()
        content = json.loads(payload["choices"][0]["message"]["content"])
        if "blocks" in content:
            content["blocks"][0]["content"] = "{{< include /etc/passwd >}}"
        payload["choices"][0]["message"]["content"] = json.dumps(content)
        import httpx2

        return httpx2.Response(200, json=payload)

    result = mock_openrouter(unsafe).post("/plans/1/notes").json()
    assert result["run"]["status"] == "done"
    assert result["document"]["sections"][0]["topics"][0]["blocks"][0]["content"] == (
        "{{< include /etc/passwd >}}"
    )
    root = tmp_uploads / "1/notes" / result["run"]["id"]
    assert "{{< include /etc/passwd >}}" in (root / "notes.json").read_text()
    manifest = json.loads((root / "artifacts.json").read_text())
    assert len(manifest) == 6
    assert all(a["status"] == "failed" and "Unsafe" in a["error"] for a in manifest)


def test_actual_quarto_html_pdf_and_docx(tmp_path):
    """Opt in with QUARTO_TEST_BIN; runs the exact production subprocess boundary."""
    import os
    import zipfile

    import pytest
    from pypdf import PdfReader

    from app.worker.render import to_quarto

    binary = os.environ.get("QUARTO_TEST_BIN")
    if not binary:
        pytest.skip("Set QUARTO_TEST_BIN to exercise an installed Quarto")
    content = r"""Нехай $A \in \mathbb{R}^{2\times 2}$.

$$A = \begin{pmatrix}1 & 2 \\ 3 & 4\end{pmatrix}.$$

An inequality $a<b$ and $(a)^T x$.

```python
print("<script>displayed code</script>")
```
"""
    # A nearby project must not inject a filter/resource into the staging project.
    (tmp_path / "_quarto.yml").write_text("filters: [/no-such-user-filter.lua]\n")
    paths = {}
    for target in ("html", "pdf", "docx"):
        folder = tmp_path / "sources" / target
        folder.mkdir(parents=True)
        paths[target] = folder / "notes.qmd"
        paths[target].write_text(to_quarto(document(content), "uk", target))
    output = tmp_path / "output"
    result = asyncio.run(render_document(paths, output, 0, binary))
    assert all(a.status == "ready" for a in result), [a.model_dump() for a in result]
    html = (output / "notes.html").read_text()
    assert "Лінійна алгебра" in html and 'lang="uk"' in html
    assert 'id="toc-title">Зміст' in html
    assert "MathJax" in html and r"(a)^T x" in html
    assert "&lt;script&gt;" in html
    assert "<script>displayed code</script>" not in html
    assert "Матриці" in " ".join(
        page.extract_text() for page in PdfReader(output / "notes.pdf").pages
    )
    with zipfile.ZipFile(output / "notes.docx") as archive:
        assert "Лінійна алгебра" in archive.read("word/document.xml").decode()


def test_resource_reads_cannot_hide_behind_markdown_fence_context():
    import pytest

    from app.worker.quarto import QuartoError
    from app.worker.render import to_quarto

    for attack in (
        "    ```python\n![secret](/etc/passwd)",
        "> ```python\n> displayed\n\n![secret](/etc/passwd)",
        "> ```python\n> displayed\n\n```{python}\nprint(1)\n```",
    ):
        with pytest.raises(QuartoError, match="Unsafe"):
            to_quarto(document(attack), "uk", "html")


def test_ordinary_prose_can_name_data_and_files():
    from app.worker.render import to_quarto

    content = "Data: a vector. Source file: lecture.pdf."
    assert content in to_quarto(document(content), "en", "html")
