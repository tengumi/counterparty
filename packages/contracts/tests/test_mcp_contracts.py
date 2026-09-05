"""The read-only tool contract of the internal reports MCP service."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from counterparty_contracts import (
    Availability,
    BankRiskAssessment,
    CompanyId,
    CompanyIdentity,
    CompanyOverview,
    CompanyOverviewEnvelope,
    CompanyStatusView,
    CompareCompaniesInput,
    Comparison,
    ComparisonCriterion,
    ComparisonEnvelope,
    ContractWarning,
    DisplayLevel,
    ErrorCode,
    GetCompanyOverviewInput,
    GetReportSectionInput,
    McpStatus,
    PartyRole,
    ProjectComparison,
    ProjectId,
    ReportId,
    ReportIdentity,
    ReportSectionFilters,
    ReportSectionName,
    ToolError,
    WarningCode,
    YearPolicy,
    ZskAssessment,
)

SNAPSHOT_AT = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
REPORT_ID = ReportId(UUID("00000000-0000-4000-8000-0000000000a1"))
OTHER_REPORT_ID = ReportId(UUID("00000000-0000-4000-8000-0000000000a2"))
COMPANY_ID = CompanyId(UUID("00000000-0000-4000-8000-0000000000b1"))


def _overview() -> CompanyOverview:
    """Build a minimal valid overview payload."""
    return CompanyOverview(
        company=CompanyIdentity(id=COMPANY_ID, inn="7449088645", short_name="Компания Пример"),
        report=ReportIdentity(id=REPORT_ID, source_report_at=SNAPSHOT_AT, ingested_at=SNAPSHOT_AT),
        status=CompanyStatusView(
            raw_value="Действующее",
            label="Действующее",
            availability=Availability.AVAILABLE,
            evidence_refs=["ev-status"],
        ),
        bank_risk=BankRiskAssessment(
            raw_value="LOW",
            label="Низкий",
            display_level=DisplayLevel.POSITIVE,
            availability=Availability.AVAILABLE,
            evidence_refs=["ev-risk"],
        ),
        zsk=ZskAssessment(
            raw_value="GREEN",
            display_level=DisplayLevel.POSITIVE,
            policy_version="1",
            availability=Availability.AVAILABLE,
            evidence_refs=["ev-zsk"],
        ),
        rule_version="1",
    )


def _comparison(**overrides: Any) -> Comparison:
    """Build a two-company comparison."""
    payload: dict[str, Any] = {
        "report_ids": [REPORT_ID, OTHER_REPORT_ID],
        "criteria": [ComparisonCriterion.FINANCIALS],
        "year_policy": YearPolicy.LATEST_AVAILABLE,
        "rule_version": "1",
    }
    payload.update(overrides)
    return Comparison.model_validate(payload)


def test_ok_result_carries_data_and_names_its_sources() -> None:
    """A successful answer says which snapshots it was read from."""
    envelope = CompanyOverviewEnvelope(
        status=McpStatus.OK,
        data=_overview(),
        source_report_ids=[REPORT_ID],
        rule_version="1",
    )

    assert envelope.schema_version == "0.1"
    assert envelope.source_report_ids == [REPORT_ID]


def test_ok_result_may_not_also_report_an_error() -> None:
    """An outcome is one thing: success does not carry a failure with it."""
    with pytest.raises(ValidationError):
        CompanyOverviewEnvelope(
            status=McpStatus.OK,
            data=_overview(),
            errors=[ToolError(code=ErrorCode.SOURCE_MISSING, message="financials are absent")],
            rule_version="1",
        )


def test_not_found_carries_no_data_and_explains_itself() -> None:
    """An unknown company is an explained outcome, never an empty success."""
    envelope = CompanyOverviewEnvelope(
        status=McpStatus.NOT_FOUND,
        errors=[ToolError(code=ErrorCode.NOT_FOUND, message="the inn is not imported")],
        rule_version="1",
    )

    assert envelope.data is None
    with pytest.raises(ValidationError):
        CompanyOverviewEnvelope(status=McpStatus.NOT_FOUND, rule_version="1")
    with pytest.raises(ValidationError):
        CompanyOverviewEnvelope(status=McpStatus.UNAVAILABLE, data=_overview(), rule_version="1")


def test_partial_result_keeps_data_and_says_what_is_missing() -> None:
    """Incompleteness is reported, not turned into a smaller complete answer."""
    envelope = CompanyOverviewEnvelope(
        status=McpStatus.PARTIAL,
        data=_overview(),
        warnings=[
            ContractWarning(
                code=WarningCode.SOURCE_MISSING,
                message="the financials section is absent from the snapshot",
                source_path="/finReports",
            )
        ],
        source_report_ids=[REPORT_ID],
        rule_version="1",
    )

    assert envelope.warnings[0].code is WarningCode.SOURCE_MISSING


def test_comparison_envelope_refuses_workspace_terms() -> None:
    """The reports MCP has no workspace access and returns no proposal facts."""
    project_comparison = ProjectComparison(
        project_id=ProjectId(uuid4()),
        report_ids=[REPORT_ID, OTHER_REPORT_ID],
        criteria=[ComparisonCriterion.FINANCIALS],
        year_policy=YearPolicy.LATEST_AVAILABLE,
        rule_version="1",
    )

    with pytest.raises(ValidationError):
        ComparisonEnvelope(status=McpStatus.OK, data=project_comparison, rule_version="1")
    assert (
        ComparisonEnvelope(status=McpStatus.OK, data=_comparison(), rule_version="1").data
        is not None
    )


def test_comparison_result_has_no_winner_or_score() -> None:
    """The deterministic layer ranks nothing, so there is no field to hold it."""
    fields = set(Comparison.model_fields)

    assert not fields & {"winner_id", "score", "total_score", "rank"}


def test_overview_input_takes_exactly_one_selector() -> None:
    """A company is named by INN or by pinned report, never by both."""
    assert GetCompanyOverviewInput(inn="7449088645").report_id is None
    with pytest.raises(ValidationError):
        GetCompanyOverviewInput()
    with pytest.raises(ValidationError):
        GetCompanyOverviewInput(inn="7449088645", report_id=REPORT_ID)


def test_section_input_defaults_to_the_shared_page_limits() -> None:
    """Paging uses the shared defaults; an oversized page is refused."""
    request = GetReportSectionInput(report_id=REPORT_ID, section=ReportSectionName.FINANCIALS)

    assert request.limit == 20
    with pytest.raises(ValidationError):
        GetReportSectionInput(report_id=REPORT_ID, section=ReportSectionName.FINANCIALS, limit=101)


def test_filters_are_checked_against_the_section() -> None:
    """A filter a section cannot apply is an error, not an ignored key."""
    allowed = GetReportSectionInput(
        report_id=REPORT_ID,
        section=ReportSectionName.EXECUTION_PROCEEDINGS,
        filters=ReportSectionFilters(active=True),
    )

    assert allowed.filters is not None
    with pytest.raises(ValidationError, match="does not support filter"):
        GetReportSectionInput(
            report_id=REPORT_ID,
            section=ReportSectionName.LICENSES,
            filters=ReportSectionFilters(active=True),
        )
    with pytest.raises(ValidationError, match="does not support filter"):
        GetReportSectionInput(
            report_id=REPORT_ID,
            section=ReportSectionName.FINANCIALS,
            filters=ReportSectionFilters(role=PartyRole.DEFENDANT),
        )


def test_free_form_filter_is_refused() -> None:
    """No expression, column name or SQL reaches the query."""
    with pytest.raises(ValidationError):
        ReportSectionFilters.model_validate({"where": "1=1"})


def test_repeated_year_is_refused() -> None:
    """A year asked twice would double count its records."""
    with pytest.raises(ValidationError):
        ReportSectionFilters(years=[2025, 2025])


def test_comparison_input_holds_the_two_to_twenty_range() -> None:
    """Comparison covers two to twenty distinct companies."""
    assert (
        len(
            CompareCompaniesInput(
                report_ids=[REPORT_ID, OTHER_REPORT_ID],
                criteria=[ComparisonCriterion.FINANCIALS],
            ).report_ids
        )
        == 2
    )
    with pytest.raises(ValidationError):
        CompareCompaniesInput(report_ids=[REPORT_ID], criteria=[ComparisonCriterion.FINANCIALS])
    with pytest.raises(ValidationError):
        CompareCompaniesInput(
            report_ids=[ReportId(uuid4()) for _ in range(21)],
            criteria=[ComparisonCriterion.FINANCIALS],
        )
    with pytest.raises(ValidationError):
        CompareCompaniesInput(
            report_ids=[REPORT_ID, REPORT_ID], criteria=[ComparisonCriterion.FINANCIALS]
        )


def test_explicit_year_policy_names_its_year() -> None:
    """A pinned year is required exactly where the policy promises one."""
    with pytest.raises(ValidationError):
        CompareCompaniesInput(
            report_ids=[REPORT_ID, OTHER_REPORT_ID],
            criteria=[ComparisonCriterion.FINANCIALS],
            year_policy=YearPolicy.EXPLICIT,
        )
    with pytest.raises(ValidationError):
        CompareCompaniesInput(
            report_ids=[REPORT_ID, OTHER_REPORT_ID],
            criteria=[ComparisonCriterion.FINANCIALS],
            year_policy=YearPolicy.LATEST_AVAILABLE,
            year=2025,
        )


def test_criteria_stay_a_whitelist() -> None:
    """An invented criterion is refused rather than interpreted."""
    with pytest.raises(ValidationError):
        CompareCompaniesInput.model_validate(
            {"report_ids": [str(REPORT_ID), str(OTHER_REPORT_ID)], "criteria": ["overall_score"]}
        )
