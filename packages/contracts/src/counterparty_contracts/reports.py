"""DTOs of the provided report and of the deterministic layer over it.

Everything here describes a snapshot the product received; nothing is scored,
rewritten or filled in. Three rules shape the whole module:

* a non-value keeps its reason (:class:`FactValue`), so *missing*, a confirmed
  empty container, an unparsable value and a real zero stay distinguishable;
* an external assessment (``riskLevel``, ``zskRiskLevel``) is transported as
  the raw token, and an unknown token neither breaks parsing nor collapses
  into a favourable default;
* every record carries at least one resolvable evidence reference.

Source ``$date`` values remain exact instants; the calendar day is derived at
the display layer, where the applied timezone is known.
"""

from collections.abc import Iterable
from types import MappingProxyType
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from .base import ContractModel, NonEmptyString, SchemaVersion, UtcDatetime
from .diagnostics import ContractWarning
from .enums import (
    ArbitrationAggregation,
    Availability,
    ComparisonCriterion,
    ComparisonRowStatus,
    DisplayLevel,
    EvidenceKind,
    PartyRole,
    ReportSectionName,
    RiskSignalPolarity,
    ValueType,
    YearPolicy,
)
from .evidence import EvidenceRef
from .facts import FactValue
from .identifiers import CompanyId, EvidenceRefId, ProjectId, ReportId
from .pagination import PageInfo
from .values import FiscalYear, NonNegativeCount

__all__ = [
    "FINANCIAL_ADDITIONAL_FACT_KEYS",
    "MAX_COMPARISON_COMPANIES",
    "MIN_COMPARISON_COMPANIES",
    "SECTION_RECORD_KINDS",
    "SECTION_SOURCE_KEYS",
    "ZSK_CONFIRMED_DISPLAY_LEVELS",
    "Activity",
    "ArbitrationAggregate",
    "BankRiskAssessment",
    "CompanyIdentity",
    "CompanyOverview",
    "CompanyStatusView",
    "Comparison",
    "ComparisonRow",
    "FinancialPeriod",
    "Inspection",
    "License",
    "Proceeding",
    "ProcurementAggregate",
    "ProfileRecord",
    "ProjectComparison",
    "RelatedEntity",
    "ReportEvidence",
    "ReportIdentity",
    "ReportRecord",
    "ReportSection",
    "RiskSignal",
    "ZskAssessment",
]

MIN_COMPARISON_COMPANIES = 2
MAX_COMPARISON_COMPANIES = 20

GroundedEvidenceRefs = Annotated[list[EvidenceRefId], Field(min_length=1)]
"""Evidence of a reported record. A record without provenance is not publishable."""

SECTION_SOURCE_KEYS: MappingProxyType[ReportSectionName, tuple[str, ...]] = MappingProxyType(
    {
        ReportSectionName.PROFILE: ("baseInfo",),
        ReportSectionName.STATUS: ("status",),
        ReportSectionName.ACTIVITIES: ("kindsOfActivityInfo",),
        ReportSectionName.FINANCIALS: ("finReports",),
        ReportSectionName.COEFFICIENTS: ("coefficient",),
        ReportSectionName.FOUNDERS: ("foundersInfo",),
        ReportSectionName.TAX_SYSTEMS: ("taxSystem",),
        ReportSectionName.CONTACTS: ("phones",),
        ReportSectionName.EXECUTION_PROCEEDINGS: ("executionProceedings",),
        ReportSectionName.ARBITRATION: ("arbitrationByStatus", "arbitrationCases"),
        ReportSectionName.PROCUREMENTS: ("procurements",),
        ReportSectionName.LICENSES: ("licenses",),
        ReportSectionName.INSPECTIONS: ("inspections",),
        ReportSectionName.RELATED_COMPANIES: ("relatedCompanies",),
        ReportSectionName.BRANCHES: ("branchesInfo",),
        ReportSectionName.RISK_SIGNALS: ("reputationalRisks",),
        ReportSectionName.ZSK: ("zskRiskLevel",),
    }
)
"""Source keys of ``report`` each public section was parsed from.

``arbitration`` deliberately covers two keys: status and year aggregates are
two views of the same cases and must not be added together.
"""

