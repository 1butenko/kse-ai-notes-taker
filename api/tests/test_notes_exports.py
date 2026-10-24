"""Word export of a selected notes revision: on demand, model-free, never touching HTML/PDF."""

import asyncio
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.notes_revisions import RevisionStore
from app.worker.openrouter import OpenRouterClient
from app.worker.render import to_quarto
from tests.test_notes_rendering import fake_cli
from tests.test_notes_revisions import client as shared_client
from tests.test_notes_revisions import model_calls as shared_model_calls
from tests.test_notes_revisions import patch_for, url
from tests.test_notes_revisions import saved_run as shared_saved_run

saved_run, client, model_calls = shared_saved_run, shared_client, shared_model_calls

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FORMULA = "$(a)^T x$"

CLI = """
import json, sys, zipfile
from pathlib import Path

args = sys.argv[1:]
source = Path(args[1]).read_text()
output = Path(args[args.index('--output') + 1])
target = args[args.index('--to') + 1]
here = Path(__file__).parent
with (here / 'calls.jsonl').open('a') as log:
    log.write(json.dumps({'to': target, 'no_execute': '--no-execute' in args}) + '\\n')
if target == 'docx':
    if (here / 'fail-docx').exists():
        print('Pandoc could not write the document')
        sys.exit(7)
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', source)
else:
    output.write_text(('%PDF-' if output.suffix == '.pdf' else '<html>') + source)
"""


@pytest.fixture
def word_cli(tmp_path, tmp_uploads):
    from app.worker.config import WorkerSettings, get_worker_settings
    from app.worker.main import app as worker_app

    cli = Path(fake_cli(tmp_path, CLI))
    settings = WorkerSettings(uploads_dir=tmp_uploads, quarto_bin=str(cli))
    worker_app.dependency_overrides[get_worker_settings] = lambda: settings
    return cli


def calls(cli: Path) -> list[dict]:
    log = cli.parent / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def word_source(response) -> str:
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return archive.read("word/document.xml").decode()


def render(client, revision: int, formats: list[str]) -> dict:
    queued = client.post(url(f"/revisions/{revision}/render"), json={"formats": formats})
    assert queued.status_code == 202, queued.text
    return client.get(url(f"/render-jobs/{queued.json()['id']}")).json()


def test_docx_export_uses_requested_revision(saved_run, client, model_calls, word_cli):
    directory, document = saved_run
    older = client.patch(url("/topics/T1"), json=patch_for(document, f"Older text {FORMULA}"))
    assert older.status_code == 200, older.text
    newer = client.patch(url("/topics/T1"), json=patch_for(document, "Newest text", base=1))
    assert newer.status_code == 200, newer.text
    assert RevisionStore(directory).current().info.revision == 2
    before = len(calls(word_cli))

    job = render(client, 1, ["docx"])

    assert (job["revision"], job["formats"], job["status"]) == (1, ["docx"], "done"), job
    # Quarto ran once per document (full notes, T1, T2), for Word only and without execution.
    word_calls = calls(word_cli)[before:]
    assert word_calls == [{"to": "docx", "no_execute": True}] * 3

    full = client.get(url("/revisions/1/artifacts/docx"))
    assert full.status_code == 200
    assert full.headers["content-type"] == DOCX
    assert full.headers["x-notes-revision"] == "1"
    assert full.headers["content-disposition"].startswith("attachment")
    source = word_source(full)
    assert "Older text" in source and "Newest text" not in source
    # Typst-specific math rewriting belongs to the PDF only.
    assert FORMULA in source and "$(a)^{T}" not in source
    assert "docx:" in source and "typst:" not in source

    topic = client.get(url("/revisions/1/topics/T1/artifacts/docx"))
    assert topic.status_code == 200 and topic.headers["content-type"] == DOCX
    assert "Older text" in word_source(topic) and "Newest text" not in word_source(topic)
    assert client.get(url("/revisions/1/topics/T2/artifacts/docx")).status_code == 200
    # Only the requested revision has a Word file; nothing aliases onto another revision.
    assert client.get(url("/revisions/2/artifacts/docx")).status_code == 404
    assert client.get(url("/revisions/0/artifacts/docx")).status_code == 404

    view = client.get(url()).json()
    docx = [a for a in view["artifacts"] if a["format"] == "docx"]
    assert {(a["topic_id"], a["revision"]) for a in docx} == {(None, 1), ("T1", 1), ("T2", 1)}
    assert view["current_revision"] == 2
    assert model_calls == []


