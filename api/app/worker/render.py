"""Prepare validated notes for HTML, Typst PDF and Word, with legacy PDF helpers."""

import asyncio
import json
import re
from pathlib import Path

from app.notes import NoteBlock, NotesDocument, NotesSection, RenderFormat, TopicNote
from app.worker.quarto import QuartoError, render_document, validate_markdown
from app.worker.references import (
    DEFAULT_REFERENCE_CONTEXT,
    ReferenceContext,
    build_reference_data,
    citation_markdown,
    normalize_links,
    reference_id,
    validate_references,
)

MATH = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$", re.S)
FONT_SWITCH = re.compile(r"\{\\(rm|bf|it|sf|tt|cal)\s+([^{}]*)\}")
FONT_COMMANDS = {"rm": "mathrm", "bf": "mathbf", "it": "mathit", "sf": "mathsf", "tt": "mathtt"}
ONE_ARGUMENT = (
    "mathcal|mathbb|mathrm|mathbf|mathit|mathsf|mathtt|mathfrak|boldsymbol|bm|operatorname|"
    "text|textrm|hat|bar|vec|tilde|dot|ddot|overline|underline"
)
BARE_SCRIPT = re.compile(
    rf"(?<!\\)([\^_])(\\(?:{ONE_ARGUMENT})(?:\s*\{{[^{{}}]*\}}|\s+[A-Za-z0-9])"
    r"|\\[A-Za-z]+(?![A-Za-z]|\s*\{)|[A-Za-z0-9])"
)


def separate_scripts(formula: str) -> str:
    """Add `{}` after each braced script that something follows: Pandoc's Typst writer glues
    a script on a bracketed base to the next token, e.g. `(a)^T x` becomes `^Tx`."""
    out, i = [], 0
    while i < len(formula):
        char = formula[i]
        out.append(char)
        i += 1
        if char not in "^_" or (i > 1 and formula[i - 2] == "\\") or formula[i : i + 1] != "{":
            continue
        depth = 0
        while i < len(formula):
            out.append(formula[i])
            if formula[i - 1] != "\\":
                depth += {"{": 1, "}": -1}.get(formula[i], 0)
            i += 1
            if depth == 0:
                break
        rest = formula[i:].lstrip()
        if rest and rest[0] not in "^_}$'":
            out.append("{}")
    return "".join(out)


def clean_math(formula: str) -> str:
    """LaTeX that Pandoc converts to Typst reliably, with the same meaning."""
    formula = FONT_SWITCH.sub(
        lambda m: f"{{\\{FONT_COMMANDS.get(m[1], 'mathcal')}{{{m[2].strip()}}}}}", formula
    )
    return separate_scripts(BARE_SCRIPT.sub(r"\1{\2}", formula))


STARTS_BLOCK = re.compile(r"\s*(?:[-*+] |\d+[.)] |\$\$|>|\|)")
QED = re.compile(r"(∎|□|■|\\square|\\blacksquare|\\qed|\\Box)\$?\s*$")


def typst_safe(text: str) -> str:
    return MATH.sub(lambda m: clean_math(m[0]), text)


CALLOUTS = {
    "definition": "note",
    "theorem": "important",
    "example": "tip",
    "intuition": "tip",
    "remark": "warning",
}

LABELS = {
    "en": {
        "definition": "Definition",
        "theorem": "Theorem",
        "proof": "Proof",
        "example": "Example",
        "intuition": "Intuition",
        "remark": "Remark",
        "summary": "Summary",
        "references": "References",
        "sources": "Sources",
        "unverified": "Not fully verified",
        "no_evidence": "No supporting material was found for this topic.",
        "notation": "Notation",
        "generated": "Generated",
        "symbol": "Symbol",
        "meaning": "Meaning",
    },
    "uk": {
        "definition": "Означення",
        "theorem": "Теорема",
        "proof": "Доведення",
        "example": "Приклад",
        "intuition": "Інтуїція",
        "remark": "Зауваження",
        "summary": "Підсумок",
        "references": "Джерела",
        "sources": "Джерела",
        "unverified": "Не повністю перевірено",
        "no_evidence": "Для цієї теми не знайдено матеріалів.",
        "notation": "Позначення",
        "generated": "Згенеровано",
        "symbol": "Символ",
        "meaning": "Значення",
    },
}


