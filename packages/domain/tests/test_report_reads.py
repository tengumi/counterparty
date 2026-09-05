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
