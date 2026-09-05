"""Running one import and reporting what it actually did.

The report is the deliverable, not a log line. Specs §02.5 asks the import to
state how many records it saw, which sections carried data, what it did not
understand and what it skipped — and the numbers here are exactly the ones a
second run has to be checked against: a re-run of an unchanged file must report
zero imported, everything skipped, and leave every stored row count identical.

The source is read in place. No cleaned copy of the mock file is written, and
the report says outright that the corpus is a mock: it is not current
information about any real company.
"""

import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from counterparty_contracts import WarningCode
from counterparty_storage.reports import SourceState, WarningSeverity
from counterparty_storage.reports.models import (
    ActivityCode,
    Company,
    CompanyProfile,
    CompanyStatus,
    FinancialStatement,
    ImportBatch,
    ImportWarning,
    ReportSnapshot,
    SectionAvailability,
    ZskAssessment,
)
from sqlalchemy.orm import Session

from . import PARSER_VERSION
from .approved_source import verify_source
from .diagnostics import Diagnostic, diagnostic
from .extended_json import load_source_file
from .importer import (
    create_import_engine,
    ensure_batch,
    finish_batch,
    stored_row_counts,
    write_batch_diagnostics,
    write_snapshot,
)
from .normalize import FailedRecord, normalize

__all__ = [
    "COUNTED_TABLES",
    "DATABASE_URL_ENV",
    "SOURCE_KIND",
    "ImportResult",
    "SourceDriftError",
    "run_import",
]

#: Same variable the migrations read, so one deployment configures both.
DATABASE_URL_ENV: Final = "COUNTERPARTY_DATABASE_URL"

#: What the corpus is. Stated in every report so a mock is never presented as
#: current information about a real counterparty.
SOURCE_KIND: Final = "provided_snapshot (mock corpus, not current information)"

#: Tables counted before and after a run. The proof that a re-run changed
#: nothing is these numbers, not an assurance in prose.
COUNTED_TABLES: Final = (
    ImportBatch,
    Company,
    ReportSnapshot,
    CompanyProfile,
    CompanyStatus,
    ActivityCode,
    FinancialStatement,
    ZskAssessment,
    SectionAvailability,
    ImportWarning,
)


