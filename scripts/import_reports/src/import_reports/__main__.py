r"""Command line of the report import.

This is a script and a job, never a service and never an agent endpoint. It has
two commands:

``inspect``
    Read-only. Describes a source file — its digests, its shape and, per
    section, how many records were absent, empty, populated or unparsable.
    Writes nothing, and never modifies the source.

``import``
    Writes the file into PostgreSQL and prints the import report. Running it
    twice on the same file is a no-op the second time; the printed
    ``changed_nothing`` and the before/after row counts are how that is
    checked rather than assumed.

Usage::

    uv run python -m import_reports inspect ../../artifacts/contractors_audit.snapshot.json
    COUNTERPARTY_DATABASE_URL=postgresql+psycopg://... \\
        uv run python -m import_reports import ../../artifacts/contractors_audit.snapshot.json
"""

import argparse
import json
import sys
from pathlib import Path

from .extended_json import load_source_file
from .inspection import summarize
from .run import DATABASE_URL_ENV, SourceDriftError, run_import


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="import_reports", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="describe a source file without writing")
    inspect.add_argument("source", type=Path, help="path to the report snapshot JSON file")

    run = commands.add_parser("import", help="import a source file into PostgreSQL")
    run.add_argument("source", type=Path, help="path to the report snapshot JSON file")
    run.add_argument(
        "--database-url",
        default=None,
        help=f"async or sync PostgreSQL URL; defaults to ${DATABASE_URL_ENV}",
    )
    run.add_argument(
        "--allow-schema-drift",
        action="store_true",
        help="import a source whose shape differs from the approved one",
    )
    return parser


def _inspect(source: Path) -> int:
    summary = summarize(source, load_source_file(source))
    print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))
    return 0 if not summary.verification.differences else 1


def _import(source: Path, *, database_url: str | None, allow_schema_drift: bool) -> int:
    try:
        result = run_import(
            source, database_url=database_url, allow_schema_drift=allow_schema_drift
        )
    except SourceDriftError as error:
        print(json.dumps({"error": "source_drift", "detail": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.records["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """Run one command and print its JSON report."""
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "inspect":
        return _inspect(arguments.source)
    return _import(
        arguments.source,
        database_url=arguments.database_url,
        allow_schema_drift=arguments.allow_schema_drift,
    )


if __name__ == "__main__":
    sys.exit(main())