def labels(language: str | None) -> dict[str, str]:
    return LABELS.get(language or "en", LABELS["en"])


def yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def block_markdown(
    block: NoteBlock,
    text: dict[str, str],
    cite: str,
    fence: str = "::::",
    target: RenderFormat = "pdf",
    assets: set[str] | None = None,
) -> str:
    validate_markdown(block.content, assets)
    if block.title:
        validate_markdown(block.title)
    transform = typst_safe if target == "pdf" else str
    title = transform(block.title) if block.title else text.get(block.kind)
    body = transform(block.content.strip())
    footer = f"\n\n{cite}" if cite else ""
    callout = CALLOUTS.get(block.kind)
    if callout:
        name = text.get(block.kind, "")
        heading = f"{name}: {title}" if block.title and name else (title or "")
        return f"{fence} {{.callout-{callout}}}\n## {heading}\n\n{body}{footer}\n{fence}"
    lead = (title or "") + "." if title and block.kind != "overview" else ""
    separator = "\n\n" if STARTS_BLOCK.match(body) else " "
    if block.kind == "proof":
        end = "" if QED.search(body) else " $\\square$"
        return f"*{lead}*{separator}{body}{end}{footer}"
    if lead:
        return f"**{lead}**{separator}{body}{footer}"
    return f"{body}{footer}"


def front_matter(
    title: str,
    date: str,
    language: str | None,
    subtitle: str | None = None,
    outline: bool = True,
    target: RenderFormat = "pdf",
    references: list[dict] | None = None,
) -> str:
    if target not in ("html", "pdf", "docx"):
        raise ValueError(f"Unsupported render format: {target}")
    created_label = "Створено" if language == "uk" else "Created"
    options = {
        "pdf": [
            "    papersize: a4",
            "    margin:",
            "      x: 2.5cm",
            "      y: 2.5cm",
            "    mainfont: DejaVu Serif",
            "    fontsize: 11pt",
            "    keep-typ: true",
        ],
        "html": [
            "    html-math-method: mathjax",
            "    embed-resources: true",
            "    css: notes.css",
            "    include-in-header: notes-head.html",
            "    toc-location: body",
        ],
        "docx": [],
    }
    return "\n".join(
        [
            "---",
            "from: markdown+lists_without_preceding_blankline-raw_html-raw_tex-raw_attribute"
            "-yaml_metadata_block",
            f"title: {yaml(title)}",
            *([f"subtitle: {yaml(subtitle)}"] if subtitle else []),
            f"date: {yaml(date[:10])}",
            f"lang: {yaml(language if language in ('uk', 'en') else 'en')}",
            f"toc-title: {yaml('Зміст' if language == 'uk' else 'Table of contents')}",
            "language:",
            f"  title-block-published: {yaml(created_label)}",
            f"  section-title-references: {yaml(labels(language)['references'])}",
            *(
                [
                    '  crossref-fig-title: "Рисунок"',
                    '  crossref-tbl-title: "Таблиця"',
                    '  crossref-sec-prefix: "Розділ"',
                    '  crossref-eq-prefix: "Рівняння"',
                ]
                if language == "uk"
                else []
            ),
            "citeproc: true",
            "references: " + json.dumps(references or [], ensure_ascii=False),
            "execute:",
            "  enabled: false",
            "format:",
            f"  {'typst' if target == 'pdf' else target}:",
            f"    toc: {str(outline).lower()}",
            f"    number-sections: {str(outline).lower()}",
            *options[target],
            "---",
        ]
    )


def topic_body(
    note: TopicNote,
    text: dict[str, str],
    document: NotesDocument,
    target: RenderFormat = "pdf",
    current_topic: str | None = None,
    context: ReferenceContext = DEFAULT_REFERENCE_CONTEXT,
) -> list[str]:
    transform = typst_safe if target == "pdf" else str
    if note.status == "no_evidence":
        return [f"*{text['no_evidence']}*\n"]
    body = []
    if note.status != "verified":
        body.append(f"::: {{.callout-caution}}\n## {text['unverified']}\n")
        body += [f"- {transform(i.detail)}" for i in note.open_issues] or ["-"]
        body.append(":::\n")
    for block in note.blocks:
        content = normalize_links(block.content, document, current_topic, context)
        prepared = block.model_copy(update={"content": content})
        body.append(
            f"::::: {{#{reference_id(note.topic_id, block.id)}}}\n\n"
            + block_markdown(
                prepared,
                text,
                citation_markdown(note, block),
                target=target,
                assets={asset.path for asset in document.assets},
            )
            + "\n\n:::::\n"
        )
    return body