class SourceDriftError(RuntimeError):
    """The source has a different shape than the one this parser was verified on."""


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Everything one run of the import is able to state about itself."""

    batch_id: UUID
    batch_reused: bool
    source: dict[str, Any]
    records: dict[str, int]
    warnings: dict[str, Any]
    sections: dict[str, dict[str, int]]
    rows_before: dict[str, int]
    rows_after: dict[str, int]

    @property
    def changed_nothing(self) -> bool:
        """Whether the run left every counted table exactly as it found it."""
        return self.rows_before == self.rows_after

    def as_dict(self) -> dict[str, Any]:
        """Render the import report as plain JSON-serializable data."""
        return {
            "source_kind": SOURCE_KIND,
            "batch": {"id": str(self.batch_id), "reused": self.batch_reused},
            "source": self.source,
            "records": self.records,
            "warnings": self.warnings,
            "sections": self.sections,
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "changed_nothing": self.changed_nothing,
        }


def resolve_database_url(explicit: str | None = None) -> str:
    """Return the database URL, refusing to invent one.

    Raises:
        RuntimeError: If neither the argument nor the environment supplies it.
    """
    url = explicit or os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(
            f"database URL is not configured: set {DATABASE_URL_ENV} or pass --database-url"
        )
    return url


def _drift_diagnostics(differences: tuple[str, ...]) -> list[Diagnostic]:
    return [
        diagnostic(
            WarningCode.UNSPECIFIED,
            f"source differs from the approved snapshot: {difference}",
            severity=WarningSeverity.WARNING,
            kind="source_difference",
        )
        for difference in differences
    ]


def run_import(
    source: Path,
    *,
    database_url: str | None = None,
    allow_schema_drift: bool = False,
) -> ImportResult:
    """Import every record of ``source`` into PostgreSQL, idempotently.

    A file whose bytes differ from the approved snapshot is imported: changed
    snapshots are exactly what a later export looks like, and they land as new
    versions. A file whose *shape* differs is refused unless the caller says
    otherwise, because a reshaped source parsed by these rules would quietly
    fill the wrong columns.

    Raises:
        SourceDriftError: If the schema fingerprint differs and drift was not
            explicitly allowed.
    """
    records = load_source_file(source)
    verification = verify_source(source, records)
    if not verification.has_approved_shape and not allow_schema_drift:
        raise SourceDriftError(
            f"{source} has schema fingerprint {verification.schema_digest}, "
            f"not the approved shape; review it and re-run with --allow-schema-drift"
        )

    engine = create_import_engine(resolve_database_url(database_url))
    section_states: dict[str, Counter[str]] = {}
    observed: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    imported = skipped = failed = 0
    companies_created = 0
    written_warnings = 0
    rows_written: Counter[str] = Counter()

    try:
        with Session(engine) as session, session.begin():
            rows_before = stored_row_counts(session, COUNTED_TABLES)
            batch = ensure_batch(
                session,
                file_name=source.name,
                sha256=verification.file_sha256,
                schema_fingerprint=verification.schema_digest,
                parser_version=PARSER_VERSION,
                record_count=verification.record_count,
            )
            written_warnings += write_batch_diagnostics(
                session,
                batch_id=batch.id,
                diagnostics=_drift_diagnostics(verification.differences),
            )

        for record in records:
            normalized = normalize(record)
            for item in normalized.diagnostics:
                observed[item.code] += 1
                by_severity[item.severity.value] += 1
            with Session(engine) as session, session.begin():
                if isinstance(normalized, FailedRecord):
                    failed += 1
                    written_warnings += write_batch_diagnostics(
                        session,
                        batch_id=batch.id,
                        diagnostics=normalized.diagnostics,
                        source_record_id=normalized.source_record_id,
                    )
                    continue
                for section in normalized.availability:
                    state = section["source_state"]
                    name = str(section["section"])
                    counter = section_states.setdefault(name, Counter())
                    counter[state.value if isinstance(state, SourceState) else str(state)] += 1
                outcome = write_snapshot(session, batch_id=batch.id, snapshot=normalized)
                if outcome.company_created:
                    companies_created += 1
                if outcome.skipped:
                    skipped += 1
                    continue
                imported += 1
                written_warnings += outcome.warnings
                rows_written["activity_codes"] += outcome.activities
                rows_written["financial_statements"] += outcome.financials
                rows_written["section_availability"] += outcome.availability

        with Session(engine) as session, session.begin():
            counts: dict[str, Any] = {
                "records": {
                    "total": len(records),
                    "imported": imported,
                    "skipped": skipped,
                    "failed": failed,
                },
                "companies_created": companies_created,
                "rows_written": dict(rows_written),
                "warnings_written": written_warnings,
                "warnings_observed": dict(observed),
                "sections": {
                    name: dict(counter) for name, counter in sorted(section_states.items())
                },
                "source_kind": SOURCE_KIND,
            }
            finish_batch(
                session,
                batch_id=batch.id,
                imported=imported,
                skipped=skipped,
                failed=failed,
                counts=counts,
            )
            rows_after = stored_row_counts(session, COUNTED_TABLES)
    finally:
        engine.dispose()

    return ImportResult(
        batch_id=batch.id,
        batch_reused=batch.reused,
        source={
            "path": str(source),
            "file_name": source.name,
            "sha256": verification.file_sha256,
            "record_count": verification.record_count,
            "schema_fingerprint": verification.schema_digest,
            "schema_rule_version": verification.schema_rule_version,
            "schema_path_count": verification.schema_path_count,
            "is_approved_source": verification.is_approved_source,
            "differences": list(verification.differences),
        },
        records={
            "total": len(records),
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "companies_created": companies_created,
        },
        warnings={
            "written": written_warnings,
            "observed": sum(observed.values()),
            "by_code": dict(sorted(observed.items())),
            "by_severity": dict(sorted(by_severity.items())),
        },
        sections={name: dict(counter) for name, counter in sorted(section_states.items())},
        rows_before=rows_before,
        rows_after=rows_after,
    )