ZSK_CONFIRMED_DISPLAY_LEVELS: MappingProxyType[str, DisplayLevel] = MappingProxyType(
    {"GREEN": DisplayLevel.POSITIVE}
)
"""Raw ZSK tokens whose presentation is confirmed.

The methodology is closed. ``YELLOW`` and ``RED`` have no confirmed mapping
yet, so they are shown neutrally with an explanatory note, and an unknown token
is treated the same way rather than being dropped or read as ``GREEN``.
"""


class CompanyIdentity(ContractModel):
    """Who the counterparty is, as identified by the snapshot."""

    id: CompanyId
    inn: NonEmptyString
    ogrn: NonEmptyString | None = None
    short_name: NonEmptyString
    full_name: NonEmptyString | None = None


class ReportIdentity(ContractModel):
    """Which snapshot the answer was read from, and how old it is."""

    id: ReportId
    source_report_at: UtcDatetime
    """``report.reportDate``: the instant the provider dated the snapshot."""

    ingested_at: UtcDatetime
    source_kind: Literal["provided_snapshot"] = "provided_snapshot"


class CompanyStatusView(ContractModel):
    """Registry status of the company at the snapshot date."""

    raw_value: NonEmptyString | None = None
    """``report.status.status`` verbatim; an unknown wording is kept as is."""

    label: NonEmptyString
    availability: Availability
    status_date: UtcDatetime | None = None
    """``report.status.date`` as an exact instant, not a calendar day."""

    reason_raw: NonEmptyString | None = None
    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_availability(self) -> Self:
        """Tie the presence of a raw value to the declared availability."""
        _validate_raw_assessment(self.raw_value, self.availability)
        return self


class BankRiskAssessment(ContractModel):
    """The bank's own risk signal, transported without rescoring."""

    raw_value: NonEmptyString | None = None
    """``report.baseInfo.riskLevel`` verbatim."""

    label: NonEmptyString
    display_level: DisplayLevel
    availability: Availability
    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_availability(self) -> Self:
        """Require a neutral presentation when the signal is not available."""
        _validate_raw_assessment(self.raw_value, self.availability)
        if self.raw_value is None and self.display_level is not DisplayLevel.NEUTRAL:
            raise ValueError("an unavailable bank risk signal must be presented neutrally")
        return self


class ZskAssessment(ContractModel):
    """The external ZSK signal and the presentation policy applied to it."""

    raw_value: NonEmptyString | None = None
    """``report.zskRiskLevel`` verbatim, including a token we do not know."""

    display_level: DisplayLevel
    display_note: NonEmptyString | None = None
    """Why the signal is shown the way it is; required whenever the raw token
    has no confirmed mapping, so a neutral colour is never left unexplained."""

    policy_version: NonEmptyString
    availability: Availability
    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        """Apply the confirmed mapping and forbid a favourable default."""
        _validate_raw_assessment(self.raw_value, self.availability)
        expected = (
            DisplayLevel.NEUTRAL
            if self.raw_value is None
            else ZSK_CONFIRMED_DISPLAY_LEVELS.get(self.raw_value, DisplayLevel.NEUTRAL)
        )
        if self.display_level is not expected:
            raise ValueError(
                "zsk display level must follow the confirmed policy; "
                f"{self.raw_value!r} is presented as {expected.value}"
            )
        if self.display_level is DisplayLevel.NEUTRAL and self.display_note is None:
            raise ValueError("a neutral zsk presentation must carry an explanatory note")
        return self


def _validate_raw_assessment(raw_value: str | None, availability: Availability) -> None:
    """Keep a raw external value and its declared availability consistent.

    Raises:
        ValueError: If an available assessment carries no raw value, or an
            unavailable one carries a value it should not have.
    """
    if availability is Availability.AVAILABLE and raw_value is None:
        raise ValueError("an available assessment must carry its raw value")
    if availability is not Availability.AVAILABLE and raw_value is not None:
        raise ValueError(f"a {availability.value} assessment must not carry a raw value")


