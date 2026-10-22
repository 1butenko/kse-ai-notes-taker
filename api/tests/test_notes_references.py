"""Stable references, source provenance and controlled note image resources."""

import pytest

from app.notes import EvidenceItem, Source
from app.worker.references import build_reference_data, reference_id, validate_references
from app.worker.render import to_quarto, topic_to_quarto
from tests.test_notes_rendering import document


def cited_document():
    notes = document("See the evidence.", language="en")
    notes.sources = [
        Source(
            id=1,
            file="private.pdf",
            title="Known textbook",
            label=None,
            pdf_start=90,
            pdf_end=100,
            sessions=[],
            outline=[],
            chunk_ids=["c1"],
        )
    ]
    note = notes.sections[0].topics[0]
    note.evidence = [
        EvidenceItem(
            chunk_id="c1",
            source=1,
            title="Known textbook",
            page="p. 10",
            role="definition",
            relevance=5,
            reason="Evidence",
            text="Private",
        )
    ]
    note.blocks[0].citations = ["c1"]
    return notes


def test_citation_preserves_source_and_printed_page():
    notes = cited_document()
    result = to_quarto(notes, "en", "html")
    assert "[@src-1, p. 10]" in result
    assert "PDF p." not in result and "Private" not in result
    assert build_reference_data(notes) == [
        {"id": "src-1", "type": "document", "title": "Known textbook"}
    ]


def test_reference_ids_survive_title_edit():
    notes = cited_document()
    note = notes.sections[0].topics[0]
    before_id = reference_id(note.topic_id)
    note.title = "A corrected title"
    after_id = reference_id(note.topic_id)
    assert before_id == after_id
    assert f"{{#{after_id}}}" in to_quarto(notes, "en", "html")


def test_unknown_citation_is_reported():
    notes = cited_document()
    notes.sections[0].topics[0].blocks[0].content += " Unknown [@src-999]."
    assert any("src-999" in issue for issue in validate_references(notes))


def test_standalone_topic_links_external_topic_explicitly():
    notes = cited_document()
    section = notes.sections[0]
    other = section.topics[0].model_copy(deep=True)
    other.topic_id = "T2"
    other.blocks[0].id = "T2.1"
    other.blocks[0].content = "$$x = 1$$ {#eq-other}"
    section.topics.append(other)
    section.topics[0].blocks[0].content = f"See @{reference_id('T2')} and @eq-other."
    for target in ("html", "pdf", "docx"):
        source = topic_to_quarto(notes, section, section.topics[0], "en", target)
        assert "/plans/1/notes/run/html#eq-other" in source
        assert f"/plans/1/notes/run/html#{reference_id('T2')}" in source
        assert "@eq-other" not in source
        assert "@eq-other" in to_quarto(notes, "en", target)


def image_bytes(kind="PNG", size=(64, 40)):
    import io

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", size, "#27779e").save(output, format=kind)
    return output.getvalue()


def asset_run(tmp_uploads):
    from app.notes import NotesRun

    run = "20261022-120000-abcd"
    root = tmp_uploads / "1/notes" / run
    root.mkdir(parents=True)
    metadata = NotesRun(
        id=run,
        course="1",
        status="done",
        stage="done",
        created_at="2026-10-22",
        updated_at="2026-10-22",
        models={},
    )
    (root / "run.json").write_text(metadata.model_dump_json())
    (root / "notes.json").write_text(cited_document().model_dump_json())
    return root, f"/plans/1/notes/{run}"


def test_png_jpeg_uploads_are_immutable_and_do_not_change_notes(tmp_uploads):
    import hashlib
    import io

    from fastapi.testclient import TestClient
    from PIL import Image

    from app.main import app

    root, base = asset_run(tmp_uploads)
    before = (root / "notes.json").read_bytes()
    client = TestClient(app)
    for kind, media in (("PNG", "image/png"), ("JPEG", "image/jpeg")):
        response = client.post(base + "/assets", files={"file": ("plot", image_bytes(kind), media)})
        assert response.status_code == 201, response.text
        payload = response.json()
        asset = payload["asset"]
        assert payload["markdown_path"] == asset["path"]
        assert asset["media_type"] == media and (asset["width"], asset["height"]) == (64, 40)
        download = client.get(base + "/assets/" + asset["id"])
        assert download.status_code == 200
        assert download.headers["content-type"] == media
        assert hashlib.sha256(download.content).hexdigest() == asset["sha256"]
        assert Image.open(io.BytesIO(download.content)).format == kind
        binary = root / asset["path"]
        stamp = binary.stat().st_mtime_ns
        repeated = client.post(base + "/assets", files={"file": ("new-name", image_bytes(kind))})
        assert repeated.json() == payload
        assert binary.stat().st_mtime_ns == stamp
    assert (root / "notes.json").read_bytes() == before
    assert len(list((root / "assets").glob("*.json"))) == 2
    assert client.get(base + "/assets/" + "0" * 64).status_code == 404
    assert client.get(base + "/assets/..%2Fnotes.json").status_code == 404