def test_docx_export_has_no_model_calls(saved_run, client, model_calls, word_cli, monkeypatch):
    from app.worker.config import get_worker_settings
    from app.worker.main import app as worker_app
    from app.worker.revisions import enqueue_render, render_revision

    llm = AsyncMock(side_effect=AssertionError("Word export must not call a model"))
    monkeypatch.setattr(OpenRouterClient, "complete_json", llm)
    directory, document = saved_run
    settings = worker_app.dependency_overrides[get_worker_settings]()

    # An unedited original and an edited revision both export without a model.
    for revision in (0, 1):
        if revision:
            client.patch(url("/topics/T1"), json=patch_for(document))
        job = asyncio.run(
            render_revision(directory, enqueue_render(directory, revision, ["docx"]).id, settings)
        )
        assert job.status == "done" and job.errors == [], job
        assert client.get(url(f"/revisions/{revision}/artifacts/docx")).status_code == 200

    assert render(client, 1, ["docx"])["status"] == "done"
    llm.assert_not_called()
    assert model_calls == []


def test_failed_docx_keeps_html_and_pdf(saved_run, client, model_calls, word_cli):
    from app.notes_artifacts import artifact_path

    directory, document = saved_run
    client.patch(url("/topics/T1"), json=patch_for(document))
    ready = {kind: (artifact_path(directory, 1, kind, None),) for kind in ("html", "pdf")}
    bytes_before = {kind: path.read_bytes() for kind, (path,) in ready.items()}
    manifest_before = [
        a for a in client.get(url()).json()["artifacts"] if a["format"] in ("html", "pdf")
    ]
    assert len(manifest_before) == 6

    (word_cli.parent / "fail-docx").write_text("")
    job = render(client, 1, ["docx"])

    assert job["status"] == "failed"
    assert len(job["errors"]) == 3 and all("docx" in error for error in job["errors"]), job
    assert client.get(url("/revisions/1/artifacts/docx")).status_code == 404
    view = client.get(url()).json()
    assert [a for a in view["artifacts"] if a["format"] in ("html", "pdf")] == manifest_before
    assert not [a for a in view["artifacts"] if a["format"] == "docx"]
    for kind, (path,) in ready.items():
        assert artifact_path(directory, 1, kind, None) == path
        assert path.read_bytes() == bytes_before[kind]
        assert client.get(url(f"/revisions/1/artifacts/{kind}")).status_code == 200
    assert view["current_revision"] == 1

    # Retrying after the fault is fixed publishes the Word files next to the HTML/PDF.
    (word_cli.parent / "fail-docx").unlink()
    assert render(client, 1, ["docx"])["status"] == "done"
    final = client.get(url()).json()["artifacts"]
    assert len(final) == 9 and client.get(url("/revisions/1/artifacts/docx")).status_code == 200
    assert model_calls == []


def test_word_contents_is_a_static_list_linked_to_stable_ids(saved_run):
    _, document = saved_run
    second = document.sections[0].topics[0].model_copy(deep=True)
    second.topic_id, second.blocks[0].id = "T3", "T3.1"
    document.sections.append(document.sections[0].model_copy(update={"title": "Власні числа"}))
    document.sections[1].topics = [second]

    word = to_quarto(document, "en", "docx")
    contents = word.split("# Table of contents {.unnumbered}\n", 1)[1].split("\n# ", 1)[0]

    # Word's own TOC field is an empty heading in viewers that do not refresh fields.
    assert "    toc: false" in word and "    number-sections: true" in word
    assert contents.strip().splitlines() == [
        "- [1. Матриці](#section-1)",
        "  - [1.1 Означення](#sec-T1)",
        "  - [1.2 Означення](#sec-T2)",
        "- [2. Власні числа](#section-2)",
        "  - [2.1 Означення](#sec-T3)",
    ]
    assert "# Матриці {#section-1}" in word and "# Власні числа {#section-2}" in word
    # The printed and browser outputs keep their native contents and their own markup.
    for target in ("html", "pdf"):
        other = to_quarto(document, "en", target)
        assert "    toc: true" in other and "](#section-1)" not in other
    # A topic export is a single chapter: no contents list.
    topic = document.sections[0].topics[0]
    from app.worker.render import topic_to_quarto

    assert "](#sec-" not in topic_to_quarto(document, document.sections[0], topic, "en", "docx")


def test_word_contents_escapes_titles_and_skips_empty_documents(saved_run):
    _, document = saved_run
    document.sections[0].title = "Set [A] and $x^2$"
    word = to_quarto(document, "en", "docx")
    assert "- [1. Set \\[A\\] and $x^2$](#section-1)" in word
    document.sections = []
    assert "Table of contents {.unnumbered}" not in to_quarto(document, "en", "docx")


