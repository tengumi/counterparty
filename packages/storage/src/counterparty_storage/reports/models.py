"""Mapped tables of the ``reports`` schema.

Scope of this revision is the first vertical only: the import batch, the
company, the report snapshot and the report entities that hang directly off a
snapshot's identity, status, activity, financial and completeness sections.
Sections that are not mapped yet (proceedings, arbitration, procurement,
licenses, inspections, related entities, branches, contacts, tax systems, risk
signals, founders, coefficients) still reach the database inside
``report_snapshots.raw_jsonb`` and are recorded in ``section_availability``, so
nothing from the source is silently dropped before they get their own tables.

Rules encoded here:

* Missing, empty, zero, unavailable and unparsable are distinct states. A
  ``NULL`` column plus a ``section_availability`` row carries which one it was;
  a zero is a real reported number and never a stand-in for absence.
* ``zskRiskLevel`` is stored as the raw external value. No colour, level or
  score is recomputed from it here.
* Every child row carries ``report_id`` and the RFC 6901 ``source_path`` it came
  from, so an evidence reference stays resolvable back to the source object.
* Money is ``NUMERIC``; float is never used.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..schemas import REPORTS_SCHEMA
from .enums import IngestionStatus, SourceState, WarningSeverity

_SOURCE_STATE = Enum(
    SourceState,
    name="source_state",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda enum: [member.value for member in enum],
)
_INGESTION_STATUS = Enum(
    IngestionStatus,
    name="ingestion_status",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda enum: [member.value for member in enum],
)
_WARNING_SEVERITY = Enum(
    WarningSeverity,
    name="warning_severity",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda enum: [member.value for member in enum],
)


class ReportsBase(Base):
    """Abstract base pinning every mapped table to the ``reports`` schema."""

    __abstract__ = True


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class ImportBatch(ReportsBase):
    """One execution of the import script against one source file."""

    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_import_batches_sha256"),
        CheckConstraint("record_count >= 0", name="record_count_non_negative"),
        {"schema": REPORTS_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    file_name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    """Digest of the source file bytes, so a snapshot stays tied to its origin."""

    schema_fingerprint: Mapped[str | None] = mapped_column(String(64))
    """Digest of the observed source shape; a change means the source drifted."""

    parser_version: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    imported_at: Mapped[datetime | None] = mapped_column()
    """Set when the batch finished; ``NULL`` while it is still running."""

    record_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    """Records recognized as an already ingested snapshot hash."""

    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    counts_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    """Per-section counts of the import report; not a substitute for warnings."""


class Company(ReportsBase):
    """A counterparty identified by its INN across snapshots."""

    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("inn", name="uq_companies_inn"),
        {"schema": REPORTS_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    inn: Mapped[str] = mapped_column(String(12))
    """Stored as a string; a checksum mismatch is reported, never silently fixed."""

    ogrn: Mapped[str | None] = mapped_column(String(15))
    entity_type: Mapped[str | None] = mapped_column(Text)
    """Left ``NULL`` unless the source confirms it; never guessed from the INN length."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReportSnapshot(ReportsBase):
    """One immutable provided report for one company at one source date."""

    __tablename__ = "report_snapshots"
    __table_args__ = (
        UniqueConstraint("company_id", "hash", name="uq_report_snapshots_company_id_hash"),
        Index("ix_report_snapshots_company_id_source_report_at", "company_id", "source_report_at"),
        Index("ix_report_snapshots_batch_id", "batch_id"),
        {"schema": REPORTS_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.companies.id", ondelete="RESTRICT")
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.import_batches.id", ondelete="RESTRICT")
    )
    source_record_id: Mapped[str] = mapped_column(Text)
    """Canonical rendering of the source ``_id``; in this file a composite key."""

    source_record_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB)
    """The raw ``_id`` object, kept so identity survives a change of encoding."""

    source_report_at: Mapped[datetime] = mapped_column()
    """``report.reportDate`` as the exact instant; not the financial year."""

    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    hash: Mapped[str] = mapped_column(String(64))
    """Digest of the canonical snapshot payload; re-importing it is a no-op."""

    raw_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB)
    """The whole ``report`` object. JSONB does not preserve source key order."""

    ingestion_status: Mapped[IngestionStatus] = mapped_column(_INGESTION_STATUS)


class CompanyProfile(ReportsBase):
    """Identity attributes as reported by one snapshot."""

    __tablename__ = "company_profiles"
    __table_args__ = ({"schema": REPORTS_SCHEMA},)

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.report_snapshots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    short_name: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str | None] = mapped_column(Text)
    kpp: Mapped[str | None] = mapped_column(String(9))
    okpo: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(Text)
    """A single reported string; not parsed into structured address parts."""

    registration_date: Mapped[datetime | None] = mapped_column()
    """``registrationInfo.registrationDate``. Kept as the exact instant because
    the source encodes local midnights at more than one UTC offset, so a
    calendar date cannot be derived without guessing a timezone."""

    years_from_registration: Mapped[int | None] = mapped_column(Integer)
    email: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    company_size: Mapped[str | None] = mapped_column(Text)
    """Reported size wording, stored raw; absence is not "small"."""

    bank_risk_raw: Mapped[str | None] = mapped_column(Text)
    """``baseInfo.riskLevel`` exactly as provided; no rescoring here."""

    extra_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    """Remainder of ``baseInfo``; a column is still required for anything used
    by filters or calculations."""


