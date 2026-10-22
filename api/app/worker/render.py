"""Prepare validated notes for HTML, Typst PDF and Word, with legacy PDF helpers."""

import asyncio
import json
import re
from pathlib import Path

from app.notes import NoteBlock, NotesDocument, NotesSection, RenderFormat, Source, TopicNote
from app.worker.quarto import QuartoError, render_document, validate_markdown

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


def source_ref(source: Source) -> str:
    pages = (
        f"PDF pp. {source.pdf_start}–{source.pdf_end}"
        if source.pdf_start and source.pdf_end and source.pdf_start != source.pdf_end
        else f"PDF p. {source.pdf_start}"
        if source.pdf_start
        else None
    )
    return ", ".join(p for p in (source.title, source.label, pages) if p)


def block_markdown(
    block: NoteBlock,
    text: dict[str, str],
    cite: str,
    fence: str = "::::",
    target: RenderFormat = "pdf",
) -> str:
    validate_markdown(block.content)
    if block.title:
        validate_markdown(block.title)
    transform = typst_safe if target == "pdf" else str
    title = transform(block.title) if block.title else text.get(block.kind)
    body = transform(block.content.strip())
    footer = f"\n\n*{text['sources']}: {cite}*" if cite else ""
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


class Citations:
    """Numbers sources in order of first citation and lists them as references."""

    def __init__(self, document: NotesDocument, text: dict[str, str]) -> None:
        self.text = text
        self.sources = {s.id: s for s in document.sources}
        self.chunks = {
            e.chunk_id: e
            for section in document.sections
            for note in section.topics
            for e in note.evidence
        }
        self.numbers: dict[int, int] = {}

    def __call__(self, block: NoteBlock) -> str:
        pages: dict[int, list[str]] = {}
        for chunk_id in block.citations:
            item = self.chunks.get(chunk_id)
            if item is None:
                continue
            number = self.numbers.setdefault(item.source, len(self.numbers) + 1)
            listed = pages.setdefault(number, [])
            if item.page and item.page not in listed:
                listed.append(item.page)
        return "; ".join(
            f"[{n}{', ' + ', '.join(p) if p else ''}]" for n, p in sorted(pages.items())
        )

    def references(self) -> list[str]:
        if not self.numbers:
            return []
        ordered = sorted(self.numbers.items(), key=lambda n: n[1])
        return [
            f"# {self.text['references']} {{.unnumbered}}\n",
            *(f"{number}. {source_ref(self.sources[source])}" for source, number in ordered),
            "",
        ]


def front_matter(
    title: str,
    date: str,
    language: str | None,
    subtitle: str | None = None,
    outline: bool = True,
    target: RenderFormat = "pdf",
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
            *(
                [
                    "language:",
                    f"  title-block-published: {yaml(created_label)}",
                ]
                if target == "html"
                else []
            ),
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
    note: TopicNote, text: dict[str, str], cite: Citations, target: RenderFormat = "pdf"
) -> list[str]:
    transform = typst_safe if target == "pdf" else str
    if note.status == "no_evidence":
        return [f"*{text['no_evidence']}*\n"]
    body = []
    if note.status != "verified":
        body.append(f"::: {{.callout-caution}}\n## {text['unverified']}\n")
        body += [f"- {transform(i.detail)}" for i in note.open_issues] or ["-"]
        body.append(":::\n")
    body += [
        block_markdown(block, text, cite(block), target=target) + "\n" for block in note.blocks
    ]
    return body


def footer(document: NotesDocument, text: dict[str, str]) -> str:
    models = ", ".join(sorted(set(document.models.values())))
    return f"\n*{text['generated']}: {document.created_at} · {models}*\n"


def to_quarto(document: NotesDocument, language: str | None, target: RenderFormat = "pdf") -> str:
    language = document.language or language
    transform = typst_safe if target == "pdf" else str
    text = labels(language)
    cite = Citations(document, text)
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
            body.append(f"## {note.title}\n")
            body += topic_body(note, text, cite, target)

    body += cite.references()
    body.append(footer(document, text))
    header = front_matter(document.title, document.created_at, language, target=target)
    return checked_document(header, body, document.title)


def topic_to_quarto(
    document: NotesDocument,
    section: NotesSection,
    note: TopicNote,
    language: str | None,
    target: RenderFormat = "pdf",
) -> str:
    """One topic as a standalone document: its blocks and only the sources it cites."""
    language = document.language or language
    text = labels(language)
    cite = Citations(document, text)
    body = topic_body(note, text, cite, target) + cite.references() + [footer(document, text)]
    header = front_matter(
        note.title,
        document.created_at,
        language,
        subtitle=f"{section.title} · {document.title}",
        outline=False,
        target=target,
    )
    return checked_document(header, body, note.title, section.title, document.title)


def checked_document(header: str, body: list[str], *titles: str) -> str:
    for title in titles:
        validate_markdown(title)
    markdown = "\n".join(body)
    validate_markdown(markdown)
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
