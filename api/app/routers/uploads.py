import shutil
import uuid
from pathlib import Path
from typing import Annotated, Literal

import httpx2
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.links import PageTooLarge, fetch, get_web_client, html_to_text, is_video
from app.moodle import MoodleClient, get_moodle_client
from app.plan import load_plan
from app.routers.courses import moodle_errors
from app.storage import sha256

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


def excerpt_sessions(settings: Settings, path: str) -> list[str]:
    """Labels of the sessions whose approved excerpts read pages of this book."""
    plan = load_plan(settings.uploads_dir / path.split("/")[0])
    ids = {p.session_id for p in plan.proposals if p.status == "approved" and p.book == path}
    labels = [s.label for s in plan.sessions if s.id in ids]
    # Approved excerpts of sessions the syllabus no longer has wait in Unassigned.
    return labels + (["Unassigned"] if ids - {s.id for s in plan.sessions} else [])


class Staging:
    """Uploads land next to their category first and replace their files only when every
    one may: a book whose pages approved excerpts read keeps its bytes."""

    def __init__(self, settings: Settings, directory: Path) -> None:
        self.settings = settings
        self.directory = directory.parent / ".staging"
        self.files: list[tuple[Path, Path]] = []

    def __enter__(self) -> "Staging":
        return self

    def __exit__(self, *_) -> None:
        for temporary, _ in self.files:
            temporary.unlink(missing_ok=True)

    def add(self, dest: Path) -> Path:
        """Where to write the upload meant for `dest`."""
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / f"{len(self.files)}-{uuid.uuid4().hex}"
        self.files.append((temporary, dest))
        return temporary

    def commit(self) -> list[SavedFile]:
        conflicts = []
        for temporary, dest in self.files:
            if dest.is_file() and sha256(dest) != sha256(temporary):
                path = dest.relative_to(self.settings.uploads_dir).as_posix()
                if sessions := excerpt_sessions(self.settings, path):
                    conflicts.append(f"{dest.name} (excerpts in {', '.join(sessions)})")
        if conflicts:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A different file is already saved under this name and approved excerpts read "
                f"its pages: {'; '.join(conflicts)}. Upload it under another name, or remove "
                "those excerpts first.",
            )
        result = []
        for temporary, dest in self.files:
            size = temporary.stat().st_size
            temporary.replace(dest)
            result.append(saved(self.settings, dest, size))
        return result


@router.post("")
async def upload_files(
    category: Annotated[Category, Form()],
    files: Annotated[list[UploadFile], File()],
    settings: Annotated[Settings, Depends(get_settings)],
    course_id: Annotated[int | None, Form()] = None,
) -> list[SavedFile]:
    directory = target_dir(settings, course_id, category)
    with Staging(settings, directory) as staging:
        for upload in files:
            with staging.add(directory / safe_name(upload.filename or "")).open("wb") as out:
                shutil.copyfileobj(upload.file, out)
        return staging.commit()


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
    with Staging(settings, directory) as staging:
        for ref in body.files:
            temporary = staging.add(directory / safe_name(ref.filename))
            with moodle_errors():
                await moodle.download(settings.moodle_token, ref.fileurl, temporary)
        return staging.commit()


class MoodleLinksRequest(BaseModel):
    course_id: int
    modules: list[int] = Field(min_length=1)


@router.post("/moodle/links")
async def upload_moodle_links(
    body: MoodleLinksRequest,
    moodle: Annotated[MoodleClient, Depends(get_moodle_client)],
    web: Annotated[httpx2.AsyncClient, Depends(get_web_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[SavedFile]:
    """Save the web pages that the course's Moodle links point to as reading materials: PDFs
    as they are, HTML pages as text. Only links of the course itself are fetched."""
    with moodle_errors():
        sections = await moodle.get_course_contents(settings.moodle_token, body.course_id)
    links = {
        m.id: (m.name, c.fileurl)
        for s in sections
        for m in s.modules
        if m.modname == "url"
        for c in m.contents[:1]
        if c.type == "url"
    }
    directory = target_dir(settings, body.course_id, "reading")
    with Staging(settings, directory) as staging:
        for module in body.modules:
            if module not in links:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"No link {module} in this course")
            name, url = links[module]
            if not url.startswith(("http://", "https://")) or is_video(url):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"{name}: only web pages can be imported",
                )
            try:
                content_type, page = await fetch(web, url)
            except PageTooLarge as error:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE, f"{name}: over 20 MB"
                ) from error
            except httpx2.HTTPError as error:
                print(f"Link download failed: {url}: {error!r}")
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY, f"{name}: couldn't download {url}"
                ) from error

            if "pdf" in content_type or page.startswith(b"%PDF"):
                staging.add(directory / f"{safe_name(name)}.pdf").write_bytes(page)
            elif "html" in content_type or "text/plain" in content_type:
                text = page.decode(errors="replace")
                if "html" in content_type:
                    text = html_to_text(text)
                if not text.strip():
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{name}: no text")
                staging.add(directory / f"{safe_name(name)}.md").write_text(
                    f"# {name}\n\nSource: {url}\n\n{text}\n"
                )
            else:
                raise HTTPException(
                    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    f"{name}: {content_type or 'unknown type'} can't be imported",
                )
        return staging.commit()


class CourseFiles(BaseModel):
    syllabus: list[SavedFile]
    reading: list[SavedFile]


@router.get("/{course}")
def list_files(course: str, settings: Annotated[Settings, Depends(get_settings)]) -> CourseFiles:
    if course != "local" and not course.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid course: {course!r}")

    def listed(category: Category) -> list[SavedFile]:
        directory = settings.uploads_dir / course / category
        if not directory.is_dir():
            return []
        return [
            SavedFile(path=f.relative_to(settings.uploads_dir).as_posix(), size=f.stat().st_size)
            for f in sorted(directory.iterdir())
            if f.is_file() and not f.name.endswith(".transcript.json")
        ]

    return CourseFiles(syllabus=listed("syllabus"), reading=listed("reading"))