def test_invalid_and_oversized_image_uploads(tmp_uploads):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.note_assets import MAX_UPLOAD_BYTES

    root, base = asset_run(tmp_uploads)
    client = TestClient(app)
    for data in (
        b"<svg/>",
        b"not image",
        image_bytes("GIF"),
        image_bytes()[:50],
        image_bytes("JPEG")[:-20],
        image_bytes(size=(5000, 4001)),
    ):
        response = client.post(base + "/assets", files={"file": ("bad.png", data, "image/png")})
        assert response.status_code == 422, response.text
    response = client.post(
        base + "/assets", files={"file": ("large.png", b"x" * (MAX_UPLOAD_BYTES + 1))}
    )
    assert response.status_code == 413
    assert not list(root.glob("assets/*"))


def test_asset_path_and_digest_are_checked(tmp_path):
    from app.note_assets import asset_resources, import_asset, load_asset

    asset = import_asset(tmp_path, image_bytes(), "diagram.png")
    markdown = f"![Diagram]({asset.path}){{#fig-diagram}}"
    assert asset_resources(tmp_path, [asset], markdown) == {asset.path: tmp_path / asset.path}
    with pytest.raises(ValueError, match="Unregistered"):
        asset_resources(tmp_path, [], markdown)
    altered = asset.model_copy(update={"path": "../secret.png"})
    with pytest.raises(ValueError):
        asset_resources(tmp_path, [altered], "![Secret](../secret.png){#fig-secret}")
    binary = tmp_path / asset.path
    binary.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="corrupted"):
        load_asset(tmp_path, asset.id)
    with pytest.raises(ValueError, match="immutable"):
        import_asset(tmp_path, image_bytes(), "diagram.png")


def test_asset_symlink_escape_is_rejected(tmp_path):
    from app.note_assets import import_asset, load_asset

    root = tmp_path / "run"
    root.mkdir()
    asset = import_asset(root, image_bytes(), "plot.png")
    image = root / asset.path
    outside = tmp_path / "outside.png"
    outside.write_bytes(image.read_bytes())
    image.unlink()
    image.symlink_to(outside)
    with pytest.raises(ValueError, match="root"):
        load_asset(root, asset.id)


@pytest.mark.parametrize(
    "content",
    [
        "$$x=1$$ {#eq-one}\n\n$$y=1$$ {#eq-one}",
        "$$x=1$$ {#bad-label}",
        "Text {#eq-text}",
        "Caption {#fig-missing}",
        "See @fig-missing.",
        "See @tbl-missing.",
        ": An orphan caption {#tbl-orphan}",
        "See @eq-missing.",
        "![Remote](https://example.org/figure.png){#fig-remote}",
        "![Missing](assets/" + "0" * 64 + ".png){#fig-missing}",
    ],
)
def test_invalid_references_stop_preparation(content):
    from app.worker.quarto import QuartoError

    notes = document(content)
    before = notes.model_dump_json()
    assert validate_references(notes)
    with pytest.raises(QuartoError):
        to_quarto(notes, "en", "html")
    assert notes.model_dump_json() == before


def test_unknown_evidence_citation_is_reported():
    notes = cited_document()
    notes.sections[0].topics[0].blocks[0].citations.append("missing-chunk")
    assert any("missing-chunk" in issue for issue in validate_references(notes))


def test_configured_public_url_and_encoded_components():
    from app.config import Settings
    from app.worker.config import WorkerSettings
    from app.worker.references import ReferenceContext

    for model in (Settings, WorkerSettings):
        for url in (
            "ftp://host",
            "https://user:password@host",
            "https://@host",
            "https://host?q=1",
            "https://host/#x",
        ):
            with pytest.raises(ValueError):
                model(public_api_url=url)
        assert (
            model(public_api_url="https://notes.example/api/").public_api_url
            == "https://notes.example/api"
        )
    notes = cited_document()
    notes.course = "course/name"
    notes.run = "a b"
    context = ReferenceContext(public_api_url="https://notes.example/api/")
    assert (
        context.document_url(notes)
        == "https://notes.example/api/plans/course%2Fname/notes/a%20b/html"
    )


