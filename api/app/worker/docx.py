"""Small, controlled fixes to the Word file Quarto wrote; the equations stay native OMML."""

import os
import re
import zipfile
from pathlib import Path

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


def polish_docx(path: Path) -> None:
    """Fix equation-number spacing and stranded callout titles; replaces `path` atomically."""
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "word/document.xml":
                    xml = NUMBER_GAP.sub(NORMAL_TEXT, data.decode())
                    data = CALLOUT_TITLE.sub(r"\1<w:keepNext/>\2", xml).encode()
                target.writestr(item, data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
