"""The read-only tool contract of the internal reports MCP service.

Three rules shape this module.

A tool answers about reports and nothing else. There is no workspace input and
no workspace output here: the user's own deal terms are never sent to this
service, and :class:`~counterparty_contracts.reports.ProjectComparison` — the
extension that carries them — is refused by the comparison envelope rather than
quietly serialized down to its report-only fields.

An incomplete answer says so. :class:`McpEnvelope` separates a protocol failure
from business incompleteness: ``partial`` still carries data and explains what
is missing, ``not_found`` and ``unavailable`` carry none, and an empty result is
never presented as "no risk".

Input is a whitelist. Sections come from a closed enum, filters are typed and
checked against the section they are used with, and an unknown filter is a
validation error rather than a silently ignored key. No free-form expression,
column name, SQL or URL is accepted.
"""

from types import MappingProxyType
from typing import Self

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyString, SchemaVersion
from .diagnostics import ContractWarning
from .enums import (
    ComparisonCriterion,
    ErrorCode,
    McpStatus,
    PartyRole,
    ReportSectionName,
    YearPolicy,
)
from .identifiers import ReportId
from .pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from .reports import (
    MAX_COMPARISON_COMPANIES,
    MIN_COMPARISON_COMPANIES,
    CompanyOverview,
    Comparison,
    ProjectComparison,
    ReportSection,
)
from .values import FiscalYear

__all__ = [
    "SECTION_ALLOWED_FILTERS",
    "CompanyOverviewEnvelope",
    "CompareCompaniesInput",
    "ComparisonEnvelope",
    "GetCompanyOverviewInput",
    "GetReportSectionInput",
    "McpEnvelope",
    "ReportSectionEnvelope",
    "ReportSectionFilters",
    "ToolError",
]


class ToolError(ContractModel):
    """A safe business error returned inside a tool envelope.

    It describes an outcome the caller can act on. A transport or protocol
    failure is not reported here, and no stack trace, SQL or internal path ever
    reaches the model.
    """

    code: ErrorCode
    message: NonEmptyString
    retryable: bool = False
    source_path: NonEmptyString | None = None


class McpEnvelope[DataT](ContractModel):
    """The shared response envelope of every MCP tool.

    Attributes:
        status: Business outcome. ``ok`` and ``partial`` carry data;
            ``not_found`` and ``unavailable`` carry none.
        data: The typed payload of the tool.
        errors: Why the answer is not complete. An empty list with a
            non-``ok`` status would leave the gap unexplained.
        warnings: Typed notes about precision, age or comparability.
        source_report_ids: Every snapshot the answer was read from, so the
            caller can pin the same reports on the next call.
        rule_version: Version of the deterministic rules that produced it.
    """

    schema_version: SchemaVersion = "0.1"
    status: McpStatus
    data: DataT | None = None
    errors: list[ToolError] = Field(default_factory=list)
    warnings: list[ContractWarning] = Field(default_factory=list)
    source_report_ids: list[ReportId] = Field(default_factory=list)
    rule_version: NonEmptyString

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Keep the declared outcome, the payload and the reasons consistent."""
        if self.status in {McpStatus.OK, McpStatus.PARTIAL}:
            if self.data is None:
                raise ValueError(f"a {self.status.value} result must carry its data")
        elif self.data is not None:
            raise ValueError(f"a {self.status.value} result must not carry data")
        if self.status is McpStatus.OK and self.errors:
            raise ValueError("an ok result must not report errors")
        if self.status is not McpStatus.OK and not self.errors and not self.warnings:
            raise ValueError(f"a {self.status.value} result must say what is missing")
        return self


class CompanyOverviewEnvelope(McpEnvelope[CompanyOverview]):
    """Result of ``get_company_overview``."""


class ReportSectionEnvelope(McpEnvelope[ReportSection]):
    """Result of ``get_report_section``. Continuation is in ``data.page``."""


class ComparisonEnvelope(McpEnvelope[Comparison]):
    """Result of ``compare_companies``: report facts only.

    The deterministic layer produces no winner and no aggregate score, and this
    service has no workspace access, so the proposal terms of a project cannot
    be part of the answer.
    """

    @model_validator(mode="after")
    def reject_workspace_comparison(self) -> Self:
        """Refuse a project comparison instead of stripping it silently."""
        if isinstance(self.data, ProjectComparison):
            raise ValueError("workspace proposal facts are not returned by the reports MCP")
        return self


class GetCompanyOverviewInput(ContractModel):
    """Identify a company by exactly one selector.

    An INN is resolved only among the imported companies: an unknown one is
    ``not_found`` and never starts an external lookup. Selecting by INN answers
    from the latest snapshot we hold and names its ``report_id``, which the
    caller pins for every following call.
    """

    inn: NonEmptyString | None = None
    report_id: ReportId | None = None

    @model_validator(mode="after")
    def validate_selector(self) -> Self:
        """Require exactly one selector, so the intent stays unambiguous."""
        if (self.inn is None) == (self.report_id is None):
            raise ValueError("name the company either by inn or by report_id, not both")
        return self


class ReportSectionFilters(ContractModel):
    """The typed filters a section may be narrowed by.

    Every field is a closed value or a list of them. A filter that a section
    does not support is a validation error rather than an ignored key, so a
    caller never believes a narrowing was applied when it was not.
    """

    years: list[FiscalYear] | None = Field(default=None, min_length=1)
    active: bool | None = None
    role: PartyRole | None = None
    status_raw: NonEmptyString | None = None
    """The provider's own case-status token, matched verbatim."""

    @model_validator(mode="after")
    def validate_years(self) -> Self:
        """Forbid a repeated year, which would double count its records."""
        if self.years is not None and len(set(self.years)) != len(self.years):
            raise ValueError("a year must not be requested twice")
        return self

    def applied_names(self) -> frozenset[str]:
        """Return the names of the filters this request actually sets."""
        return frozenset(
            name for name, value in self.model_dump(exclude_none=True).items() if value is not None
        )


