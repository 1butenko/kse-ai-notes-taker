"""Shared Markdown reference lexer used by approval and rendering."""

import re
import unicodedata
from collections.abc import Iterator

REFERENCE = re.compile(r"(?<![\w/])@([A-Za-z0-9][A-Za-z0-9_.:-]*[A-Za-z0-9]|[A-Za-z0-9])")
BLANK_LINE = re.compile(r"\r?\n[ \t]*\r?\n")


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
    The caller supplies Pandoc's CR-free input projection.
    """
    cursor = body_start = start + len(delimiter)
    inline = delimiter == "$"
    # Pandoc opening spaceChar: Unicode Zs plus tab/LF/VT/FF. U+2028,
    # U+2029 and NEL remain math; standalone CR is discarded by its reader.
    if cursor == len(value) or (
        inline and (value[cursor] in "\t\n\v\f" or unicodedata.category(value[cursor]) == "Zs")
    ):
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
            trailing_space = value[cursor] in " \t\n"
            cursor += 1
    return None


def code_projection(value: str) -> tuple[str, list[int]]:
    """Pandoc discards CR before parsing; retain raw offsets while excluding code."""
    offsets = [index for index, char in enumerate(value) if char != "\r"]
    return without_code(value.replace("\r", "")), offsets


def math_regions(value: str) -> Iterator[tuple[int, int]]:
    """Raw offsets of Pandoc dollar math, after its CR removal and code parsing."""
    value, offsets = code_projection(value)
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
                yield offsets[cursor], offsets[end - 1] + 1
                cursor = end
                continue
        cursor += 1


def prose(value: str) -> str:
    """Exclude code and Pandoc dollar math without hiding currency prose."""
    projected, offsets = code_projection(value)
    result = list(value)
    for offset, char in zip(offsets, projected, strict=True):
        result[offset] = char
    for start, end in math_regions(value):
        result[start:end] = mask_text(value[start:end])
    return "".join(result)


def reference_tokens(value: str) -> list[str]:
    """Pandoc-visible @references with terminal punctuation removed."""
    return [token.rstrip(".:") for token in REFERENCE.findall(prose(value))]


def source_ids_from_markdown(value: str) -> set[int]:
    """Frozen source IDs cited directly by an authored Markdown field."""
    return {
        int(token[4:])
        for token in reference_tokens(value)
        if token.startswith("src-") and token[4:].isdigit()
    }
