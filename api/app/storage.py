import hashlib
from pathlib import Path


def sha256(file: Path) -> str:
    with file.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
