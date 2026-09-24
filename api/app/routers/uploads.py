import shutil
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.moodle import MoodleClient, get_moodle_client
from app.routers.courses import moodle_errors

router = APIRouter(prefix="/uploads", tags=["uploads"])

Category = Literal["syllabus", "reading"]


class SavedFile(BaseModel):
    path: str
    size: int


class MoodleFileRef(BaseModel):
    fileurl: str
    filename: str


class MoodleUploadRequest(BaseModel):
    category: Category
    course_id: int | None = None
    files: list[MoodleFileRef] = Field(min_length=1)


def safe_name(name: str) -> str:
    cleaned = name.replace("/", "-").replace("\\", "-").strip()
    if cleaned in ("", ".", ".."):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid file name: {name!r}")
    return cleaned


def target_dir(settings: Settings, course_id: int | None, category: Category) -> Path:
    directory = settings.uploads_dir / (str(course_id) if course_id else "local") / category
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def saved(settings: Settings, dest: Path, size: int) -> SavedFile:
    path = dest.relative_to(settings.uploads_dir).as_posix()
    print(f"Saved upload: {path} ({size} bytes)")
    return SavedFile(path=path, size=size)


@router.post("")
async def upload_files(
    category: Annotated[Category, Form()],
    files: Annotated[list[UploadFile], File()],
    settings: Annotated[Settings, Depends(get_settings)],
    course_id: Annotated[int | None, Form()] = None,
) -> list[SavedFile]:
    directory = target_dir(settings, course_id, category)
    result = []
    for upload in files:
        dest = directory / safe_name(upload.filename or "")
        with dest.open("wb") as out:
            shutil.copyfileobj(upload.file, out)
        result.append(saved(settings, dest, dest.stat().st_size))
    return result


@router.post("/moodle")
async def upload_moodle_files(
    body: MoodleUploadRequest,
    moodle: Annotated[MoodleClient, Depends(get_moodle_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[SavedFile]:
    moodle_prefix = f"{settings.moodle_url.rstrip('/')}/"
    for ref in body.files:
        if not ref.fileurl.startswith(moodle_prefix):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Not a Moodle file: {ref.fileurl}")

    directory = target_dir(settings, body.course_id, body.category)
    result = []
    for ref in body.files:
        dest = directory / safe_name(ref.filename)
        with moodle_errors():
            size = await moodle.download(settings.moodle_token, ref.fileurl, dest)
        result.append(saved(settings, dest, size))
    return result
