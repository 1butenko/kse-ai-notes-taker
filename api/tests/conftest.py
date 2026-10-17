from collections.abc import Iterator
from pathlib import Path

import pytest

from app.engine import tools


@pytest.fixture
def qmd_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Write generated .qmd files to a temp folder instead of output/qmd/."""
    monkeypatch.setattr(tools, "QMD_OUTPUT_DIR", tmp_path)
    yield tmp_path