def figure_document(tmp_path):
    from app.note_assets import import_asset
    from app.notes import NoteBlock

    notes = cited_document()
    asset = import_asset(tmp_path, image_bytes(), "diagram.png")
    notes.assets = [asset]
    notes.title = "Reference verification"
    section = notes.sections[0]
    section.title = "Foundations"
    note = section.topics[0]
    note.title = "First topic"
    note.blocks[0].kind = "explanation"
    note.blocks[0].content = (
        "See @eq-energy, @fig-diagram and @tbl-values. See Topic T2.\n\n"
        "$$E = m c^2$$ {#eq-energy}\n\n"
        f"![Measured diagram]({asset.path}){{#fig-diagram}}\n\n"
        "| Symbol | Value |\n|---|---|\n| x | 1 |\n\n: Measured values {#tbl-values}\n"
    )
    other = note.model_copy(deep=True)
    other.topic_id = "T2"
    other.title = "Second topic"
    other.blocks = [
        NoteBlock(
            id="T2.1",
            kind="explanation",
            title=None,
            content="See @eq-energy and @fig-diagram.\n\n$$y = 2$$ {#eq-second}",
            citations=[],
        )
    ]
    section.topics.append(other)
    return notes


def test_only_referenced_assets_are_staged_and_missing_assets_fail(tmp_path):
    import asyncio

    from app.note_assets import asset_resources, import_asset
    from app.worker.quarto import render_document
    from tests.test_notes_rendering import fake_cli

    notes = figure_document(tmp_path)
    unused = import_asset(tmp_path, image_bytes(size=(12, 12)), "unused.png")
    source = tmp_path / "notes.qmd"
    source.write_text(to_quarto(notes, "en", "html"))
    resources = asset_resources(tmp_path, notes.assets, source.read_text())
    resources[unused.path] = tmp_path / unused.path
    cli = fake_cli(
        tmp_path,
        """
import pathlib, sys
args = sys.argv[1:]
assert len(list(pathlib.Path("assets").iterdir())) == 1
pathlib.Path(args[args.index("--output") + 1]).write_text("rendered")
""",
    )
    result = asyncio.run(render_document({"html": source}, tmp_path / "out", 0, cli, resources))
    assert result[0].status == "ready"
    result = asyncio.run(render_document({"html": source}, tmp_path / "out", 0, cli))
    assert result[0].status == "failed" and "unregistered" in result[0].error
    assert (tmp_path / "out/notes.html").read_text() == "rendered"
    (tmp_path / notes.assets[0].path).write_bytes(b"changed")
    result = asyncio.run(render_document({"html": source}, tmp_path / "out", 0, cli, resources))
    assert result[0].status == "failed" and "digest" in result[0].error


