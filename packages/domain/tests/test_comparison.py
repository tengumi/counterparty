"""Comparison policies keep periods, unknowns and input order explicit."""

from datetime import UTC, datetime
from uuid import uuid4

from counterparty_contracts import (
    Availability,
    BankRiskAssessment,
    CompanyId,
    CompanyIdentity,
    CompanyOverview,
    CompanyStatusView,
    ComparisonCriterion,
    ComparisonRowStatus,
    DisplayLevel,
    FactValue,
    ReportId,
    ReportIdentity,
    ValueType,
    YearPolicy,
    ZskAssessment,
)

from counterparty_domain import build_comparison_rows

NOW = datetime(2026, 9, 5, tzinfo=UTC)


def _overview(year: int | None, value: str | None = "0") -> CompanyOverview:
    report_id = uuid4()
    facts = []
    if year is not None:
        facts.append(
            FactValue(
                key=f"financials.{year}.proceeds",
                label="Выручка",
                value=value,
                value_type=ValueType.DECIMAL,
                period=year,
                availability=Availability.AVAILABLE if value is not None else Availability.MISSING,
                evidence_refs=[f"report:{report_id}:/finReports/0/common/proceeds"]
                if value is not None
                else [],
            )
        )
    return CompanyOverview(
        company=CompanyIdentity(
            id=CompanyId(uuid4()), inn=str(uuid4().int)[:10], short_name="Компания"
        ),
        report=ReportIdentity(id=ReportId(report_id), source_report_at=NOW, ingested_at=NOW),
        status=CompanyStatusView(
            raw_value="ACTIVE",
            label="ACTIVE",
            availability=Availability.AVAILABLE,
            evidence_refs=[f"report:{report_id}:/status/status"],
        ),
        bank_risk=BankRiskAssessment(
            raw_value="LOW",
            label="LOW",
            display_level=DisplayLevel.NEUTRAL,
            availability=Availability.AVAILABLE,
            evidence_refs=[f"report:{report_id}:/baseInfo/riskLevel"],
        ),
        zsk=ZskAssessment(
            raw_value="GREEN",
            display_level=DisplayLevel.POSITIVE,
            policy_version="zsk-display/1",
            availability=Availability.AVAILABLE,
            evidence_refs=[f"report:{report_id}:/zskRiskLevel"],
        ),
        facts=facts,
        rule_version="overview/1",
    )


def test_latest_available_keeps_request_order_and_zero() -> None:
    """Different latest years are named, and a reported zero stays available."""
    first, second = _overview(2024), _overview(2025, "10")
    rows, warnings = build_comparison_rows(
        [second.report.id, first.report.id],
        [first, second],
        [ComparisonCriterion.FINANCIALS],
        year_policy=YearPolicy.LATEST_AVAILABLE,
    )
    assert [row.report.id for row in rows] == [second.report.id, first.report.id]
    assert rows[1].cells[0].value == "0"
    assert warnings[0].code.value == "period_mismatch"


def test_common_latest_reports_incomparable_rows_as_unavailable() -> None:
    """No shared year yields explicit unavailable rows instead of borrowed data."""
    first, second = _overview(2024), _overview(2025)
    rows, warnings = build_comparison_rows(
        [first.report.id, second.report.id],
        [first, second],
        [ComparisonCriterion.FINANCIALS],
        year_policy=YearPolicy.COMMON_LATEST,
    )
    assert all(row.status is ComparisonRowStatus.UNAVAILABLE for row in rows)
    assert warnings[0].code.value == "not_comparable"


def test_missing_value_is_partial_not_zero_or_a_rank() -> None:
    """One missing cell makes the row partial without fabricating a value."""
    item = _overview(2025, None)
    rows, _ = build_comparison_rows(
        [item.report.id],
        [item],
        [ComparisonCriterion.STATUS, ComparisonCriterion.FINANCIALS],
        year_policy=YearPolicy.EXPLICIT,
        year=2025,
    )
    assert rows[0].status is ComparisonRowStatus.PARTIAL
    assert rows[0].cells[1].value is None