class SectionAvailabilityView(ContractModel):
    """What the snapshot actually carried for one section.

    ``record_count`` is the number of parsed records. It stays ``None`` for a
    missing or unparsable section: an empty aggregate object is
    ``present_empty`` and is not a confirmed zero.
    """

    section: ReportSectionName
    availability: Availability
    record_count: NonNegativeCount | None = None
    confirms_absence: bool = False
    """``True`` only when an empty container was confirmed to mean "no records"."""

    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        """Allow a record count only where records were actually parsed."""
        if self.availability is Availability.AVAILABLE and self.record_count is None:
            raise ValueError("an available section must report its record count")
        if self.availability in {Availability.MISSING, Availability.INVALID}:
            if self.record_count is not None:
                raise ValueError(f"a {self.availability.value} section has no record count")
            if self.confirms_absence:
                raise ValueError("absence may be confirmed only for a present but empty section")
        return self


class CompanyOverview(ContractModel):
    """The summary card of one company as of one report snapshot."""

    schema_version: SchemaVersion = "0.1"
    company: CompanyIdentity
    report: ReportIdentity
    status: CompanyStatusView
    bank_risk: BankRiskAssessment
    zsk: ZskAssessment
    facts: list[FactValue] = Field(default_factory=list)
    available_sections: list[SectionAvailabilityView] = Field(default_factory=list)
    """Completeness of every known section, including the absent ones: a
    section the UI cannot show must still be nameable as missing."""

    warnings: list[ContractWarning] = Field(default_factory=list)
    rule_version: NonEmptyString

    @model_validator(mode="after")
    def validate_unique_keys(self) -> Self:
        """Forbid duplicate fact keys and duplicate section entries."""
        _require_unique(fact.key for fact in self.facts)
        _require_unique(entry.section.value for entry in self.available_sections)
        return self


def _require_unique(keys: Iterable[str]) -> None:
    """Reject a repeated key.

    Raises:
        ValueError: If any key appears more than once.
    """
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen.add(key)


class ProfileRecord(ContractModel):
    """Identity attributes as reported by one snapshot."""

    kind: Literal["profile_record"] = "profile_record"
    short_name: NonEmptyString | None = None
    full_name: NonEmptyString | None = None
    inn: NonEmptyString | None = None
    kpp: NonEmptyString | None = None
    okpo: NonEmptyString | None = None
    address: NonEmptyString | None = None
    """A single reported string; it is not parsed into structured parts."""

    registration_date: UtcDatetime | None = None
    """``registrationInfo.registrationDate`` as an exact instant."""

    years_from_registration: NonNegativeCount | None = None
    email: NonEmptyString | None = None
    website: NonEmptyString | None = None
    company_size: NonEmptyString | None = None
    """Reported size wording, kept raw; its absence does not mean "small"."""

    evidence_refs: GroundedEvidenceRefs


class Activity(ContractModel):
    """One declared OKVED activity, main or secondary."""

    kind: Literal["activity"] = "activity"
    code: NonEmptyString | None = None
    description: NonEmptyString | None = None
    is_primary: bool
    evidence_refs: GroundedEvidenceRefs


FINANCIAL_ADDITIONAL_FACT_KEYS: frozenset[str] = frozenset(
    {
        "current_assets",
        "stocks",
        "noncurrent_assets",
        "fixed_assets",
        "balance_total_liabilities_side",
        "long_term_total",
        "long_term_other",
        "short_term_total",
        "short_term_borrowed",
    }
)
"""Reported figures beyond the headline ones, keyed as in ``reports``.

``balance_total_liabilities_side`` is ``liabilities.totalLiabilities``: the
balance-sheet total of the liabilities side, not the amount of debt.
"""

_HEADLINE_FINANCIAL_KEYS = (
    "proceeds",
    "profit",
    "total_assets",
    "equity",
    "cash",
    "receivables",
    "accounts_payable",
)


