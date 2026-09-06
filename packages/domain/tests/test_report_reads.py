"""Shared report projections keep source states, filters and refs deterministic."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from counterparty_contracts import (
    Availability,
    GetReportSectionInput,
    ReportId,
    ReportSectionFilters,
    ReportSectionName,
)

from counterparty_domain.report_evidence import build_report_evidence
from counterparty_domain.report_reads import ReportReadData, build_company_overview
from counterparty_domain.report_sections import build_report_section


def report_data(raw: dict[str, Any]) -> ReportReadData:
    """Represent stored source availability without an importer or database."""
    return ReportReadData(
        report_id=uuid4(),
        company_id=uuid4(),
        inn="7449088645",
        ogrn=None,
        source_report_at=datetime(2026, 9, 5, tzinfo=UTC),
        ingested_at=datetime(2026, 9, 5, tzinfo=UTC),
        raw=raw,
        sections={
            key: {
                "source_state": "present_empty" if value in (None, [], {}) else "present",
                "record_count": len(value) if isinstance(value, list) else 1,
                "source_path": "/" + key,
            }
            for key, value in raw.items()
        },
    )


def test_financials_keep_zero_empty_missing_and_normalized_invalid() -> None:
    """A true zero is usable; null, omitted and failed normalized data are not."""
    data = report_data(
        {
            "finReports": [
                {
                    "common": {"year": 2025, "proceeds": 0, "profit": None},
                    "assets": {"totalAssets": "bad"},
                }
            ]
        }
    )
    data = replace(
        data, financials=[{"year": 2025, "source_path": "/finReports/0", "proceeds": Decimal(0)}]
    )
    section = build_report_section(
        data,
        GetReportSectionInput(
            report_id=ReportId(data.report_id), section=ReportSectionName.FINANCIALS
        ),
    )
    record = section.records[0]
    assert record.kind == "financial_period"
    assert (record.proceeds.value, record.proceeds.availability) == ("0", Availability.AVAILABLE)
    assert record.profit.availability is Availability.PRESENT_EMPTY
    assert record.equity.availability is Availability.MISSING
    assert record.total_assets.availability is Availability.INVALID
    assert build_company_overview(data).facts[0].value == record.proceeds.value


def test_cursor_filters_scope_and_stable_records() -> None:
    """Changing page size is supported; a different filter or snapshot is refused."""
    data = report_data(
        {"executionProceedings": [{"active": True, "amount": index} for index in range(3)]}
    )
    request = GetReportSectionInput(
        report_id=ReportId(data.report_id),
        section=ReportSectionName.EXECUTION_PROCEEDINGS,
        filters=ReportSectionFilters(active=True),
        limit=1,
    )
    first = build_report_section(data, request)
    second = build_report_section(
        data, request.model_copy(update={"limit": 2, "cursor": first.page.next_cursor})
    )
    assert len(second.records) == 2 and not second.page.has_more
    assert first.records[0].evidence_refs != second.records[0].evidence_refs
    with pytest.raises(ValueError, match="cursor"):
        build_report_section(
            data,
            request.model_copy(
                update={
                    "cursor": first.page.next_cursor,
                    "filters": ReportSectionFilters(active=False),
                }
            ),
        )


@pytest.mark.parametrize(
    "raw,expected", [({}, Availability.MISSING), ({"licenses": []}, Availability.PRESENT_EMPTY)]
)
def test_absent_and_empty_sections_are_not_confirmed_zero(
    raw: dict[str, Any], expected: Availability
) -> None:
    """Empty and missing sections have distinct DTO states and explanatory warnings."""
    data = report_data(raw)
    result = build_report_section(
        data,
        GetReportSectionInput(
            report_id=ReportId(data.report_id), section=ReportSectionName.LICENSES
        ),
    )
    assert result.availability is expected
    assert result.warnings
    assert result.total_records == (0 if expected is Availability.PRESENT_EMPTY else None)


def test_source_timestamp_keeps_offset_instant() -> None:
    """A late UTC instant from a positive offset must never become another date."""
    data = report_data({"foundersInfo": {"dateFrom": {"$date": "2024-01-15T00:00:00+03:00"}}})
    section = build_report_section(
        data,
        GetReportSectionInput(
            report_id=ReportId(data.report_id), section=ReportSectionName.FOUNDERS
        ),
    )
    assert section.facts[0].value_type.value == "string"
    assert section.facts[0].value == "2024-01-14T21:00:00+00:00"


def test_status_arbitration_uses_actual_source_keys_and_raw_status() -> None:
    """The source misspelling and pf/df keys must not turn known amounts missing."""
    from counterparty_contracts import PartyRole

    data = report_data(
        {
            "arbitrationByStatus": {
                "plaintiffArbitration": {
                    "plaintiffArbitrationFinished": {"pfCount": 1, "pfAmount": 957189}
                },
                "defandantArbitration": {
                    "defandantArbitrationPending": {"dpCount": 0, "dpAmount": 0}
                },
            }
        }
    )
    request = GetReportSectionInput(
        report_id=ReportId(data.report_id),
        section=ReportSectionName.ARBITRATION,
        filters=ReportSectionFilters(role=PartyRole.DEFENDANT, status_raw="Pending"),
    )
    result = build_report_section(data, request)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.kind == "arbitration_aggregate"
    assert record.count.value == 0 and record.amount.value == "0"
    assert record.amount.evidence_refs[0].endswith("/defandantArbitrationPending/dpAmount")


def test_malformed_source_record_is_invalid_not_empty() -> None:
    """Unreadable array elements cannot silently disappear from a section."""
    data = report_data({"licenses": [False]})
    result = build_report_section(
        data,
        GetReportSectionInput(
            report_id=ReportId(data.report_id), section=ReportSectionName.LICENSES
        ),
    )
    assert result.availability is Availability.INVALID
    assert result.total_records is None
    assert result.warnings[0].code.value == "parse_failed"


def test_empty_status_aggregate_is_not_missing_or_zero() -> None:
    """An explicitly empty source status aggregate retains present_empty facts."""
    data = report_data(
        {"arbitrationByStatus": {"plaintiffArbitration": {"plaintiffArbitrationFinished": {}}}}
    )
    result = build_report_section(
        data,
        GetReportSectionInput(
            report_id=ReportId(data.report_id), section=ReportSectionName.ARBITRATION
        ),
    )
    record = result.records[0]
    assert record.kind == "arbitration_aggregate"
    assert record.count.availability is Availability.PRESENT_EMPTY
    assert record.amount.value is None
    assert record.count.evidence_refs == record.evidence_refs
    assert result.warnings[0].code.value == "partial_data"


def test_rest_empty_filters_and_mcp_omitted_filters_share_cursor() -> None:
    """Equivalent REST and MCP requests yield the exact same continuation token."""
    data = report_data({"licenses": [{"number": "one"}, {"number": "two"}]})
    request = GetReportSectionInput(
        report_id=ReportId(data.report_id), section=ReportSectionName.LICENSES, limit=1
    )
    mcp = build_report_section(data, request)
    rest = build_report_section(
        data, request.model_copy(update={"filters": ReportSectionFilters()})
    )
    assert mcp == rest


@pytest.mark.parametrize("suffix", ["", "/assets/currentAssets/stocks"])
def test_evidence_keeps_old_financial_period_outside_overview(suffix: str) -> None:
    """An exact old source ref retains its validated year, regardless of array order."""
    old = {"common": {"year": 2021, "proceeds": 0}, "assets": {"currentAssets": {"stocks": 0}}}
    data = report_data({"finReports": [old, {"common": {"year": 2025, "proceeds": 50}}]})
    data = replace(
        data,
        financials=[
            {
                "year": 2021,
                "source_path": "/finReports/0",
                "proceeds": Decimal(0),
                "stocks": Decimal(0),
            },
            {"year": 2025, "source_path": "/finReports/1", "proceeds": Decimal(50)},
        ],
    )
    ref = f"report:{data.report_id}:/finReports/0{suffix}"
    assert all(ref not in fact.evidence_refs for fact in build_company_overview(data).facts)
    result = build_report_evidence(data, ref)
    assert result is not None
    assert result.evidence.period == 2021
    assert result.evidence.source_path == f"/finReports/0{suffix}"
    assert result.value == (0 if suffix else old)


def test_evidence_does_not_borrow_report_date_for_unknown_period() -> None:
    """A source without a typed financial period keeps the period unknown."""
    data = report_data({"foundersInfo": {"shareCapital": 10000}})
    result = build_report_evidence(data, f"report:{data.report_id}:/foundersInfo/shareCapital")
    assert result is not None
    assert result.evidence.period is None
    assert result.value == 10000
