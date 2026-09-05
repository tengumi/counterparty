"""Fixtures giving tests access to the approved source file."""

from pathlib import Path
from typing import Any

import pytest

from import_reports import load_source_file

#: The approved mock source is read in place from ``artifacts/``; no cleaned or
#: derived copy of it exists anywhere in this project.
SOURCE_PATH = Path(__file__).resolve().parents[3] / "artifacts" / "contractors_audit.snapshot.json"


@pytest.fixture(scope="session")
def source_path() -> Path:
    """Path of the approved snapshot."""
    assert SOURCE_PATH.is_file(), f"approved source not found at {SOURCE_PATH}"
    return SOURCE_PATH


@pytest.fixture(scope="session")
def records(source_path: Path) -> list[Any]:
    """The approved snapshot, loaded once for the whole session."""
    return load_source_file(source_path)
