"""Normalize `core_course_get_contents` into a flat catalog the agent can browse."""

import re
from html.parser import HTMLParser

from pydantic import BaseModel

from app.note_taker.moodle.client import Module, Section

# Activities that never hold study material. The prompt tells the agent to skip them, and
# `fetch_materials` refuses them as a second line of defence.
SKIP_MODNAMES = frozenset(
    {
        "forum",
        "quiz",
        "attendance",
        "feedback",
        "choice",
        "assign",
        "workshop",
        "chat",
        "survey",
        "scorm",
        "bigbluebuttonbn",
        "zoom",
        "choicegroup",
        "questionnaire",
    }
)


class CatalogFile(BaseModel):
    filename: str
    fileurl: str
    mimetype: str = ""
    filesize: int = 0
    timemodified: int = 0


class CatalogItem(BaseModel):
    module_id: int
    section: int
    section_name: str
    modname: str
    name: str
    url: str = ""
    description: str = ""
    files: list[CatalogFile] = []


class CatalogSection(BaseModel):
    section: int
    name: str
    summary: str = ""


class Catalog(BaseModel):
    sections: list[CatalogSection] = []
    items: list[CatalogItem] = []

    def find(self, module_id: int) -> CatalogItem | None:
        return next((item for item in self.items if item.module_id == module_id), None)


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"}
    _SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skipping += 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skipping = max(0, self._skipping - 1)
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Plain text of an HTML fragment, with paragraphs kept as line breaks."""
    extractor = _TextExtractor()
    extractor.feed(html)
    text = "".join(extractor.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def link_target(module: Module) -> str:
    """Where a `url` module points (its first content); Moodle's own page for other modules."""
    if module.modname == "url":
        for content in module.contents:
            if content.type == "url" and content.fileurl:
                return content.fileurl
    return module.url


def normalize_contents(sections: list[Section]) -> Catalog:
    """Flatten sections into catalog items. Hidden modules are dropped, they are not accessible."""
    catalog = Catalog()
    for section in sections:
        if not section.visible:
            continue
        catalog.sections.append(
            CatalogSection(
                section=section.section,
                name=section.name,
                summary=html_to_text(section.summary),
            )
        )
        for module in section.modules:
            if not module.visible or not module.uservisible:
                continue
            catalog.items.append(
                CatalogItem(
                    module_id=module.id,
                    section=section.section,
                    section_name=section.name,
                    modname=module.modname,
                    name=module.name,
                    url=link_target(module),
                    description=html_to_text(module.description),
                    files=[
                        CatalogFile(
                            filename=content.filename,
                            fileurl=content.fileurl,
                            mimetype=content.mimetype,
                            filesize=content.filesize,
                            timemodified=content.timemodified,
                        )
                        for content in module.contents
                        if content.type == "file" and content.fileurl
                    ],
                )
            )
    return catalog


def _size(num_bytes: int) -> str:
    if num_bytes >= 1_000_000:
        return f"{num_bytes / 1_000_000:.1f} MB"
    return f"{max(num_bytes // 1000, 1)} KB"


def outline(catalog: Catalog) -> str:
    """A compact outline, one line per module, grouped by section."""
    lines: list[str] = []
    by_section: dict[int, list[CatalogItem]] = {}
    for item in catalog.items:
        by_section.setdefault(item.section, []).append(item)
    for section in catalog.sections:
        summary = f" - {section.summary[:120]}" if section.summary else ""
        lines.append(f"## Section {section.section}: {section.name or '(untitled)'}{summary}")
        for item in by_section.get(section.section, []):
            files = ", ".join(
                f"{f.filename} ({f.mimetype or '?'}, {_size(f.filesize)})" for f in item.files[:5]
            )
            if len(item.files) > 5:
                files += f", +{len(item.files) - 5} more"
            lines.append(
                f"- [{item.module_id}] {item.modname}: {item.name}"
                + (f" | {files}" if files else "")
                + (f" -> {item.url[:120]}" if item.modname == "url" and item.url else "")
            )
    return "\n".join(lines)
