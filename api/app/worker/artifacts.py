"""Versioned artifacts and the run log of one notes generation run."""

import os
from pathlib import Path

from pydantic import BaseModel

from app.notes import NotesRun, RunEvent, now


class RunStore:
    def __init__(self, directory: Path, run: NotesRun) -> None:
        self.directory = directory
        self.run = run

    def path(self, name: str) -> Path:
        return self.directory / name

    def read[T: BaseModel](self, name: str, model: type[T]) -> T | None:
        target = self.path(name)
        return model.model_validate_json(target.read_text()) if target.is_file() else None

    def write(self, name: str, data: BaseModel | str) -> Path:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else data.model_dump_json(indent=2)
        partial = target.with_name(f".{target.name}.partial")
        partial.write_text(text)
        os.replace(partial, target)
        return target

    def save(self) -> None:
        self.run.updated_at = now()
        self.write("run.json", self.run)

    def log(self, stage: str, message: str) -> None:
        print(f"Notes {self.run.course}/{self.run.id} [{stage}] {message}")
        self.run.stage = stage
        self.run.events.append(RunEvent(at=now(), stage=stage, message=message))
        self.save()

    def warn(self, message: str) -> None:
        self.run.warnings.append(message)
        self.log(self.run.stage, f"Warning: {message}")
