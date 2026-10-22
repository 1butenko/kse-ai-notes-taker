"""Stable document references and bibliography without invented source metadata."""

import re
from dataclasses import dataclass
from urllib.parse import quote

from app.config import validate_public_api_url
from app.note_assets import image_references
from app.notes import NoteBlock, NotesDocument, TopicNote

LABEL = re.compile(r"\{#([^{}\s]+)\}")
REFERENCE = re.compile(r"(?<![\w/])@([A-Za-z0-9][A-Za-z0-9_.:-]*[A-Za-z0-9]|[A-Za-z0-9])")
FRAGMENT_LINK = re.compile(r"(?<!!)\[([^\[\]\n]+)\]\(#([^\s)]+)\)")
MARKDOWN_LINK = re.compile(r"!?\[[^\[\]\n]*\]\([^\n)]*\)")
BLANK_LINE = re.compile(r"\r?\n[ \t]*\r?\n")
VALID_LABEL = re.compile(r"(?:eq|fig|tbl)-[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z")


def reference_id(topic_id: str, block_id: str | None = None) -> str:
    """Encode identifiers reversibly, preserving their identity through title edits."""

    def encode(value: str) -> str:
        return "".join(
            char if char.isascii() and char.isalnum() else f"_{ord(char):x}_" for char in value
        )

    return "sec-" + encode(topic_id) + ("--" + encode(block_id) if block_id is not None else "")


def build_reference_data(document: NotesDocument) -> list[dict]:
    # Source has no author/year fields. Never infer them from file names or PDF offsets.
    return [
        {"id": f"src-{source.id}", "type": "document", "title": source.title}
        for source in document.sources
    ]


def mask_text(value: str) -> str:
    """Keep offsets and line boundaries when excluding literal regions from scans."""
    return re.sub(r"[^\r\n]", " ", value)


def without_code(value: str) -> str:
    """Exclude fenced/indented blocks and exact-delimiter inline code spans.

    Fences can have up to three leading spaces; a closer uses the same marker
    and at least the opener's length. Indented code starts after a blank line
    (or at the beginning), so ordinary indented paragraph continuations remain
    prose. This mask never replaces the independent unsafe-Markdown validator.
    """
    lines = []
    fence: str | None = None
    indented = False
    previous_blank = True
    for line in value.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", line)
        blank = not line.strip()
        if fence is not None:
            lines.append(mask_text(line))
            if (
                marker
                and marker[1][0] == fence[0]
                and len(marker[1]) >= len(fence)
                and not marker[2].strip()
            ):
                fence = None
        elif marker:
            fence = marker[1]
            indented = False
            lines.append(mask_text(line))
        elif re.match(r"^(?: {4}| {0,3}\t)", line) and (indented or previous_blank):
            indented = True
            lines.append(mask_text(line))
        else:
            if not blank:
                indented = False
            lines.append(line)
        previous_blank = blank
    value = "".join(lines)
    # Delimiter boundaries prevent a shorter run inside a code span from closing
    # it. Code spans may cross line breaks but not a paragraph boundary.
    return re.sub(
        r"(?<![\\`])(`+)(?!`)(?:(?!\n[ \t]*\n)[\s\S])*?(?<!`)\1(?!`)",
        lambda match: mask_text(match[0]),
        value,
    )


def math_end(value: str, start: int, delimiter: str) -> int | None:
    """Find a dollar-math closer using Pandoc's tex_math_dollars boundaries.

    https://pandoc.org/MANUAL.html#extension-tex_math_dollars
    Inline opening/closing whitespace and a digit after the closer prevent a
    match. Both forms allow line breaks but not blank lines. Backslash escapes
    consume their next character, including a literal dollar or escaped space.
    """
    cursor = body_start = start + len(delimiter)
    inline = delimiter == "$"
    if cursor == len(value) or (inline and value[cursor].isspace()):
        return None
    trailing_space = False
    while cursor < len(value):
        if BLANK_LINE.match(value, cursor):
            return None
        if value.startswith(delimiter, cursor):
            end = cursor + len(delimiter)
            if cursor == body_start or (
                inline and (trailing_space or (end < len(value) and value[end] in "0123456789"))
            ):
                return None
            return end
        if value[cursor] == "\\":
            cursor += 2
            trailing_space = False
        else:
            trailing_space = value[cursor] in " \t\r\n"
            cursor += 1
    return None