class FinancialPeriod(ContractModel):
    """Reported financial figures for one year of one snapshot.

    Every figure is a :class:`FactValue`, so a year that reported nothing is
    distinguishable from a year that reported zero. ``equity`` is
    ``liabilities.capitals``, the reported capital, and a negative value is not
    by itself proven insolvency.
    """

    kind: Literal["financial_period"] = "financial_period"
    year: FiscalYear
    """``common.year``. Array position does not imply the latest period."""

    proceeds: FactValue
    profit: FactValue
    total_assets: FactValue
    equity: FactValue
    cash: FactValue
    receivables: FactValue
    accounts_payable: FactValue
    additional_facts: list[FactValue] = Field(default_factory=list)
    evidence_refs: GroundedEvidenceRefs

    @model_validator(mode="after")
    def validate_fact_keys(self) -> Self:
        """Keep each figure keyed as its field and whitelisted when extra."""
        for name in _HEADLINE_FINANCIAL_KEYS:
            fact: FactValue = getattr(self, name)
            if fact.key != name:
                raise ValueError(f"financial fact for {name} is keyed {fact.key!r}")
            if fact.value_type is not ValueType.DECIMAL:
                raise ValueError(f"financial fact {name} must be a decimal")
        for extra in self.additional_facts:
            if extra.key not in FINANCIAL_ADDITIONAL_FACT_KEYS:
                raise ValueError(f"unknown additional financial fact {extra.key!r}")
        _require_unique(extra.key for extra in self.additional_facts)
        return self


class Proceeding(ContractModel):
    """One enforcement proceeding as listed by the snapshot."""

    kind: Literal["proceeding"] = "proceeding"
    id: UUID
    number: NonEmptyString | None = None
    started_at: UtcDatetime | None = None
    """``executionProceedings[].date`` as an exact instant."""

    active: FactValue
    """Boolean fact: an unknown state is not a closed proceeding."""

    amount: FactValue
    """Decimal fact: a proceeding without a known amount is not a zero debt."""

    evidence_refs: GroundedEvidenceRefs

    @model_validator(mode="after")
    def validate_fact_types(self) -> Self:
        """Pin the declared types of the two decision-bearing figures."""
        if self.active.value_type is not ValueType.BOOLEAN:
            raise ValueError("proceeding active must be a boolean fact")
        if self.amount.value_type is not ValueType.DECIMAL:
            raise ValueError("proceeding amount must be a decimal fact")
        return self


class ArbitrationAggregate(ContractModel):
    """A count and amount of arbitration cases, grouped by year or by status.

    This is an aggregate, never one case: no case number, subject or decision
    text can be recovered from it. Year and status aggregates describe the same
    cases and are never summed together.
    """

    kind: Literal["arbitration_aggregate"] = "arbitration_aggregate"
    aggregation: ArbitrationAggregation
    role: PartyRole
    year: FiscalYear | None = None
    case_status_raw: NonEmptyString | None = None
    """The provider's status token (for example ``Finished``), kept verbatim."""

    count: FactValue
    amount: FactValue
    evidence_refs: GroundedEvidenceRefs

    @model_validator(mode="after")
    def validate_grouping(self) -> Self:
        """Require exactly the dimension the aggregate claims to be grouped by."""
        if self.aggregation is ArbitrationAggregation.BY_YEAR:
            if self.year is None:
                raise ValueError("a year aggregate must carry its year")
            if self.case_status_raw is not None:
                raise ValueError("a year aggregate must not also claim a case status")
        elif self.case_status_raw is None:
            raise ValueError("a status aggregate must carry its raw case status")
        elif self.year is not None:
            raise ValueError("a status aggregate must not also claim a year")
        if self.count.value_type is not ValueType.INTEGER:
            raise ValueError("arbitration count must be an integer fact")
        if self.amount.value_type is not ValueType.DECIMAL:
            raise ValueError("arbitration amount must be a decimal fact")
        return self


