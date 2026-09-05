"""Report DTOs: raw signals, section completeness and the Specs fixture."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from counterparty_contracts import (
    SECTION_RECORD_KINDS,
    SECTION_SOURCE_KEYS,
    ZSK_CONFIRMED_DISPLAY_LEVELS,
    Activity,
    ArbitrationAggregate,
    ArbitrationAggregation,
    Availability,
    BankRiskAssessment,
    CompanyId,
    CompanyIdentity,
    CompanyOverview,
    CompanyStatusView,
    Comparison,
    ComparisonCriterion,
    ComparisonRow,
    ComparisonRowStatus,
    DisplayLevel,
    EvidenceKind,
    EvidenceRef,
    FactValue,
    FinancialPeriod,
    PageInfo,
    PartyRole,
    Proceeding,
    ProjectComparison,
    ProjectId,
    ReportId,
    ReportIdentity,
    ReportSection,
    ReportSectionName,
    SectionAvailabilityView,
    ValueType,
    YearPolicy,
    ZskAssessment,
    parse_decimal_string,
)

FIXTURE_REPORT_ID = ReportId(UUID("00000000-0000-4000-8000-000000000010"))
FIXTURE_COMPANY_ID = CompanyId(UUID("00000000-0000-4000-8000-000000000011"))
SNAPSHOT_AT = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)


def money_fact(key: str, value: str | None, ref: str) -> FactValue:
    """Build an available monetary fact, or a missing one when value is None."""
    if value is None:
        return FactValue(
            key=key, label=key, value_type=ValueType.DECIMAL, availability=Availability.MISSING
        )
    return FactValue(
        key=key,
        label=key,
        value=value,
        value_type=ValueType.DECIMAL,
        currency="RUB",
        period=2025,
        availability=Availability.AVAILABLE,
        evidence_refs=[ref],
    )


def fixture_period() -> FinancialPeriod:
    """The Specs §10 financial fixture for INN 7449088645."""
    return FinancialPeriod(
        year=2025,
        proceeds=money_fact("proceeds", "74586000", "ev-proceeds"),
        profit=money_fact("profit", None, ""),
        total_assets=money_fact("total_assets", None, ""),
        equity=money_fact("equity", "-300000", "ev-capitals"),
        cash=money_fact("cash", "355000", "ev-bankroll"),
        receivables=money_fact("receivables", None, ""),
        accounts_payable=money_fact("accounts_payable", None, ""),
        evidence_refs=["ev-period-0"],
    )


def report_field_ref(ref_id: str, source_path: str) -> EvidenceRef:
    """Build a resolvable report-field evidence reference."""
    return EvidenceRef(
        id=ref_id,
        kind=EvidenceKind.REPORT_FIELD,
        report_id=FIXTURE_REPORT_ID,
        company_id=FIXTURE_COMPANY_ID,
        source_path=source_path,
        period=2025,
    )


def test_fixture_values_and_source_paths_resolve() -> None:
    """The documented figures keep their exact decimals and JSON Pointers."""
    period = fixture_period()
    assert period.year == 2025
    assert parse_decimal_string(str(period.proceeds.value)) == Decimal("74586000")
    assert parse_decimal_string(str(period.equity.value)) == Decimal("-300000")
    assert parse_decimal_string(str(period.cash.value)) == Decimal("355000")

    refs = {
        "ev-proceeds": "/finReports/0/common/proceeds",
        "ev-capitals": "/finReports/0/liabilities/capitals",
        "ev-bankroll": "/finReports/0/assets/currentAssets/bankroll",
    }
    for ref_id, path in refs.items():
        assert report_field_ref(ref_id, path).source_path == path


def test_negative_equity_is_a_reportable_value() -> None:
    """Reported capital below zero is data, not a parse failure."""
    assert fixture_period().equity.is_available


def test_missing_financial_figure_is_not_a_zero() -> None:
    """A figure the snapshot never carried stays missing."""
    period = fixture_period()
    assert period.profit.availability is Availability.MISSING
    assert period.profit.value is None


def test_financial_facts_must_be_keyed_as_their_field() -> None:
    """A figure cannot be filed under another field's name."""
    payload = fixture_period().model_dump(mode="json")
    payload["cash"] = money_fact("proceeds", "1", "ev-x").model_dump(mode="json")
    with pytest.raises(ValidationError, match="is keyed"):
        FinancialPeriod.model_validate(payload)


