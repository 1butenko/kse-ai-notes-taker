"""The course record, <course>/course.json: its name and setup decisions."""

from pathlib import Path

from pydantic import BaseModel, ValidationError


class CourseInfo(BaseModel):
    course: str
    name: str
    created_at: str
    # When the lecturer approved the readings per lecture; reading the lectures anew clears it.
    readings_approved_at: str | None = None


def info_file(directory: Path) -> Path:
    return directory / "course.json"


def load_info(directory: Path) -> CourseInfo | None:
    target = info_file(directory)
    if not target.is_file():
        return None
    try:
        info = CourseInfo.model_validate_json(target.read_text())
    except ValidationError:
        return None
    # The directory names the course, whatever the file says.
    return info.model_copy(update={"course": directory.name})


def save_info(directory: Path, info: CourseInfo) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    info_file(directory).write_text(info.model_dump_json(indent=2))


def clear_readings_approval(directory: Path) -> None:
    """The lectures were read or edited again: their readings need approving again."""
    info = load_info(directory)
    if info and info.readings_approved_at:
        save_info(directory, info.model_copy(update={"readings_approved_at": None}))
        print(f"Readings approval cleared: {directory.name}")