class ProcurementAggregate(ContractModel):
    """Participation and signed contracts for one year and one procurement law.

    Aggregated participation does not prove that a contract was performed.
    """

    kind: Literal["procurement_aggregate"] = "procurement_aggregate"
    year: FiscalYear
    law_code: NonEmptyString
    """``federalLawCode`` verbatim, for example ``44`` or ``223``."""

    winners_count: FactValue
    contracts_count: FactValue
    contracts_amount: FactValue
    evidence_refs: GroundedEvidenceRefs


class License(ContractModel):
    """One licence record; not the full text of the permission."""

    kind: Literal["license"] = "license"
    number: NonEmptyString | None = None
    name: NonEmptyString | None = None
    authority: NonEmptyString | None = None
    issue_date: UtcDatetime | None = None
    """``licenses[].issueDate`` as an exact instant."""

    status_raw: NonEmptyString | None = None
    evidence_refs: GroundedEvidenceRefs


class Inspection(ContractModel):
    """One recorded inspection or official warning."""

    kind: Literal["inspection"] = "inspection"
    external_id: NonEmptyString | None = None
    """``inspections[].erpId``: the registry id, not our own identifier."""

    form: NonEmptyString | None = None
    authority: NonEmptyString | None = None
    start_date: UtcDatetime | None = None
    end_date: UtcDatetime | None = None
    status_raw: NonEmptyString | None = None
    evidence_refs: GroundedEvidenceRefs


class RelatedEntity(ContractModel):
    """A brief related-company record from the snapshot.

    The record does not prove the nature of the relationship, and a full report
    for the related company is available only when ``available_company_id`` is
    set.
    """

    kind: Literal["related_entity"] = "related_entity"
    inn: NonEmptyString | None = None
    ogrn: NonEmptyString | None = None
    name: NonEmptyString | None = None
    available_company_id: CompanyId | None = None
    evidence_refs: GroundedEvidenceRefs


class RiskSignal(ContractModel):
    """One reputational signal published by the source.

    ``source_name`` names who raised the signal; it is not a verified finding
    of ours, and ``interpretation_note`` never becomes a conclusion.
    """

    kind: Literal["risk_signal"] = "risk_signal"
    code: NonEmptyString
    source_name: NonEmptyString | None = None
    polarity: RiskSignalPolarity
    chapter: NonEmptyString | None = None
    interpretation_note: NonEmptyString | None = None
    evidence_refs: GroundedEvidenceRefs


ReportRecord = Annotated[
    ProfileRecord
    | Activity
    | FinancialPeriod
    | Proceeding
    | ArbitrationAggregate
    | ProcurementAggregate
    | License
    | Inspection
    | RelatedEntity
    | RiskSignal,
    Field(discriminator="kind"),
]

SECTION_RECORD_KINDS: MappingProxyType[ReportSectionName, frozenset[str]] = MappingProxyType(
    {
        ReportSectionName.PROFILE: frozenset({"profile_record"}),
        ReportSectionName.STATUS: frozenset(),
        ReportSectionName.ACTIVITIES: frozenset({"activity"}),
        ReportSectionName.FINANCIALS: frozenset({"financial_period"}),
        ReportSectionName.COEFFICIENTS: frozenset(),
        ReportSectionName.FOUNDERS: frozenset(),
        ReportSectionName.TAX_SYSTEMS: frozenset(),
        ReportSectionName.CONTACTS: frozenset(),
        ReportSectionName.EXECUTION_PROCEEDINGS: frozenset({"proceeding"}),
        ReportSectionName.ARBITRATION: frozenset({"arbitration_aggregate"}),
        ReportSectionName.PROCUREMENTS: frozenset({"procurement_aggregate"}),
        ReportSectionName.LICENSES: frozenset({"license"}),
        ReportSectionName.INSPECTIONS: frozenset({"inspection"}),
        ReportSectionName.RELATED_COMPANIES: frozenset({"related_entity"}),
        ReportSectionName.BRANCHES: frozenset(),
        ReportSectionName.RISK_SIGNALS: frozenset({"risk_signal"}),
        ReportSectionName.ZSK: frozenset(),
    }
)
"""Record types each section may return.

A section mapped to an empty set has no record type of its own yet: it is
reported through availability and facts, and returning arbitrary records for it
is a contract violation rather than a convenience.
"""