def test_additional_financial_facts_are_whitelisted() -> None:
    """Only known reported columns may ride along as extra figures."""
    period = fixture_period()
    payload = period.model_dump(mode="json")
    payload["additional_facts"] = [
        money_fact("stocks", "1000", "ev-stocks").model_dump(mode="json")
    ]
    assert FinancialPeriod.model_validate(payload).additional_facts[0].key == "stocks"
    payload["additional_facts"] = [money_fact("ebitda", "1000", "ev-x").model_dump(mode="json")]
    with pytest.raises(ValidationError, match="unknown additional financial fact"):
        FinancialPeriod.model_validate(payload)


def zsk(raw: str | None, level: DisplayLevel, note: str | None, available: bool) -> ZskAssessment:
    """Build a ZSK assessment with an explicit availability."""
    return ZskAssessment(
        raw_value=raw,
        display_level=level,
        display_note=note,
        policy_version="1",
        availability=Availability.AVAILABLE if available else Availability.MISSING,
        evidence_refs=["ev-zsk"] if available else [],
    )


def test_confirmed_zsk_mapping_is_the_only_favourable_one() -> None:
    """Only a confirmed token may be presented as anything but neutral."""
    assert ZSK_CONFIRMED_DISPLAY_LEVELS["GREEN"] is DisplayLevel.POSITIVE
    assert zsk("GREEN", DisplayLevel.POSITIVE, None, True).display_level is DisplayLevel.POSITIVE
    with pytest.raises(ValidationError, match="confirmed policy"):
        zsk("YELLOW", DisplayLevel.POSITIVE, "note", True)


@pytest.mark.parametrize("raw", ["YELLOW", "RED", "PURPLE", "unmapped-value"])
def test_unmapped_zsk_token_parses_neutrally_with_a_note(raw: str) -> None:
    """An unknown value neither breaks parsing nor becomes a default."""
    assessment = zsk(raw, DisplayLevel.NEUTRAL, "Отображение требует уточнения", True)
    assert assessment.raw_value == raw
    assert assessment.display_level is DisplayLevel.NEUTRAL


def test_neutral_zsk_must_explain_itself() -> None:
    """A neutral colour without an explanation is not publishable."""
    with pytest.raises(ValidationError, match="explanatory note"):
        zsk("RED", DisplayLevel.NEUTRAL, None, True)


def test_unavailable_zsk_carries_no_raw_value() -> None:
    """An absent signal cannot also claim a raw token."""
    with pytest.raises(ValidationError, match="must not carry a raw value"):
        zsk("GREEN", DisplayLevel.POSITIVE, None, False)


def test_unavailable_bank_risk_is_presented_neutrally() -> None:
    """A missing bank signal is never shown as a favourable one."""
    with pytest.raises(ValidationError, match="presented neutrally"):
        BankRiskAssessment(
            label="Нет данных",
            display_level=DisplayLevel.POSITIVE,
            availability=Availability.MISSING,
        )


def test_present_empty_section_is_not_a_confirmed_zero() -> None:
    """An empty container is reported as such, with absence unconfirmed."""
    entry = SectionAvailabilityView(
        section=ReportSectionName.FINANCIALS,
        availability=Availability.PRESENT_EMPTY,
        record_count=0,
    )
    assert not entry.confirms_absence

    with pytest.raises(ValidationError, match="no record count"):
        SectionAvailabilityView(
            section=ReportSectionName.FINANCIALS,
            availability=Availability.MISSING,
            record_count=0,
        )


def test_every_section_declares_its_source_keys_and_record_types() -> None:
    """No section can be added without saying where it came from."""
    assert set(SECTION_SOURCE_KEYS) == set(ReportSectionName)
    assert set(SECTION_RECORD_KINDS) == set(ReportSectionName)
    assert SECTION_SOURCE_KEYS[ReportSectionName.ARBITRATION] == (
        "arbitrationByStatus",
        "arbitrationCases",
    )