def test_word_polish_spaces_equation_numbers_and_keeps_callout_titles(tmp_path):
    from app.worker.docx import polish_docx

    gap = chr(0x2001) * 2
    math = (
        "<m:oMathPara><m:oMath><m:r><m:t>x</m:t></m:r><m:r><m:t>.</m:t></m:r>"
        f"<m:r><m:t>{gap}</m:t></m:r><m:r><m:t>(</m:t></m:r><m:r><m:t>1</m:t></m:r>"
        "<m:r><m:t>)</m:t></m:r></m:oMath></m:oMathPara>"
    )
    plain = f"<w:p><w:r><w:t>{gap}</w:t></w:r></w:p>"  # Ordinary text keeps its spaces.
    title = (
        '<w:p><w:pPr><w:pStyle w:val="BodyText" /></w:pPr><w:pPr>\n'
        '    <w:spacing w:before="0" w:after="0" />\n'
        '    <w:textAlignment w:val="center"/>\n    </w:pPr><w:r><w:t>Definition</w:t></w:r></w:p>'
    )
    body = '<w:p><w:pPr><w:pStyle w:val="BodyText" /></w:pPr><w:r><w:t>Text</w:t></w:r></w:p>'
    path = tmp_path / "notes.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml", f"<w:document>{math}{plain}{title}{body}</w:document>"
        )
        archive.writestr("word/media/image1.png", b"png")

    polish_docx(path)

    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert archive.read("word/media/image1.png") == b"png"
        text = archive.read("word/document.xml").decode()
    # LibreOffice's formula engine drops spaces in math runs; normal-text runs keep them.
    assert f'<m:r><m:rPr><m:nor/></m:rPr><m:t xml:space="preserve">{gap}</m:t></m:r>' in text
    assert text.count("<m:oMath>") == 1 and "<m:t>x</m:t>" in text
    assert plain in text
    # Only the callout title row keeps with its body row.
    assert text.count("<w:keepNext/>") == 1
    assert '<w:pStyle w:val="BodyText" /><w:keepNext/></w:pPr>' in text
    assert body in text
    assert not list(tmp_path.glob(".*.tmp"))


def test_word_polish_rejects_a_file_that_is_not_a_word_package(tmp_path):
    import pytest

    from app.worker.docx import polish_docx

    broken = tmp_path / "notes.docx"
    broken.write_text("<html>")
    with pytest.raises(zipfile.BadZipFile):
        polish_docx(broken)
    assert broken.read_text() == "<html>" and not list(tmp_path.glob(".*.tmp"))


def test_word_polish_groups_parenthesized_superscript_bases(tmp_path):
    """Pandoc makes only ')' the base; LibreOffice renders both formulas as ¿."""
    from xml.dom.minidom import parseString

    from app.worker.docx import polish_docx

    def run(value: str) -> str:
        return f"<m:r><m:t>{value}</m:t></m:r>"

    def sup(power: str) -> str:
        return f"<m:sSup><m:e>{run(')')}</m:e><m:sup>{run(power)}</m:sup></m:sSup>"

    math = (
        f"<m:oMath>{run('(')}{run('2')}{run('−')}{run('λ')}{sup('2')}"
        f"{run('+')}{run('(')}{run('1')}{run(',')}{run('1')}{sup('T')}"
        f"{run('+')}{run('(')}{run('a')}{run('(')}{run('b')}{run(')')}{sup('3')}"
        f"{run('+')}{run('x')}{sup('4')}"
        f"{run('+')}<m:sSub><m:e>{run('x')}</m:e><m:sub>{run('1')}</m:sub></m:sSub>{sup('5')}"
        f"<m:sSup><m:e>{run('(')}{run('q')}{run(')')}</m:e><m:sup>{run('6')}</m:sup></m:sSup>"
        "</m:oMath>"
    )
    path = tmp_path / "notes.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
            f"{math}</w:document>",
        )

    polish_docx(path)

    with zipfile.ZipFile(path) as archive:
        root = parseString(archive.read("word/document.xml"))
    superscripts = root.getElementsByTagName("m:sSup")
    bases = [sup.getElementsByTagName("m:e")[0] for sup in superscripts]
    assert [
        "".join(t.firstChild.nodeValue for t in base.getElementsByTagName("m:t")) for base in bases
    ] == ["(2−λ)", "(1,1)", "(a(b))", ")", ")", "(q)"]
    assert len(superscripts) == 6