@pytest.mark.parametrize("language", ["en", "uk"])
def test_figure_resource_and_caption_survive_render(tmp_path, language):
    """Opt-in real subprocess: images, links, numbering and bibliography in all formats."""
    import asyncio
    import os
    import re
    import zipfile

    from pypdf import PdfReader

    from app.note_assets import asset_resources
    from app.worker.quarto import render_document
    from app.worker.references import ReferenceContext

    binary = os.environ.get("QUARTO_TEST_BIN")
    if not binary:
        pytest.skip("Set QUARTO_TEST_BIN to exercise an installed Quarto")
    notes = figure_document(tmp_path)
    notes.language = language
    context = ReferenceContext(public_api_url="https://notes.example/api")
    sources = {}
    for target in ("html", "pdf", "docx"):
        folder = tmp_path / target
        folder.mkdir()
        source = folder / "notes.qmd"
        source.write_text(to_quarto(notes, "en", target, context))
        sources[target] = source
    resources = asset_resources(tmp_path, notes.assets, sources["html"].read_text())
    output = tmp_path / "output"
    result = asyncio.run(render_document(sources, output, 0, binary, resources))
    assert all(a.status == "ready" for a in result), [a.model_dump() for a in result]
    html = (output / "notes.html").read_text()
    assert 'id="fig-diagram"' in html and 'src="data:image/png;base64,' in html
    assert 'href="#sec-T2"' in html
    assert 'id="eq-energy"' in html and 'id="tbl-values"' in html
    assert 'id="ref-src-1"' in html
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    figure_label, table_label = ("Рисунок", "Таблиця") if language == "uk" else ("Figure", "Table")
    assert f"{figure_label} 1" in text and f"{table_label} 1" in text
    assert "Measured diagram" in text and "known textbook" in text.lower()
    from html.parser import HTMLParser

    class CitationText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth, self.parts = 0, []

        def handle_starttag(self, tag, attrs):
            if tag == "span":
                attributes = dict(attrs)
                if self.depth or attributes.get("data-cites") == "src-1":
                    self.depth += 1

        def handle_endtag(self, tag):
            if tag == "span" and self.depth:
                self.depth -= 1

        def handle_data(self, data):
            if self.depth:
                self.parts.append(data)

    citation = CitationText()
    citation.feed(html)
    citation_text = "".join(citation.parts)
    assert "known textbook" in citation_text.lower()
    assert re.search(r",\s*(?:p\.\s*)?10\)$", citation_text)
    pdf = PdfReader(output / "notes.pdf")
    pdf_text = re.sub(r"\s+", " ", " ".join(page.extract_text() for page in pdf.pages))
    assert f"{figure_label} 1" in pdf_text and f"{table_label} 1" in pdf_text and "(1)" in pdf_text
    assert (
        "Measured diagram" in pdf_text
        and "known textbook" in pdf_text.lower()
        and re.search(r"known textbook.{0,30}, (?:p\. )?10\)", pdf_text, re.I)
    )
    assert sum(len(page.images) for page in pdf.pages) >= 1
    with zipfile.ZipFile(output / "notes.docx") as archive:
        xml = archive.read("word/document.xml").decode()
        assert any(name.startswith("word/media/") for name in archive.namelist())
        assert all(
            term in xml.lower()
            for term in ("measured diagram", "measured values", "known textbook")
        )
        assert figure_label in xml and table_label in xml
        assert "w:drawing" in xml and "w:hyperlink" in xml
    # External equations must become usable absolute HTML links in standalone PDF/Word.
    standalone = {}
    for target in ("html", "pdf", "docx"):
        source = tmp_path / target / "topic.qmd"
        source.write_text(
            topic_to_quarto(
                notes, notes.sections[0], notes.sections[0].topics[1], "en", target, context
            )
        )
        standalone[target] = source
    result = asyncio.run(render_document(standalone, output, 0, binary, resources))
    assert all(a.status == "ready" for a in result), [a.model_dump() for a in result]
    expected = "https://notes.example/api/plans/1/notes/run/html#eq-energy"
    assert expected in (output / "topic.html").read_text()
    topic_pdf = PdfReader(output / "topic.pdf")
    links = [
        annotation.get_object().get("/A", {}).get("/URI", "")
        for page in topic_pdf.pages
        for annotation in page.get("/Annots", [])
    ]
    assert expected in links
    assert "?@eq-energy" not in " ".join(page.extract_text() for page in topic_pdf.pages)
    with zipfile.ZipFile(output / "topic.docx") as archive:
        assert expected in archive.read("word/_rels/document.xml.rels").decode()


def test_markdown_and_block_links_share_stable_destinations():
    from app.worker.references import ReferenceContext

    notes = cited_document()
    section = notes.sections[0]
    other = section.topics[0].model_copy(deep=True)
    other.topic_id, other.blocks[0].id = "T2", "T2.1"
    section.topics.append(other)
    block_id = reference_id("T2", "T2.1")
    section.topics[0].blocks[0].content = (
        f"[Other](#T2) and [Topic T2](#sec-T2) and @{block_id}. "
        "Plain Topic T2 and `Topic T2 @eq-example`."
    )
    context = ReferenceContext(public_api_url="https://notes.example/api")
    full = to_quarto(notes, "en", "html", context)
    assert f"](#{block_id})" in full
    assert "[Other](#sec-T2)" in full
    assert "[[Topic" not in full
    topic = topic_to_quarto(notes, section, section.topics[0], "en", "pdf", context)
    assert f"](https://notes.example/api/plans/1/notes/run/html#{block_id})" in topic
    assert "`Topic T2 @eq-example`" in topic
    section.topics[0].blocks[0].content = "[Missing](#unknown)"
    assert any("unknown" in issue for issue in validate_references(notes))


