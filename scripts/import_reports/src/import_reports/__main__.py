"""CLI entry point: describe and verify a report source file.

This is a read-only inspection command, not the importer. It writes nothing and
never modifies the source.

Usage::

    uv run python -m import_reports ../../artifacts/contractors_audit.snapshot.json
"""

import argparse
import json
import sys
from pathlib import Path

from .extended_json import load_source_file
from .inspection import summarize


def main(argv: list[str] | None = None) -> int:
    """Print a JSON summary of the given source file."""
    parser = argparse.ArgumentParser(prog="import_reports", description=__doc__)
    parser.add_argument("source", type=Path, help="path to the report snapshot JSON file")
    arguments = parser.parse_args(argv)

    records = load_source_file(arguments.source)
    summary = summarize(arguments.source, records)
    print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))
    return 0 if not summary.verification.differences else 1


if __name__ == "__main__":
    sys.exit(main())