class CompanyStatus(ReportsBase):
    """Registry status of the company at the snapshot date."""

    __tablename__ = "company_statuses"
    __table_args__ = ({"schema": REPORTS_SCHEMA},)

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.report_snapshots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status_raw: Mapped[str | None] = mapped_column(Text)
    status_date: Mapped[datetime | None] = mapped_column()
    """``status.date`` as the exact instant, for the reason given on
    :attr:`CompanyProfile.registration_date`."""

    reason_raw: Mapped[str | None] = mapped_column(Text)
    """``status.reasonName``; present on only a few records."""

    extra_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ActivityCode(ReportsBase):
    """One declared OKVED activity, main or secondary."""

    __tablename__ = "activity_codes"
    __table_args__ = (
        UniqueConstraint("report_id", "ordinal", name="uq_activity_codes_report_id_ordinal"),
        Index("ix_activity_codes_report_id", "report_id"),
        {"schema": REPORTS_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.report_snapshots.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    """Position in the source; the main activity is ordinal 0."""

    code: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean)
    source_path: Mapped[str] = mapped_column(Text)


class FinancialStatement(ReportsBase):
    """Reported financial figures for one year of one snapshot."""

    __tablename__ = "financial_statements"
    __table_args__ = (
        UniqueConstraint("report_id", "year", name="uq_financial_statements_report_id_year"),
        Index("ix_financial_statements_report_id_year", "report_id", "year"),
        CheckConstraint("year BETWEEN 1900 AND 2200", name="year_in_range"),
        {"schema": REPORTS_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.report_snapshots.id", ondelete="CASCADE")
    )
    year: Mapped[int] = mapped_column(Integer)
    """``common.year``. The snapshot date is a different thing and never
    substitutes for it; array position does not imply the latest period."""

    ordinal: Mapped[int] = mapped_column(Integer)
    """Position inside ``finReports``, kept only to rebuild the source path."""

    proceeds: Mapped[Decimal | None] = mapped_column()
    profit: Mapped[Decimal | None] = mapped_column()
    total_assets: Mapped[Decimal | None] = mapped_column()
    current_assets: Mapped[Decimal | None] = mapped_column()
    stocks: Mapped[Decimal | None] = mapped_column()
    receivables: Mapped[Decimal | None] = mapped_column()
    cash: Mapped[Decimal | None] = mapped_column()
    """``assets.currentAssets.bankroll``."""

    noncurrent_assets: Mapped[Decimal | None] = mapped_column()
    fixed_assets: Mapped[Decimal | None] = mapped_column()
    balance_total_liabilities_side: Mapped[Decimal | None] = mapped_column()
    """``liabilities.totalLiabilities`` — the balance-sheet total of the
    liabilities side, NOT the amount of debt."""

    equity: Mapped[Decimal | None] = mapped_column()
    """``liabilities.capitals`` — reported equity, not the share capital.
    A negative value is not by itself proven insolvency."""

    long_term_total: Mapped[Decimal | None] = mapped_column()
    long_term_other: Mapped[Decimal | None] = mapped_column()
    short_term_total: Mapped[Decimal | None] = mapped_column()
    short_term_borrowed: Mapped[Decimal | None] = mapped_column()
    accounts_payable: Mapped[Decimal | None] = mapped_column()
    extra_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_path: Mapped[str] = mapped_column(Text)


class ZskAssessment(ReportsBase):
    """External ZSK signal, stored verbatim."""

    __tablename__ = "zsk_assessments"
    __table_args__ = ({"schema": REPORTS_SCHEMA},)

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.report_snapshots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    raw_value: Mapped[str | None] = mapped_column(Text)
    """``report.zskRiskLevel`` as provided. The methodology is closed: no colour
    or level is recomputed, and an unknown value is kept rather than dropped."""

    display_policy_version: Mapped[str] = mapped_column(Text)
    """Version of the presentation policy applied downstream, not a score."""

    source_path: Mapped[str] = mapped_column(Text)


class SectionAvailability(ReportsBase):
    """What the parser actually found for one section of one snapshot."""

    __tablename__ = "section_availability"
    __table_args__ = (
        CheckConstraint(
            "source_state <> 'present' OR record_count IS NOT NULL",
            name="present_requires_record_count",
        ),
        {"schema": REPORTS_SCHEMA},
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.report_snapshots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    section: Mapped[str] = mapped_column(Text, primary_key=True)
    source_state: Mapped[SourceState] = mapped_column(_SOURCE_STATE)
    record_count: Mapped[int | None] = mapped_column(Integer)
    """Records actually parsed. ``NULL`` for a missing or unparsable section;
    an empty aggregate object is ``present_empty`` and not a confirmed zero."""

    source_path: Mapped[str] = mapped_column(Text)
    warnings_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ImportWarning(ReportsBase):
    """One diagnostic raised while normalizing a snapshot.

    Unknown fields, unknown enum values and unparsable numbers are recorded
    here instead of being coerced into a default, so the import report can name
    exactly what was not understood.
    """

    __tablename__ = "import_warnings"
    __table_args__ = (
        Index("ix_import_warnings_batch_id", "batch_id"),
        Index("ix_import_warnings_report_id", "report_id"),
        {"schema": REPORTS_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.import_batches.id", ondelete="CASCADE")
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{REPORTS_SCHEMA}.report_snapshots.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[str | None] = mapped_column(Text)
    """Set when the record could not be stored as a snapshot at all."""

    severity: Mapped[WarningSeverity] = mapped_column(_WARNING_SEVERITY)
    code: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    details_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
