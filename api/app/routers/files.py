from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.config import Settings, get_settings

router = APIRouter(prefix="/files", tags=["files"])

VIEWABLE = {"syllabus", "reading", "excerpts", "lecture"}


@router.get("")
def get_file(
    path: Annotated[str, Query()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    """Serve an uploaded file or excerpt inline, for the viewer."""
    root = settings.uploads_dir.resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Path is outside the uploads directory")
    parts = file.relative_to(root).parts
    if len(parts) < 3 or parts[1] not in VIEWABLE or file.name.endswith(".json"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a viewable file")
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(file, filename=file.name, content_disposition_type="inline")