SECTION_ALLOWED_FILTERS: MappingProxyType[ReportSectionName, frozenset[str]] = MappingProxyType(
    {
        ReportSectionName.PROFILE: frozenset(),
        ReportSectionName.STATUS: frozenset(),
        ReportSectionName.ACTIVITIES: frozenset(),
        ReportSectionName.FINANCIALS: frozenset({"years"}),
        ReportSectionName.COEFFICIENTS: frozenset({"years"}),
        ReportSectionName.FOUNDERS: frozenset(),
        ReportSectionName.TAX_SYSTEMS: frozenset(),
        ReportSectionName.CONTACTS: frozenset(),
        ReportSectionName.EXECUTION_PROCEEDINGS: frozenset({"active"}),
        ReportSectionName.ARBITRATION: frozenset({"years", "role", "status_raw"}),
        ReportSectionName.PROCUREMENTS: frozenset({"years"}),
        ReportSectionName.LICENSES: frozenset(),
        ReportSectionName.INSPECTIONS: frozenset(),
        ReportSectionName.RELATED_COMPANIES: frozenset(),
        ReportSectionName.BRANCHES: frozenset(),
        ReportSectionName.RISK_SIGNALS: frozenset(),
        ReportSectionName.ZSK: frozenset(),
    }
)
"""Filters each section accepts. Anything else is a validation error."""


class GetReportSectionInput(ContractModel):
    """Read one section of one pinned snapshot, page by page.

    Paging is by cursor with the shared limits, so a large section is continued
    rather than cut in the middle. A page that returns nothing does not prove
    that the section is empty: ``has_more`` and the section availability do.
    """

    report_id: ReportId
    section: ReportSectionName
    filters: ReportSectionFilters | None = None
    cursor: NonEmptyString | None = None
    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)

    @model_validator(mode="after")
    def validate_filters(self) -> Self:
        """Accept only the filters the requested section actually supports."""
        if self.filters is None:
            return self
        allowed = SECTION_ALLOWED_FILTERS[self.section]
        rejected = sorted(self.filters.applied_names() - allowed)
        if rejected:
            raise ValueError(
                f"section {self.section.value} does not support filter(s) {', '.join(rejected)}"
            )
        return self


class CompareCompaniesInput(ContractModel):
    """Compare two to twenty pinned snapshots on whitelisted criteria.

    The tool returns facts and deterministic values. It computes no ranking and
    no risk score, and it accepts no expression of its own.
    """

    report_ids: list[ReportId] = Field(
        min_length=MIN_COMPARISON_COMPANIES, max_length=MAX_COMPARISON_COMPANIES
    )
    criteria: list[ComparisonCriterion] = Field(min_length=1)
    year_policy: YearPolicy = YearPolicy.LATEST_AVAILABLE
    year: FiscalYear | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        """Require unique reports and an explicit year only where it applies."""
        if len(set(self.report_ids)) != len(self.report_ids):
            raise ValueError("a report must not be compared with itself")
        if len(set(self.criteria)) != len(self.criteria):
            raise ValueError("a criterion must not be requested twice")
        if self.year_policy is YearPolicy.EXPLICIT and self.year is None:
            raise ValueError("an explicit year policy must name the year")
        if self.year_policy is not YearPolicy.EXPLICIT and self.year is not None:
            raise ValueError(f"the {self.year_policy.value} policy must not pin a year")
        return self