def test_duplicate_or_custom_reference_attributes_are_rejected():
    notes = document("$$x=1$$ {#eq-one .class}\n\n$$y=1$$ {#eq-one}")
    assert any("attributes" in issue for issue in validate_references(notes))


def test_pdf_page_fallback_stays_explicit():
    notes = cited_document()
    notes.sections[0].topics[0].evidence[0].page = "PDF p. 1"
    assert "[@src-1, PDF p. 1]" in to_quarto(notes, "en", "html")


@pytest.mark.parametrize("before", [False, True])
def test_table_caption_must_remain_adjacent_to_a_table(before):
    table = "| Symbol | Value |\n|---|---|\n| x | 1 |"
    caption = ": Values {#tbl-values}"
    content = f"{caption}\n\n{table}" if before else f"{table}\n\n{caption}"
    notes = document(content)
    assert validate_references(notes) == []
    to_quarto(notes, "en", "html")


@pytest.mark.parametrize(
    "literal",
    [
        r"$\text{Topic T2}$",
        "$\u2028Topic T2$",
        r"$\text{Cost \$5; Topic T2 @eq-example}$",
        r"$$\text{Topic T2 @eq-example [Other](#T2)}$$ {#eq-display}",
        "$$\n\\text{Topic T2 @eq-example}\n$$ {#eq-display}",
        "````text\nTopic T2 @eq-example [Other](#T2)\n`````",
        "~~~text\nTopic T2 @eq-example [Other](#T2)\n~~~~",
        "   ```text\nTopic T2 @eq-example [Other](#T2)\n   ````",
        "    Topic T2 @eq-example [Other](#T2)\n    More code",
        "\tTopic T2 @eq-example [Other](#T2)",
        "``Topic T2 ` @eq-example [Other](#T2)``",
        "`Topic T2\n@eq-example [Other](#T2)`",
    ],
)
def test_reference_normalization_preserves_math_and_code(literal):
    from app.worker.references import ReferenceContext, normalize_links

    notes = cited_document()
    section = notes.sections[0]
    other = section.topics[0].model_copy(deep=True)
    other.topic_id, other.blocks[0].id = "T2", "T2.1"
    other.blocks[0].content = "Target topic."
    section.topics.append(other)
    section.topics[0].blocks[
        0
    ].content = f"Intro.\n\n{literal}\n\nGenuine Topic T2, @sec-T2 and [Other](#T2)."
    assert validate_references(notes) == []
    assert normalize_links(literal, notes, "T1", ReferenceContext()) == literal
    for target in ("html", "pdf", "docx"):
        standalone = topic_to_quarto(notes, section, section.topics[0], "en", target)
        assert literal in standalone
        assert (
            "Genuine [Topic T2](http://localhost:8000/plans/1/notes/run/html#sec-T2)" in standalone
        )
        assert "[Other](http://localhost:8000/plans/1/notes/run/html#sec-T2)" in standalone
        full = to_quarto(notes, "en", target)
        assert literal in full
        assert "Genuine [Topic T2](#sec-T2), @sec-T2 and [Other](#sec-T2)." in full


def test_masked_math_still_checks_equation_labels_and_unsafe_resources():
    from app.worker.quarto import QuartoError

    notes = document("$$x=1$$ {#eq-known}\n\nSee @eq-known.")
    assert validate_references(notes) == []
    notes.sections[0].topics[0].blocks[0].content += "\n\n$$y=2$$ {#eq-known}"
    assert any("Duplicate" in issue for issue in validate_references(notes))
    for content in (r"$\input{/etc/passwd}$", r"$$\input{/etc/passwd}$$"):
        with pytest.raises(QuartoError, match="external TeX resources"):
            to_quarto(document(content), "en", "html")


def test_multiline_inline_math_remains_literal():
    from app.worker.references import ReferenceContext, normalize_links

    notes = cited_document()
    other = notes.sections[0].topics[0].model_copy(deep=True)
    other.topic_id, other.blocks[0].id = "T2", "T2.1"
    notes.sections[0].topics.append(other)
    content = "$x +\nTopic T2$\n\nSee Topic T2."
    notes.sections[0].topics[0].blocks[0].content = content
    normalized = normalize_links(content, notes, "T1", ReferenceContext())
    assert "$x +\nTopic T2$" in normalized
    assert "See [Topic T2](http://localhost:8000/plans/1/notes/run/html#sec-T2)." in normalized
    for target in ("html", "pdf", "docx"):
        assert "$x +\nTopic T2$" in to_quarto(notes, "en", target)