def test_source_keys_cover_the_imported_sections() -> None:
    """The public sections account for every source key the importer knows."""
    imported = {
        "baseInfo",
        "status",
        "kindsOfActivityInfo",
        "zskRiskLevel",
        "reputationalRisks",
        "arbitrationByStatus",
        "arbitrationCases",
        "executionProceedings",
        "procurements",
        "finReports",
        "coefficient",
        "foundersInfo",
        "taxSystem",
        "phones",
        "licenses",
        "inspections",
        "relatedCompanies",
        "branchesInfo",
    }
    covered = {key for keys in SECTION_SOURCE_KEYS.values() for key in keys}
    assert imported <= covered


def section(**overrides: object) -> ReportSection:
    """Build an available financials section, overriding single fields."""
    payload: dict[str, object] = {
        "report_id": FIXTURE_REPORT_ID,
        "section": ReportSectionName.FINANCIALS,
        "availability": Availability.AVAILABLE,
        "records": [fixture_period().model_dump(mode="json")],
        "page": PageInfo(limit=20, has_more=False),
        "rule_version": "1",
    }
    payload.update(overrides)
    return ReportSection.model_validate(payload)


def test_section_accepts_only_its_own_record_type() -> None:
    """The record union is narrowed per section, not left as free JSON."""
    assert isinstance(section().records[0], FinancialPeriod)
    activity = Activity(code="46.90", description="Торговля", is_primary=True, evidence_refs=["e"])
    with pytest.raises(ValidationError, match="not a record of section financials"):
        section(records=[activity.model_dump(mode="json")])


def test_section_without_a_record_type_returns_no_records() -> None:
    """A section we have not typed yet cannot smuggle records through."""
    with pytest.raises(ValidationError, match="not a record of section coefficients"):
        section(section=ReportSectionName.COEFFICIENTS)


def test_unavailable_section_carries_no_records() -> None:
    """A missing section cannot also list what it found."""
    with pytest.raises(ValidationError, match="must not carry records"):
        section(availability=Availability.MISSING)


def test_proceeding_keeps_an_unknown_active_state_unknown() -> None:
    """A proceeding whose state was not reported is not a closed one."""
    proceeding = Proceeding(
        id=uuid4(),
        number="12345/24/74000-ИП",
        started_at=SNAPSHOT_AT,
        active=FactValue(
            key="active",
            label="Действующее",
            value_type=ValueType.BOOLEAN,
            availability=Availability.MISSING,
        ),
        amount=money_fact("amount", None, ""),
        evidence_refs=["ev-proceeding"],
    )
    assert proceeding.active.value is None
    assert proceeding.active.is_unknown


def arbitration(**overrides: object) -> ArbitrationAggregate:
    """Build a year-grouped arbitration aggregate."""
    payload: dict[str, object] = {
        "aggregation": ArbitrationAggregation.BY_YEAR,
        "role": PartyRole.DEFENDANT,
        "year": 2025,
        "count": FactValue(
            key="count",
            label="Дел",
            value=3,
            value_type=ValueType.INTEGER,
            availability=Availability.AVAILABLE,
            evidence_refs=["ev-arb"],
        ).model_dump(mode="json"),
        "amount": money_fact("amount", "1000000", "ev-arb").model_dump(mode="json"),
        "evidence_refs": ["ev-arb"],
    }
    payload.update(overrides)
    return ArbitrationAggregate.model_validate(payload)


def test_arbitration_aggregate_declares_exactly_one_grouping() -> None:
    """Year and status aggregates stay separable, so they are not double counted."""
    assert arbitration().year == 2025
    with pytest.raises(ValidationError, match="must not also claim a case status"):
        arbitration(case_status_raw="Finished")
    with pytest.raises(ValidationError, match="must carry its raw case status"):
        arbitration(aggregation=ArbitrationAggregation.BY_STATUS, year=None)


def overview(**overrides: object) -> CompanyOverview:
    """Build a minimal, valid company overview."""
    payload: dict[str, object] = {
        "company": CompanyIdentity(
            id=FIXTURE_COMPANY_ID, inn="7449088645", short_name="Компания Пример"
        ).model_dump(mode="json"),
        "report": ReportIdentity(
            id=FIXTURE_REPORT_ID, source_report_at=SNAPSHOT_AT, ingested_at=SNAPSHOT_AT
        ).model_dump(mode="json"),
        "status": CompanyStatusView(
            raw_value="Действующее",
            label="Действующее",
            availability=Availability.AVAILABLE,
            status_date=SNAPSHOT_AT,
            evidence_refs=["ev-status"],
        ).model_dump(mode="json"),
        "bank_risk": BankRiskAssessment(
            raw_value="LOW",
            label="Низкий",
            display_level=DisplayLevel.POSITIVE,
            availability=Availability.AVAILABLE,
            evidence_refs=["ev-risk"],
        ).model_dump(mode="json"),
        "zsk": zsk("GREEN", DisplayLevel.POSITIVE, None, True).model_dump(mode="json"),
        "rule_version": "1",
    }
    payload.update(overrides)
    return CompanyOverview.model_validate(payload)