def prose(value: str) -> str:
    """Exclude code and Pandoc dollar math without hiding currency prose."""
    value = without_code(value)
    result = list(value)
    cursor = 0
    while cursor < len(value):
        if value[cursor] == "\\":
            cursor += 2
            continue
        if value[cursor] == "$":
            end = math_end(value, cursor, "$$") if value.startswith("$$", cursor) else None
            if end is None:
                end = math_end(value, cursor, "$")
            if end is not None:
                result[cursor:end] = mask_text(value[cursor:end])
                cursor = end
                continue
        cursor += 1
    return "".join(result)


def reference_targets(document: NotesDocument) -> dict[str, tuple[TopicNote, str]]:
    targets = {}
    for section in document.sections:
        for note in section.topics:
            targets[reference_id(note.topic_id)] = (note, note.title)
            for block in note.blocks:
                targets[reference_id(note.topic_id, block.id)] = (note, block.title or block.id)
                for label in LABEL.findall(prose(block.content)):
                    targets[label] = (note, label)
    return targets


def has_captioned_table(content: str, label: str) -> bool:
    caption = re.search(r"(?m)^:\s+\S[^\n]*\{#" + re.escape(label) + r"\}[^\S\n]*$", content)
    if caption is None:
        return False
    # Pandoc permits captions immediately before or after a pipe table, with a
    # separating blank line. An orphan caption is not a cross-reference target.
    before = re.split(r"\n\s*\n", content[: caption.start()].rstrip())[-1]
    after = re.split(r"\n\s*\n", content[caption.end() :].lstrip())[0]
    separator = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
    for adjacent in (before, after):
        lines = adjacent.splitlines()
        for index, line in enumerate(lines):
            if index and separator.fullmatch(line) and "|" in lines[index - 1]:
                return True
    return False


def validate_references(document: NotesDocument) -> list[str]:
    issues = []
    labels = set()
    sources = {f"src-{source.id}" for source in document.sources}
    if len(sources) != len(document.sources):
        issues.append("Duplicate source IDs")
    assets = {asset.path for asset in document.assets}
    if len(assets) != len(document.assets):
        issues.append("Duplicate asset paths")
    targets = reference_targets(document)
    for section in document.sections:
        for note in section.topics:
            anchors = [reference_id(note.topic_id)]
            evidence = {item.chunk_id: item for item in note.evidence}
            for block in note.blocks:
                anchors.append(reference_id(note.topic_id, block.id))
                content = without_code(block.content)
                visible = prose(block.content)
                declared = LABEL.findall(visible)
                for attributes in re.findall(r"\{[^{}]*#[^{}]*\}", visible):
                    if not LABEL.fullmatch(attributes):
                        issues.append(f"Invalid reference label attributes: {attributes}")
                for label in declared:
                    if not VALID_LABEL.fullmatch(label):
                        issues.append(f"Invalid label: {label}; use eq-, fig- or tbl-")
                    elif label.startswith("eq-") and not re.search(
                        r"\$\$[\s\S]+?\$\$\s*\{#" + re.escape(label) + r"\}", content
                    ):
                        issues.append(f"Equation label must follow display math: {label}")
                    elif label.startswith("tbl-") and not has_captioned_table(content, label):
                        issues.append(
                            f"Table label requires a caption beside a pipe table: {label}"
                        )
                try:
                    figures = image_references(block.content)
                    figure_labels = {label for _, _, label in figures}
                    for _, path, _ in figures:
                        if path not in assets:
                            issues.append(f"Unregistered note asset: {path}")
                    for label in declared:
                        if label.startswith("fig-") and label not in figure_labels:
                            issues.append(f"Figure label requires a captioned image: {label}")
                except ValueError as error:
                    issues.append(str(error))
                anchors.extend(declared)
                for chunk in block.citations:
                    item = evidence.get(chunk)
                    if item is None:
                        issues.append(f"Unknown evidence citation: {chunk}")
                    elif f"src-{item.source}" not in sources:
                        issues.append(f"Unknown evidence source: src-{item.source}")
                aliases = {
                    topic.topic_id: reference_id(topic.topic_id)
                    for section in document.sections
                    for topic in section.topics
                }
                for _, fragment in FRAGMENT_LINK.findall(visible):
                    if aliases.get(fragment, fragment) not in targets:
                        issues.append(f"Unknown reference: {fragment}")
                # A final period is punctuation, not part of the identifier.
                for token in REFERENCE.findall(visible):
                    token = token.rstrip(".:")
                    if token not in sources and token not in targets:
                        issues.append(f"Unknown reference: {token}")
            for anchor in anchors:
                if anchor in labels:
                    issues.append(f"Duplicate reference label: {anchor}")
                labels.add(anchor)
    return issues