def checked_references(document: NotesDocument) -> list[dict]:
    issues = validate_references(document)
    if issues:
        raise QuartoError("Invalid references: " + "; ".join(issues))
    references = build_reference_data(document)
    for item in references:
        validate_markdown(item["title"])
    return references


def bibliography(text: dict[str, str]) -> list[str]:
    return [f"# {text['references']} {{.unnumbered}}\n", "::: {#refs}\n:::\n"]


def footer(document: NotesDocument, text: dict[str, str]) -> str:
    models = ", ".join(sorted(set(document.models.values())))
    return f"\n*{text['generated']}: {document.created_at} · {models}*\n"


def to_quarto(
    document: NotesDocument,
    language: str | None,
    target: RenderFormat = "pdf",
    context: ReferenceContext = DEFAULT_REFERENCE_CONTEXT,
) -> str:
    language = document.language or language
    transform = typst_safe if target == "pdf" else str
    text = labels(language)
    references = checked_references(document)
    body = []
    if document.notation:
        body.append(f"# {text['notation']} {{.unnumbered}}\n")
        body.append(f"| {text['symbol']} | {text['meaning']} |\n|---|---|")
        body += [
            f"| {transform(n.symbol).replace('|', '\\|')} | "
            f"{transform(n.meaning).replace('|', '\\|')} |"
            for n in document.notation
        ]
        body.append("")

    for section in document.sections:
        body.append(f"# {section.title}\n")
        for note in section.topics:
            body.append(f"## {note.title} {{#{reference_id(note.topic_id)}}}\n")
            body += topic_body(note, text, document, target, context=context)

    if references:
        body += bibliography(text)
    body.append(footer(document, text))
    header = front_matter(
        document.title, document.created_at, language, target=target, references=references
    )
    return checked_document(
        header, body, document.title, assets={asset.path for asset in document.assets}
    )


def topic_to_quarto(
    document: NotesDocument,
    section: NotesSection,
    note: TopicNote,
    language: str | None,
    target: RenderFormat = "pdf",
    context: ReferenceContext = DEFAULT_REFERENCE_CONTEXT,
) -> str:
    """One topic as a standalone document: its blocks and only the sources it cites."""
    language = document.language or language
    text = labels(language)
    references = checked_references(document)
    body = [f"# {note.title} {{#{reference_id(note.topic_id)}}}\n"]
    body += topic_body(note, text, document, target, note.topic_id, context)
    if references:
        body += bibliography(text)
    body.append(footer(document, text))
    header = front_matter(
        note.title,
        document.created_at,
        language,
        subtitle=f"{section.title} · {document.title}",
        outline=False,
        target=target,
        references=references,
    )
    return checked_document(
        header,
        body,
        note.title,
        section.title,
        document.title,
        assets={asset.path for asset in document.assets},
    )


def checked_document(
    header: str, body: list[str], *titles: str, assets: set[str] | None = None
) -> str:
    for title in titles:
        validate_markdown(title)
    markdown = "\n".join(body)
    validate_markdown(markdown, assets)
    return header + "\n\n" + markdown


async def render_pdf(qmd: Path, quarto: str) -> Path:
    """Compatibility wrapper: publish a PDF next to its prepared QMD."""
    (artifact,) = await render_document({"pdf": qmd}, qmd.parent, 0, quarto)
    if artifact.status == "failed":
        raise QuartoError(artifact.error)
    return qmd.parent / artifact.path


async def render_pdfs(qmds: list[Path], quarto: str, concurrency: int) -> dict[Path, QuartoError]:
    """Typeset several documents, `concurrency` at a time; returns the ones that failed."""
    gate = asyncio.Semaphore(concurrency)
    failed: dict[Path, QuartoError] = {}

    async def one(qmd: Path) -> None:
        async with gate:
            try:
                await render_pdf(qmd, quarto)
            except QuartoError as error:
                failed[qmd] = error

    await asyncio.gather(*(one(qmd) for qmd in qmds))
    return failed
