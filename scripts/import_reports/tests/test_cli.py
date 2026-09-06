"""The inspection command is read-only and reports what it found."""

import json
from pathlib import Path

import pytest

from import_reports.__main__ import main


def test_cli_reports_the_approved_source_without_differences(
    source_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Running against the approved file exits 0 and prints a JSON summary."""
    before = source_path.stat().st_mtime_ns
    assert main(["inspect", str(source_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verification"]["differences"] == []
    assert payload["record_count"] == 100
    assert source_path.stat().st_mtime_ns == before, "the source file must not be modified"


def test_cli_fails_on_a_source_that_is_not_the_approved_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A different file exits non-zero and names every difference."""
    other = tmp_path / "other.json"
    other.write_text(json.dumps([{"_id": {}, "report": {}}]), encoding="utf-8")
    assert main(["inspect", str(other)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["verification"]["differences"]) == 3