def test_overview_reports_the_snapshot_it_answers_from() -> None:
    """The card names its snapshot and how the data reached us."""
    card = overview()
    assert card.report.source_kind == "provided_snapshot"
    assert card.report.source_report_at == SNAPSHOT_AT


def test_overview_rejects_duplicate_fact_keys() -> None:
    """Two facts under one key would make the card ambiguous."""
    duplicate = money_fact("proceeds", "1", "ev-a").model_dump(mode="json")
    with pytest.raises(ValidationError, match="duplicate key"):
        overview(facts=[duplicate, duplicate])


def test_overview_lists_absent_sections_too() -> None:
    """Completeness includes what the snapshot did not carry."""
    card = overview(
        available_sections=[
            SectionAvailabilityView(
                section=ReportSectionName.LICENSES, availability=Availability.MISSING
            ).model_dump(mode="json")
        ]
    )
    assert card.available_sections[0].availability is Availability.MISSING


def comparison(**overrides: object) -> Comparison:
    """Build a two-company comparison over the default year policy."""
    payload: dict[str, object] = {
        "report_ids": [str(FIXTURE_REPORT_ID), str(uuid4())],
        "criteria": [ComparisonCriterion.FINANCIALS],
        "year_policy": YearPolicy.LATEST_AVAILABLE,
        "rule_version": "1",
    }
    payload.update(overrides)
    return Comparison.model_validate(payload)


def test_comparison_size_and_uniqueness() -> None:
    """Two to twenty distinct reports; no silent truncation of a bigger set."""
    assert len(comparison().report_ids) == 2
    with pytest.raises(ValidationError):
        comparison(report_ids=[str(FIXTURE_REPORT_ID)])
    with pytest.raises(ValidationError):
        comparison(report_ids=[str(uuid4()) for _ in range(21)])
    with pytest.raises(ValidationError, match="duplicate key"):
        comparison(report_ids=[str(FIXTURE_REPORT_ID), str(FIXTURE_REPORT_ID)])


def test_explicit_year_policy_requires_the_year() -> None:
    """An explicit policy names the year; the others must not pin one."""
    assert comparison(year_policy=YearPolicy.EXPLICIT, year=2025).year == 2025
    with pytest.raises(ValidationError, match="must name the year"):
        comparison(year_policy=YearPolicy.EXPLICIT)
    with pytest.raises(ValidationError, match="must not pin a year"):
        comparison(year=2025)


def test_comparison_has_no_winner_or_score() -> None:
    """The deterministic layer ranks nothing."""
    fields = set(Comparison.model_fields)
    assert not fields & {"winner_id", "score", "rating", "rank"}


def test_comparison_row_reports_partial_data_as_partial() -> None:
    """An incomplete row says so instead of looking like a bad number."""
    row = ComparisonRow(
        company=CompanyIdentity(id=FIXTURE_COMPANY_ID, inn="7449088645", short_name="Компания"),
        report=ReportIdentity(
            id=FIXTURE_REPORT_ID, source_report_at=SNAPSHOT_AT, ingested_at=SNAPSHOT_AT
        ),
        cells=[money_fact("proceeds", None, "")],
        status=ComparisonRowStatus.PARTIAL,
    )
    assert row.status is ComparisonRowStatus.PARTIAL


def test_project_comparison_keeps_proposal_facts_separate() -> None:
    """Workspace deal terms are a distinct field, not merged report facts."""
    project_comparison = ProjectComparison.model_validate(
        comparison().model_dump(mode="json")
        | {
            "project_id": str(ProjectId(uuid4())),
            "proposal_facts": [
                money_fact("advance", "1920000.00", "ev-advance").model_dump(mode="json")
            ],
        }
    )
    assert "proposal_facts" not in Comparison.model_fields
    assert project_comparison.proposal_facts[0].key == "advance"
