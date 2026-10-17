import re
from typing import Literal

import yaml
from deepagents.backends import StateBackend
from langchain.tools import tool
from langchain_core.utils.uuid import uuid7
from langchain_core.vectorstores import VectorStore

from app.engine.config import QMD_OUTPUT_DIR, SEARCH_K


def make_search_books_tool(vector_store: VectorStore, backend: StateBackend):
    @tool(parse_docstring=True)
    def search_books(query: str) -> str:
        """Search course textbooks and save matching chunks to the agent filesystem.

        Args:
            query: Natural language search query.

        Returns:
            File paths where retrieved chunks were saved under /retrieved/.
        """
        retrieved_docs = vector_store.similarity_search(query, k=SEARCH_K)
        batch_id = uuid7().hex[:8]
        uploads: list[tuple[str, bytes]] = []
        saved_paths: list[str] = []

        for index, doc in enumerate(retrieved_docs, start=1):
            path = f"/retrieved/{batch_id}/chunk_{index}.md"
            content = f"# Source: {doc.metadata.get('source', 'unknown')}\n\n{doc.page_content}"
            uploads.append((path, content.encode("utf-8")))
            saved_paths.append(path)

        backend.upload_files(uploads)
        return f"Saved {len(saved_paths)} documentation chunks:\n" + "\n".join(saved_paths)

    return search_books


@tool(parse_docstring=True)
def write_quarto_document(
    filename: str,
    title: str,
    body: str,
    toc: bool = True,
    toc_depth: int | None = None,
    toc_location: Literal["right", "left", "body", "left-body", "right-body"] | None = None,
    toc_title: str | None = None,
    number_sections: bool = False,
    number_depth: int | None = None,
    html_math_method: Literal["katex", "mathjax", "webtex", "gladtex", "mathml", "plain"] = "katex",
    css: str | None = None,
    embed_resources: bool = False,
) -> str:
    """Write a Quarto (.qmd) document with an HTML-format YAML header to the output folder.

    Header options follow https://quarto.org/docs/output-formats/html-basics.html.
    Options left at their default are omitted from the header.

    Args:
        filename: File name for the document, e.g. "eigenvalues".
            The .qmd extension is added if missing.
        title: Document title.
        body: Markdown body of the document (headings, text, $...$ / $$...$$ math,
            code blocks). Do not include the YAML header.
        toc: Include a generated table of contents.
        toc_depth: Number of heading levels in the table of contents (Quarto default 3).
        toc_location: Where the table of contents appears (Quarto default "right", floating).
        toc_title: Heading text for the table of contents.
        number_sections: Number the section headings.
        number_depth: Deepest heading level that gets numbered (only with number_sections).
        html_math_method: How LaTeX math is rendered in HTML.
        css: Path to an extra stylesheet, e.g. "styles.css".
            Omit if the document has no custom stylesheet.
        embed_resources: Produce a self-contained HTML file (all assets inlined).

    Returns:
        Path of the written .qmd file.
    """
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.strip()).strip(".-") or "document"
    if not stem.endswith(".qmd"):
        stem += ".qmd"
    path = QMD_OUTPUT_DIR / stem

    html: dict = {}
    if toc:
        html["toc"] = True
        if toc_depth is not None:
            html["toc-depth"] = toc_depth
        if toc_location is not None:
            html["toc-location"] = toc_location
        if toc_title:
            html["toc-title"] = toc_title
    if number_sections:
        html["number-sections"] = True
        if number_depth is not None:
            html["number-depth"] = number_depth
    html["html-math-method"] = html_math_method
    if css:
        html["css"] = css
    if embed_resources:
        html["embed-resources"] = True

    header = {"title": title, "format": {"html": html}}
    front_matter = yaml.safe_dump(header, sort_keys=False, allow_unicode=True)

    QMD_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front_matter}---\n\n{body.strip()}\n", encoding="utf-8")
    return f"Wrote Quarto document to {path}"