class ReportSection(ContractModel):
    """One paginated section of one report snapshot."""

    schema_version: SchemaVersion = "0.1"
    report_id: ReportId
    section: ReportSectionName
    availability: Availability
    records: list[ReportRecord] = Field(default_factory=list)
    facts: list[FactValue] = Field(default_factory=list)
    page: PageInfo
    total_records: NonNegativeCount | None = None
    """Total across pages when the server can count it without guessing."""

    warnings: list[ContractWarning] = Field(default_factory=list)
    rule_version: NonEmptyString

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        """Only the record types declared for this section may appear in it."""
        allowed = SECTION_RECORD_KINDS[self.section]
        for record in self.records:
            if record.kind not in allowed:
                raise ValueError(f"{record.kind!r} is not a record of section {self.section.value}")
        if self.records and self.availability is not Availability.AVAILABLE:
            raise ValueError(f"a {self.availability.value} section must not carry records")
        _require_unique(fact.key for fact in self.facts)
        return self


class ComparisonRow(ContractModel):
    """One company's line of a comparison.

    A row that could not be built completely says so; an unknown value is never
    ranked as the worst number.
    """

    company: CompanyIdentity
    report: ReportIdentity
    cells: list[FactValue] = Field(default_factory=list)
    status: ComparisonRowStatus
    warnings: list[ContractWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cells(self) -> Self:
        """Forbid duplicate criteria in one row."""
        _require_unique(cell.key for cell in self.cells)
        return self


class Comparison(ContractModel):
    """A side-by-side view of report facts for two to twenty companies.

    The deterministic layer produces no winner and no aggregate score.
    """

    schema_version: SchemaVersion = "0.1"
    id: UUID | None = None
    report_ids: list[ReportId] = Field(
        min_length=MIN_COMPARISON_COMPANIES, max_length=MAX_COMPARISON_COMPANIES
    )
    criteria: list[ComparisonCriterion] = Field(min_length=1)
    year_policy: YearPolicy
    year: FiscalYear | None = None
    rows: list[ComparisonRow] = Field(default_factory=list)
    warnings: list[ContractWarning] = Field(default_factory=list)
    rule_version: NonEmptyString

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        """Require unique reports and an explicit year only where it applies."""
        _require_unique(str(report_id) for report_id in self.report_ids)
        _require_unique(criterion.value for criterion in self.criteria)
        if self.year_policy is YearPolicy.EXPLICIT and self.year is None:
            raise ValueError("an explicit year policy must name the year")
        if self.year_policy is not YearPolicy.EXPLICIT and self.year is not None:
            raise ValueError(f"the {self.year_policy.value} policy must not pin a year")
        return self


class ProjectComparison(Comparison):
    """A project comparison, which may add workspace deal terms to each row.

    ``proposal_facts`` are the user's own conditions with their own evidence.
    They are kept apart from report facts and never returned to the MCP client.
    """

    project_id: ProjectId
    proposal_facts: list[FactValue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_proposal_facts(self) -> Self:
        """Forbid duplicate proposal keys."""
        _require_unique(fact.key for fact in self.proposal_facts)
        return self


class ReportEvidence(ContractModel):
    """An authorized original source fragment addressed by an issued reference."""

    schema_version: SchemaVersion = "0.1"
    evidence: EvidenceRef
    report: ReportIdentity
    availability: Availability
    value: JsonValue = None
    warnings: list[ContractWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report_locator(self) -> Self:
        """Accept only a report-field reference to this exact snapshot."""
        if self.evidence.kind is not EvidenceKind.REPORT_FIELD:
            raise ValueError("report evidence requires a report_field reference")
        if self.evidence.report_id != self.report.id:
            raise ValueError("evidence and report must identify the same snapshot")
        if (
            self.availability in {Availability.MISSING, Availability.RESTRICTED}
            and self.value is not None
        ):
            raise ValueError("missing or restricted evidence must not carry a source value")
        return self