def test_currency_does_not_hide_prose_references():
    from app.worker.quarto import QuartoError
    from app.worker.references import ReferenceContext, normalize_links

    notes = cited_document()
    other = notes.sections[0].topics[0].model_copy(deep=True)
    other.topic_id, other.blocks[0].id = "T2", "T2.1"
    notes.sections[0].topics.append(other)
    content = "Prices are $5 and Topic T2 costs $10."
    normalized = normalize_links(content, notes, "T1", ReferenceContext())
    assert normalized == (
        "Prices are $5 and [Topic T2]"
        "(http://localhost:8000/plans/1/notes/run/html#sec-T2) costs $10."
    )
    notes.sections[0].topics[0].blocks[0].content = "Cost $5. Unknown @eq-unknown. Then $10."
    assert "Unknown reference: eq-unknown" in validate_references(notes)
    with pytest.raises(QuartoError, match="eq-unknown"):
        to_quarto(notes, "en", "html")


DOLLAR_CASES = [
    ("$x +\nTopic T2$", True),
    ("$x +\r\nTopic T2$", True),
    ("$x +\n  Topic T2$", True),
    ("Prices are $5 and Topic T2 costs $10.", False),
    ("$ Topic T2$", False),
    ("$Topic T2 $", False),
    ("$\r Topic T2$", False),
    ("$Topic T2 \r$", False),
    ("$\r\nTopic T2$", False),
    ("$Topic T2\r\n$", False),
    ("$Topic T2$10", False),
    ("$Topic T2\n\nnext$", False),
    ("$$Topic T2\n\n$$", False),
    ("$$\nTopic T2\n$$", True),
    ("$$Topic T2$$10", True),
    (r"\$Topic T2$", False),
    (r"\\$Topic T2$", True),
    (r"$x \$ Topic T2$", True),
    (r"$Topic T2\ $", True),
    ("$x$10 and Topic T2$", True),
    ("$$Topic T2$", True),
    ("$Topic T2$$", True),
]


# Bundled Pandoc 3.10 whitespace boundaries: Unicode separators are not all
# Markdown spaces, and the closing predicate is narrower than the opening one.
UNICODE_MATH_SPACES = [
    ("\t", False, False),
    ("\n", False, False),
    ("\v", False, True),
    ("\f", False, True),
    ("\r", True, True),
    (" ", False, False),
    ("\u0085", True, True),
    ("\u00a0", False, True),
    ("\u1680", False, True),
    ("\u2000", False, True),
    ("\u2007", False, True),
    ("\u200b", True, True),
    ("\u2028", True, True),
    ("\u2029", True, True),
    ("\u202f", False, True),
    ("\u205f", False, True),
    ("\u3000", False, True),
]
DOLLAR_CASES += [
    (content, expected)
    for char, opening, closing in UNICODE_MATH_SPACES
    for content, expected in [(f"${char}Topic T2$", opening), (f"$Topic T2{char}$", closing)]
]


@pytest.mark.parametrize("content,is_math", DOLLAR_CASES)
def test_dollar_delimiters_keep_math_distinct_from_prose(content, is_math):
    from app.worker.references import prose

    assert ("Topic T2" not in prose(content)) == is_math
    assert len(prose(content)) == len(content)


def test_dollar_masks_match_installed_pandoc():
    """Optional parser differential test; no application path invokes Pandoc."""
    import json
    import os
    import subprocess

    from app.worker.references import prose

    binary = os.environ.get("PANDOC_TEST_BIN")
    if not binary:
        pytest.skip("Set PANDOC_TEST_BIN to compare against the installed Markdown parser")

    def contains_math(value):
        if isinstance(value, dict):
            if value.get("t") == "Math" and "Topic T2" in value["c"][1]:
                return True
            return any(contains_math(child) for child in value.values())
        if isinstance(value, list):
            return any(contains_math(child) for child in value)
        return False

    for content, expected in DOLLAR_CASES:
        result = subprocess.run(
            [binary, "--from", "markdown", "--to", "json"],
            input=content,
            text=True,
            capture_output=True,
            check=True,
        )
        parsed_as_math = contains_math(json.loads(result.stdout))
        assert parsed_as_math == expected, content
        assert ("Topic T2" not in prose(content)) == parsed_as_math, content
