from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response

from app.books import subset_pdf
from app.config import Settings, get_settings
from app.plan import excerpt_proposal, load_plan

router = APIRouter(prefix="/files", tags=["files"])

VIEWABLE = {"syllabus", "reading", "excerpts", "lecture"}


def inline(filename: str) -> str:
    """Content-Disposition for showing a file in the browser, as FileResponse writes it."""
    quoted = quote(filename)
    if quoted != filename:
        return f"inline; filename*=utf-8''{quoted}"
    return f'inline; filename="{filename}"'


def excerpt_response(root: Path, path: str) -> Response:
    """The excerpt's pages, cut from its book now: excerpts are not stored as files."""
    course = path.split("/")[0]
    proposal = excerpt_proposal(load_plan(root / course), path)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Excerpt not found")
    book = root / proposal.book
    if not book.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The book file is gone")
    pages = list(range(proposal.pdf_start, proposal.pdf_end + 1))
    name = f"{book.stem[:60]} - {proposal.label}"[:120].replace("/", "-")
    return Response(
        subset_pdf(book, pages),
        media_type="application/pdf",
        headers={"content-disposition": inline(f"{name}.pdf")},
    )


@router.get("")
def get_file(
    path: Annotated[str, Query()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Serve an uploaded file or excerpt inline, for the viewer."""
    root = settings.uploads_dir.resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Path is outside the uploads directory")
    parts = file.relative_to(root).parts
    if len(parts) < 3 or parts[1] not in VIEWABLE or file.name.endswith(".json"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a viewable file")
    if parts[1] == "excerpts" and not file.is_file():
        return excerpt_response(root, file.relative_to(root).as_posix())
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(file, filename=file.name, content_disposition_type="inline")