@dataclass(frozen=True)
class ReferenceContext:
    """Trusted destinations; later revision rendering can supply an immutable HTML URL."""

    public_api_url: str = "http://localhost:8000"
    full_html_url: str | None = None

    def document_url(self, document: NotesDocument) -> str:
        if self.full_html_url is not None:
            return validate_public_api_url(self.full_html_url)
        base = validate_public_api_url(self.public_api_url)
        course, run = quote(document.course, safe=""), quote(document.run, safe="")
        return f"{base}/plans/{course}/notes/{run}/html"


def normalize_links(
    content: str, document: NotesDocument, current_topic: str | None, context: ReferenceContext
) -> str:
    targets = reference_targets(document)
    topics = [note for section in document.sections for note in section.topics]
    aliases = {note.topic_id: reference_id(note.topic_id) for note in topics}
    block_anchors = {
        reference_id(note.topic_id, block.id) for note in topics for block in note.blocks
    }

    def destination(token: str) -> str:
        owner = targets[token][0]
        base = (
            context.document_url(document)
            if current_topic and owner.topic_id != current_topic
            else ""
        )
        return base + "#" + quote(token, safe="")

    def link_text(value: str) -> str:
        return value.replace("[", "").replace("]", "").replace("\n", " ")

    # Existing local Markdown links use the same destinations as @ cross-references.
    for match in reversed(list(FRAGMENT_LINK.finditer(prose(content)))):
        token = aliases.get(match[2], match[2])
        if token in targets:
            replacement = f"[{match[1]}]({destination(token)})"
            content = content[: match.start()] + replacement + content[match.end() :]

    def unlinked_prose(value: str) -> str:
        return MARKDOWN_LINK.sub(lambda m: " " * len(m[0]), prose(value))

    for match in reversed(list(REFERENCE.finditer(unlinked_prose(content)))):
        token = match[1].rstrip(".:")
        suffix = match[1][len(token) :]
        target = targets.get(token)
        if target is None:
            continue
        external = bool(current_topic and target[0].topic_id != current_topic)
        # Blocks have stable anchors but no section number: use a normal link.
        if external or token in block_anchors:
            label = link_text(target[1]) + (" (HTML)" if external else "")
            replacement = f"[{label}]({destination(token)}){suffix}"
            content = content[: match.start()] + replacement + content[match.end() :]

    # The composition prompt has always used "Topic T3" for inter-topic references.
    for note in topics:
        pattern = re.compile(r"\bTopic " + re.escape(note.topic_id) + r"\b")
        for match in reversed(list(pattern.finditer(unlinked_prose(content)))):
            url = destination(reference_id(note.topic_id))
            content = content[: match.start()] + f"[{match[0]}]({url})" + content[match.end() :]
    return content


def citation_markdown(note: TopicNote, block: NoteBlock) -> str:
    evidence = {item.chunk_id: item for item in note.evidence}
    citations = []
    for chunk in block.citations:
        item = evidence[chunk]
        page = item.page.strip() if item.page else ""
        if page and re.fullmatch(r"[0-9ivxlcdmIVXLCDM]+(?:[–-][0-9ivxlcdmIVXLCDM]+)?", page):
            page = "p. " + page
        citation = f"@src-{item.source}" + (f", {page}" if page else "")
        if citation not in citations:
            citations.append(citation)
    return "[" + "; ".join(citations) + "]" if citations else ""


DEFAULT_REFERENCE_CONTEXT = ReferenceContext()
