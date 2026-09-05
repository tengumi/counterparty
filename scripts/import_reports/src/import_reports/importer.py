"""Writing normalized snapshots into PostgreSQL, idempotently.

Idempotence is a property of the schema here, not of a flag in this file. Two
unique constraints carry it:

* ``import_batches.sha256`` — one batch row per source file. A second run of the
  same file reuses that row instead of opening a parallel history of the same
  bytes;
* ``report_snapshots (company_id, hash)`` — one row per distinct snapshot
  payload. Re-importing an unchanged record inserts nothing and, crucially,
  touches none of its child rows; a record whose content changed hashes
  differently and therefore lands as a new version alongside the old one.

Both are expressed as ``INSERT ... ON CONFLICT DO NOTHING``, so a re-run is
decided by the database rather than by a read-then-write race, and the importer
never needs ``DELETE`` — a privilege its role does not have. Nothing already
stored is rewritten: a snapshot that is already there is skipped whole.

Each snapshot is written in its own transaction, so an interrupted run leaves
whole snapshots behind, never a company without its report or a report without
its sections.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from counterparty_contracts import WarningCode
from counterparty_storage.reports import WarningSeverity
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
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .diagnostics import Diagnostic, diagnostic
from .normalize import NormalizedSnapshot

__all__ = [
    "BatchState",
    "SnapshotOutcome",
    "create_import_engine",
    "ensure_batch",
    "finish_batch",
    "stored_row_counts",
    "write_batch_diagnostics",
    "write_snapshot",
]


def create_import_engine(url: str) -> Engine:
    """Open the engine the import writes through.

    The URL is supplied by the caller — from the environment or the command
    line — because a credential never belongs in this repository. It is
    expected to name the ``counterparty_importer`` login role: that role may
    write inside ``reports`` and holds no ``DELETE`` at all, so the database,
    not this code, is what stops the import from removing anything.
    """
    return create_engine(url, future=True, pool_pre_ping=True)


@dataclass(frozen=True, slots=True)
class BatchState:
    """The batch row this run writes into."""

    id: UUID
    reused: bool
    """True when the same file was already imported; its row is updated in place."""


@dataclass(slots=True)
class SnapshotOutcome:
    """What happened to one source record."""

    inserted: bool = False
    skipped: bool = False
    """The snapshot hash was already stored; nothing was written or changed."""

    failed: bool = False
    company_created: bool = False
    activities: int = 0
    financials: int = 0
    availability: int = 0
    warnings: int = 0
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)


def ensure_batch(
    session: Session,
    *,
    file_name: str,
    sha256: str,
    schema_fingerprint: str,
    parser_version: str,
    record_count: int,
) -> BatchState:
    """Return the batch row for this source file, creating it only once.

    The unique digest of the file is what makes a batch: a second run of the
    same bytes continues the same batch instead of claiming to be a new import
    of new data.
    """
    statement = (
        pg_insert(ImportBatch)
        .values(
            id=uuid.uuid4(),
            file_name=file_name,
            sha256=sha256,
            schema_fingerprint=schema_fingerprint,
            parser_version=parser_version,
            record_count=record_count,
            imported_count=0,
            skipped_count=0,
            failed_count=0,
            counts_jsonb={},
        )
        .on_conflict_do_nothing(index_elements=[ImportBatch.sha256])
        .returning(ImportBatch.id)
    )
    created = session.execute(statement).scalar_one_or_none()
    if created is not None:
        return BatchState(id=created, reused=False)
    existing = session.execute(
        select(ImportBatch.id).where(ImportBatch.sha256 == sha256)
    ).scalar_one()
    return BatchState(id=existing, reused=True)


def _insert_warning(
    session: Session,
    *,
    batch_id: UUID,
    report_id: UUID | None,
    source_record_id: str | None,
    item: Diagnostic,
) -> None:
    session.execute(
        pg_insert(ImportWarning).values(
            id=uuid.uuid4(),
            batch_id=batch_id,
            report_id=report_id,
            source_record_id=source_record_id,
            severity=item.severity,
            code=item.code,
            source_path=item.source_path,
            message=item.message,
            details_jsonb=dict(item.details),
        )
    )


def write_batch_diagnostics(
    session: Session,
    *,
    batch_id: UUID,
    diagnostics: Iterable[Diagnostic],
    source_record_id: str | None = None,
) -> int:
    """Store diagnostics that belong to the run rather than to one snapshot.

    ``import_warnings`` has no natural key, and the importer cannot delete, so
    a warning that would repeat on a re-run of the same batch is looked up
    before it is written. That keeps a second run from inflating the diagnostic
    count of the first.
    """
    written = 0
    for item in diagnostics:
        already = session.execute(
            select(ImportWarning.id)
            .where(
                ImportWarning.batch_id == batch_id,
                ImportWarning.report_id.is_(None),
                ImportWarning.code == item.code,
                ImportWarning.message == item.message,
            )
            .limit(1)
        ).scalar_one_or_none()
        if already is not None:
            continue
        _insert_warning(
            session,
            batch_id=batch_id,
            report_id=None,
            source_record_id=source_record_id,
            item=item,
        )
        written += 1
    return written


def _ensure_company(session: Session, snapshot: NormalizedSnapshot) -> tuple[UUID, bool, int]:
    """Return the company row for this INN, creating it at most once.

    An existing company is never rewritten from a later snapshot: identity
    attributes belong to the snapshot that reported them. A registration number
    that disagrees with the stored one is reported instead of overwriting it.
    """
    statement = (
        pg_insert(Company)
        .values(
            id=uuid.uuid4(),
            inn=snapshot.inn,
            ogrn=snapshot.ogrn,
            entity_type=None,
        )
        .on_conflict_do_nothing(index_elements=[Company.inn])
        .returning(Company.id)
    )
    created = session.execute(statement).scalar_one_or_none()
    if created is not None:
        return created, True, 0
    existing = session.execute(
        select(Company.id, Company.ogrn).where(Company.inn == snapshot.inn)
    ).one()
    conflicts = 0
    if snapshot.ogrn is not None and existing.ogrn is not None and existing.ogrn != snapshot.ogrn:
        conflicts = 1
    return existing.id, False, conflicts


def write_snapshot(
    session: Session, *, batch_id: UUID, snapshot: NormalizedSnapshot
) -> SnapshotOutcome:
    """Write one snapshot and everything that hangs off it, or skip it.

    Returns without writing anything when the snapshot hash is already stored:
    that is what makes a re-run a no-op rather than a duplicate.
    """
    company_id, company_created, ogrn_conflicts = _ensure_company(session, snapshot)
    report_id = session.execute(
        pg_insert(ReportSnapshot)
        .values(
            id=uuid.uuid4(),
            company_id=company_id,
            batch_id=batch_id,
            source_record_id=snapshot.source_record_id,
            source_record_jsonb=snapshot.source_record_jsonb,
            source_report_at=snapshot.source_report_at,
            hash=snapshot.hash,
            raw_jsonb=snapshot.raw_jsonb,
            ingestion_status=snapshot.ingestion_status,
        )
        .on_conflict_do_nothing(index_elements=[ReportSnapshot.company_id, ReportSnapshot.hash])
        .returning(ReportSnapshot.id)
    ).scalar_one_or_none()
    if report_id is None:
        return SnapshotOutcome(skipped=True, company_created=company_created)

    session.execute(pg_insert(CompanyProfile).values(report_id=report_id, **snapshot.profile))
    session.execute(pg_insert(CompanyStatus).values(report_id=report_id, **snapshot.status))
    session.execute(pg_insert(ZskAssessment).values(report_id=report_id, **snapshot.zsk))
    for activity in snapshot.activities:
        session.execute(
            pg_insert(ActivityCode).values(id=uuid.uuid4(), report_id=report_id, **activity)
        )
    for financial in snapshot.financials:
        session.execute(
            pg_insert(FinancialStatement).values(id=uuid.uuid4(), report_id=report_id, **financial)
        )
    for section in snapshot.availability:
        session.execute(pg_insert(SectionAvailability).values(report_id=report_id, **section))

    diagnostics = list(snapshot.diagnostics)
    if ogrn_conflicts:
        diagnostics.append(
            diagnostic(
                WarningCode.AGGREGATE_MISMATCH,
                "this snapshot reports a different OGRN than the stored company; "
                "the stored value is kept and neither is corrected",
                severity=WarningSeverity.WARNING,
                source_path="/baseInfo/ogrn",
                kind="company_ogrn_conflict",
                snapshot_ogrn=snapshot.ogrn,
            )
        )
    for item in diagnostics:
        _insert_warning(
            session,
            batch_id=batch_id,
            report_id=report_id,
            source_record_id=snapshot.source_record_id,
            item=item,
        )

    return SnapshotOutcome(
        inserted=True,
        company_created=company_created,
        activities=len(snapshot.activities),
        financials=len(snapshot.financials),
        availability=len(snapshot.availability),
        warnings=len(diagnostics),
        diagnostics=tuple(diagnostics),
    )


def finish_batch(
    session: Session,
    *,
    batch_id: UUID,
    imported: int,
    skipped: int,
    failed: int,
    counts: dict[str, Any],
) -> None:
    """Record how the run ended on the batch row.

    The counts describe the run that just finished. On a re-run of the same
    file they are overwritten rather than accumulated: "0 imported, 100 already
    present" is the true statement about that run, and adding it to the first
    run's numbers would state something that never happened.
    """
    batch = session.get(ImportBatch, batch_id)
    if batch is None:  # pragma: no cover - the row was just created or selected
        raise LookupError(f"import batch {batch_id} disappeared during the run")
    batch.imported_at = datetime.now(tz=UTC)
    batch.imported_count = imported
    batch.skipped_count = skipped
    batch.failed_count = failed
    batch.counts_jsonb = counts


def stored_row_counts(session: Session, tables: Sequence[Any]) -> dict[str, int]:
    """Count the rows of the given mapped tables, for before/after evidence."""
    return {
        str(table.__tablename__): session.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
        for table in tables
    }
