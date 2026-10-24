"""Small, controlled fixes to the Word file Quarto wrote; the equations stay native OMML."""

import os
import re
import zipfile
from pathlib import Path
from xml.dom import Node
from xml.dom.minidom import Element, parseString

# Quarto appends "<gap>(N)" to a numbered display equation as math runs. Math engines such as
# LibreOffice's drop the spaces of an ordinary math run, which leaves "formula.(1)" glued.
NUMBER_GAP = re.compile(
    r"<m:r><m:t>(\u2001+)</m:t></m:r>"
    r"(?=<m:r>(?:<m:rPr>(?:(?!</m:rPr>).)*</m:rPr>)?<m:t>\(</m:t></m:r>)",
    re.S,
)
NORMAL_TEXT = r'<m:r><m:rPr><m:nor/></m:rPr><m:t xml:space="preserve">\1</m:t></m:r>'

# A callout is a two-row table: a coloured title row and its body. Each row cannot split, so a
# title row at the bottom of a page is stranded from its body unless it keeps with the next row.
CALLOUT_TITLE = re.compile(
    r'(<w:p><w:pPr><w:pStyle w:val="[^"]+" />)'
    r'(</w:pPr><w:pPr>\s*<w:spacing w:before="0" w:after="0" />'
    r'\s*<w:textAlignment w:val="center"/>)'
)
MATH_BLOCK = re.compile(r"<m:oMath>.*?</m:oMath>", re.S)


def _simple_math_run(node: Node) -> str | None:
    """Read one Pandoc math character without flattening nested OMML constructs."""
    if node.nodeType != Node.ELEMENT_NODE or node.nodeName != "m:r":
        return None
    children = [child for child in node.childNodes if child.nodeType == Node.ELEMENT_NODE]
    texts = [child for child in children if child.nodeName == "m:t"]
    if len(texts) != 1 or any(child.nodeName not in {"m:rPr", "m:t"} for child in children):
        return None
    return "".join(child.data for child in texts[0].childNodes if child.nodeType == Node.TEXT_NODE)


def _group_superscript_bases(xml: str) -> str:
    """Put a balanced parenthesized expression inside its superscript base.

    Pandoc writes `(x)^2` as sibling runs for `(x` followed by a superscript whose
    base is only `)`. LibreOffice imports that unmatched closing parenthesis as `¿`.
    Moving the existing runs into the base keeps the expression and editable OMML.
    """
    if "<m:sSup>" not in xml:
        return xml

    def group_one(match: re.Match[str]) -> str:
        source = match.group(0)
        if "<m:sSup>" not in source:
            return source
        document = parseString(
            '<root xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
            f"{source}</root>"
        )
        math = document.documentElement.firstChild
        changed = False
        for superscript in math.getElementsByTagName("m:sSup"):
            base = next(
                (
                    child
                    for child in superscript.childNodes
                    if child.nodeType == Node.ELEMENT_NODE and child.nodeName == "m:e"
                ),
                None,
            )
            if base is None:
                continue
            base_parts = [child for child in base.childNodes if child.nodeType == Node.ELEMENT_NODE]
            if len(base_parts) != 1 or _simple_math_run(base_parts[0]) != ")":
                continue
            parent = superscript.parentNode
            if not isinstance(parent, Element) or parent.nodeName not in {"m:oMath", "m:e"}:
                continue
            previous = superscript.previousSibling
            depth = 1
            preceding: list[Node] = []
            while previous is not None:
                value = _simple_math_run(previous)
                if value is None or len(value) != 1:
                    break
                preceding.append(previous)
                if value == ")":
                    depth += 1
                elif value == "(":
                    depth -= 1
                    if depth == 0:
                        break
                previous = previous.previousSibling
            if depth != 0:
                continue
            closing = base_parts[0]
            for run in reversed(preceding):
                base.insertBefore(parent.removeChild(run), closing)
            changed = True
        return math.toxml() if changed else source

    return MATH_BLOCK.sub(group_one, xml)


def polish_docx(path: Path) -> None:
    """Fix equation-number spacing and stranded callout titles; replaces `path` atomically."""
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "word/document.xml":
                    xml = NUMBER_GAP.sub(NORMAL_TEXT, data.decode())
                    xml = CALLOUT_TITLE.sub(r"\1<w:keepNext/>\2", xml)
                    data = _group_superscript_bases(xml).encode()
                target.writestr(item, data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
