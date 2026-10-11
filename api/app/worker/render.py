"""Format writer: render the validated notes into a Quarto document and typeset it with Typst."""

import asyncio
import json
import re
import shutil
from pathlib import Path

from app.notes import NoteBlock, NotesDocument, NotesSection, Source, TopicNote

QUARTO_TIMEOUT = 600
TOPIC_RENDERS = 4

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


def block_markdown(block: NoteBlock, text: dict[str, str], cite: str, fence: str = "::::") -> str:
    title = typst_safe(block.title) if block.title else text.get(block.kind)
    body = typst_safe(block.content.strip())
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
    title: str, date: str, language: str | None, subtitle: str | None = None, outline: bool = True
) -> str:
    return "\n".join(
        [
            "---",
            "from: markdown+lists_without_preceding_blankline",
            f"title: {yaml(title)}",
            *([f"subtitle: {yaml(subtitle)}"] if subtitle else []),
            f"date: {yaml(date[:10])}",
            f"lang: {yaml(language or 'en')}",
            "format:",
            "  typst:",
            f"    toc: {str(outline).lower()}",
            f"    number-sections: {str(outline).lower()}",
            "    papersize: a4",
            "    margin:",
            "      x: 2.5cm",
            "      y: 2.5cm",
            "    mainfont: DejaVu Serif",
            "    fontsize: 11pt",
            "    keep-typ: true",
            "---",
        ]
    )


def topic_body(note: TopicNote, text: dict[str, str], cite: Citations) -> list[str]:
    if note.status == "no_evidence":
        return [f"*{text['no_evidence']}*\n"]
    body = []
    if note.status != "verified":
        body.append(f"::: {{.callout-caution}}\n## {text['unverified']}\n")
        body += [f"- {typst_safe(i.detail)}" for i in note.open_issues] or ["-"]
        body.append(":::\n")
    body += [block_markdown(block, text, cite(block)) + "\n" for block in note.blocks]
    return body


def footer(document: NotesDocument, text: dict[str, str]) -> str:
    models = ", ".join(sorted(set(document.models.values())))
    return f"\n*{text['generated']}: {document.created_at} · {models}*\n"


def to_quarto(document: NotesDocument, language: str | None) -> str:
    text = labels(language)
    cite = Citations(document, text)
    body = []
    if document.notation:
        body.append(f"# {text['notation']} {{.unnumbered}}\n")
        body.append(f"| {text['symbol']} | {text['meaning']} |\n|---|---|")
        body += [
            f"| {typst_safe(n.symbol).replace('|', '\\|')} | "
            f"{typst_safe(n.meaning).replace('|', '\\|')} |"
            for n in document.notation
        ]
        body.append("")

    for section in document.sections:
        body.append(f"# {section.title}\n")
        for note in section.topics:
            body.append(f"## {note.title}\n")
            body += topic_body(note, text, cite)

    body += cite.references()
    body.append(footer(document, text))
    header = front_matter(document.title, document.created_at, language)
    return header + "\n\n" + "\n".join(body)


def topic_to_quarto(
    document: NotesDocument, section: NotesSection, note: TopicNote, language: str | None
) -> str:
    """One topic as a standalone document: its blocks and only the sources it cites."""
    text = labels(language)
    cite = Citations(document, text)
    body = topic_body(note, text, cite) + cite.references() + [footer(document, text)]
    header = front_matter(
        note.title,
        document.created_at,
        language,
        subtitle=f"{section.title} · {document.title}",
        outline=False,
    )
    return header + "\n\n" + "\n".join(body)


class QuartoError(Exception):
    pass


async def render_pdf(qmd: Path, quarto: str) -> Path:
    """Typeset a .qmd next to itself with Quarto; returns the PDF path."""
    binary = shutil.which(quarto)
    if binary is None:
        raise QuartoError(f"Quarto is not installed ({quarto!r} not found)")
    process = await asyncio.create_subprocess_exec(
        binary,
        "render",
        qmd.name,
        "--to",
        "typst",
        cwd=qmd.parent,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), QUARTO_TIMEOUT)
    except TimeoutError as error:
        process.kill()
        raise QuartoError(f"Quarto took longer than {QUARTO_TIMEOUT} s") from error
    log = output.decode(errors="replace")
    (qmd.parent / "quarto.log").write_text(log)
    pdf = qmd.with_suffix(".pdf")
    if process.returncode != 0 or not pdf.is_file():
        tail = re.sub(r"\s+", " ", log[-600:]).strip()
        raise QuartoError(f"Quarto failed (exit {process.returncode}): {tail}")
    return pdf


async def render_pdfs(qmds: list[Path], quarto: str) -> dict[Path, QuartoError]:
    """Typeset several documents, a few at a time; returns the ones that failed."""
    gate = asyncio.Semaphore(TOPIC_RENDERS)
    failed: dict[Path, QuartoError] = {}

    async def one(qmd: Path) -> None:
        async with gate:
            try:
                await render_pdf(qmd, quarto)
            except QuartoError as error:
                failed[qmd] = error

    await asyncio.gather(*(one(qmd) for qmd in qmds))
    return failed
