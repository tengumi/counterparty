"""Pinned report bundles stay ordered, complete and isolated from newer snapshots."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from conftest import SnapshotFactory
from sqlalchemy.ext.asyncio import AsyncSession

from counterparty_storage.reports.enums import SourceState, WarningSeverity
from counterparty_storage.reports.models import (
    CompanyProfile,
    CompanyStatus,
    FinancialStatement,
    ImportWarning,
    ReportSnapshot,
    SectionAvailability,
    ZskAssessment,
)
from counterparty_storage.repositories.reports import ReportSnapshotReadRepository


async def test_report_read_bundle_preserves_requested_ids_and_child_rows(
    session: AsyncSession,
    new_snapshot: SnapshotFactory,
) -> None:
    """One batch keeps snapshot order, known zero and missing children distinct."""
    company_id, first = await new_snapshot("7449088645")
    _, second = await new_snapshot("7702070139")
    source = await session.get(ReportSnapshot, first)
    assert source is not None
    session.add_all(
        [
            CompanyProfile(report_id=first, short_name="Pinned"),
            CompanyStatus(report_id=first, status_raw="ACTIVE"),
            ZskAssessment(
                report_id=first,
                raw_value="UNKNOWN",
                display_policy_version="zsk-display/1",
                source_path="/zskRiskLevel",
            ),
            FinancialStatement(
                report_id=first,
                year=2025,
                ordinal=0,
                proceeds=Decimal(0),
                source_path="/finReports/0",
            ),
            FinancialStatement(
                report_id=first, year=2024, ordinal=1, proceeds=None, source_path="/finReports/1"
            ),
            SectionAvailability(
                report_id=first,
                section="finReports",
                source_state=SourceState.PRESENT,
                record_count=2,
                source_path="/finReports",
            ),
            SectionAvailability(
                report_id=first,
                section="licenses",
                source_state=SourceState.MISSING,
                record_count=None,
                source_path="/licenses",
            ),
            ImportWarning(
                batch_id=source.batch_id,
                report_id=first,
                severity=WarningSeverity.WARNING,
                code="source_missing",
                source_path="/licenses",
                message="Section missing",
            ),
        ]
    )
    await session.flush()
    session.expunge_all()
    repository = ReportSnapshotReadRepository(session)
    bundles = await repository.get_read_bundles([second, first, second, uuid4()])
    assert [bundle.snapshot.id for bundle in bundles] == [second, first]
    assert bundles[0].profile is None and not bundles[0].financials and not bundles[0].warnings
    loaded = bundles[1]
    assert loaded.company.id == company_id
    assert loaded.profile is not None and loaded.profile.short_name == "Pinned"
    assert loaded.status is not None and loaded.status.status_raw == "ACTIVE"
    assert loaded.zsk is not None and loaded.zsk.raw_value == "UNKNOWN"
    assert [(row.year, row.proceeds) for row in loaded.financials] == [
        (2024, None),
        (2025, Decimal(0)),
    ]
    assert [(row.section, row.source_state) for row in loaded.sections] == [
        ("finReports", SourceState.PRESENT),
        ("licenses", SourceState.MISSING),
    ]
    assert loaded.warnings[0].source_path == "/licenses"
    assert await repository.get_read_bundles([]) == []
    assert await repository.get_read_bundles([uuid4()]) == []
    assert not session.new and not session.dirty and not session.deleted


async def test_latest_tie_break_does_not_replace_pinned_bundle(
    session: AsyncSession,
    snapshot: tuple[UUID, UUID],
) -> None:
    """Latest uses the deterministic id tie-break, while a pin remains exact."""
    company_id, pinned = snapshot
    original = await session.get(ReportSnapshot, pinned)
    assert original is not None
    instant = datetime(2026, 9, 5, tzinfo=UTC)
    original.ingested_at = instant
    newer_id = uuid4()
    session.add(
        ReportSnapshot(
            id=newer_id,
            company_id=company_id,
            batch_id=original.batch_id,
            source_record_id="newer",
            source_record_jsonb={},
            source_report_at=original.source_report_at,
            ingested_at=instant,
            hash=uuid4().hex * 2,
            raw_jsonb={},
            ingestion_status=original.ingestion_status,
        )
    )
    await session.flush()
    repository = ReportSnapshotReadRepository(session)
    latest = await repository.latest_for_company(company_id)
    assert latest is not None and latest.id == max(pinned, newer_id)
    loaded = await repository.get_read_bundles([pinned])
    assert loaded[0].snapshot.id == pinned
