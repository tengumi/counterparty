"""REST DTOs of the workspace: projects, companies, threads, terms, decisions.

The user's own work is kept separate from what the provided report says. Deal
terms (:class:`ProjectFact`) always name where they came from and how confirmed
they are, and a recorded decision (:class:`UserDecision`) is an independent,
versioned entity that neither replaces nor is replaced by an AI artifact.

Optimistic concurrency runs through ``context_version``: any request that
changes the project context states the version it expected to change.
"""

from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyString, SchemaVersion, UtcDatetime
from .enums import (
    ArtifactFreshness,
    CompanyAddOutcome,
    ConfirmationStatus,
    CounterpartyRole,
    DecisionOutcome,
    ErrorCode,
    ProjectDeletionState,
    ProjectFactKey,
    ThreadStatus,
    ValueType,
)
from .envelopes import ProjectEnvelope, ThreadEnvelope
from .facts import FactValueScalar
from .identifiers import (
    ArtifactId,
    ClientRequestId,
    CompanyId,
    DecisionId,
    EvidenceRefId,
    ProjectId,
    ReportId,
    ThreadId,
    UserId,
)
from .values import CurrencyCode, parse_calendar_date, parse_decimal_string

__all__ = [
    "MAX_PROJECT_COMPANIES",
    "AddCompaniesRequest",
    "AddCompaniesResponse",
    "AddCompanyItem",
    "AddCompanyResult",
    "ArtifactAttachment",
    "ArtifactPreview",
    "CompanySummary",
    "CreateDecisionRequest",
    "CreateProjectRequest",
    "CreateThreadRequest",
    "DeleteProjectRequest",
    "Project",
    "ProjectCompaniesResponse",
    "ProjectCompany",
    "ProjectDeletionStatus",
    "ProjectFact",
    "ProjectFactChange",
    "ProjectFactsResponse",
    "RemoveCompanyRequest",
    "ThreadSummary",
    "UpdateProjectFactsRequest",
    "UpdateProjectRequest",
    "UpdateThreadRequest",
    "UserDecision",
]

MAX_PROJECT_COMPANIES = 20
"""Companies one project may compare. A batch that would exceed the limit is
rejected as a whole rather than silently truncated to the first N items."""

ThreadSummary = ThreadEnvelope
"""Canonical name of one chat inside a project.

The identity is the ``thread_id``; an authorization session cookie never
substitutes for it.
"""


class ArtifactPreview(ContractModel):
    """Compact reference to one immutable version of an AI artifact."""

    artifact_id: ArtifactId
    version: int = Field(ge=1)
    title: NonEmptyString
    source_thread_id: ThreadId
    created_at: UtcDatetime
    freshness: ArtifactFreshness
    available: bool
    """``False`` once the artifact can no longer be opened; a newer version
    never rewrites an already sent reference."""


class ArtifactAttachment(ContractModel):
    """A reference to one immutable artifact version, or a section of it.

    The server resolves the attachment: it checks the project, the existence of
    the pinned version and the section. A URL or a server path is never
    accepted as an attachment, and a newer version never rewrites a reference
    that was already sent.
    """

    artifact_id: ArtifactId
    version: int = Field(ge=1)
    section_id: NonEmptyString | None = None


class CompanySummary(ContractModel):
    """A company found in the local index. No external lookup is performed."""

    company_id: CompanyId
    inn: NonEmptyString
    ogrn: NonEmptyString | None = None
    short_name: NonEmptyString
    full_name: NonEmptyString | None = None
    latest_report_id: ReportId | None = None
    latest_report_at: UtcDatetime | None = None
    """Instant of the newest snapshot we hold; ``None`` when we hold none."""

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        """Keep the newest snapshot and its date reported together."""
        if (self.latest_report_id is None) != (self.latest_report_at is None):
            raise ValueError("a latest report must come with its date, and the other way round")
        return self


class ProjectCompany(ContractModel):
    """One counterparty currently under review inside a project."""

    company_id: CompanyId
    report_id: ReportId
    """The snapshot this project is reasoning about; pinned when added."""

    inn: NonEmptyString
    short_name: NonEmptyString
    role: CounterpartyRole = CounterpartyRole.UNKNOWN
    shortlisted: bool = False
    added_at: UtcDatetime


class UserDecision(ContractModel):
    """The decision the user recorded, with their own grounds.

    A decision may be recorded without any AI artifact, and disagreement with
    one is a valid outcome. Superseding a decision keeps the older one.
    """

    schema_version: SchemaVersion = "0.1"
    id: DecisionId
    project_id: ProjectId
    outcome: DecisionOutcome
    company_ids: list[CompanyId] = Field(default_factory=list)
    rationale: NonEmptyString
    conditions: list[NonEmptyString] = Field(default_factory=list)
    """Concrete conditions or missing facts, never a generic disclaimer."""

    based_on_artifact_id: ArtifactId | None = None
    based_on_artifact_version: int | None = Field(default=None, ge=1)
    context_version: int = Field(ge=0)
    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)
    author_user_id: UserId
    """Taken from the authenticated caller; never from the request body."""

    created_at: UtcDatetime
    supersedes_id: DecisionId | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Require the concrete conditions the outcome promises."""
        _validate_decision_shape(
            self.outcome,
            self.conditions,
            self.based_on_artifact_id,
            self.based_on_artifact_version,
        )
        return self


def _validate_decision_shape(
    outcome: DecisionOutcome,
    conditions: list[str],
    artifact_id: ArtifactId | None,
    artifact_version: int | None,
) -> None:
    """Check the invariants shared by a decision and its create request.

    Raises:
        ValueError: If a conditional outcome names no condition, or an artifact
            is referenced without pinning the version that was read.
    """
    conditional = {DecisionOutcome.READY_WITH_CONDITIONS, DecisionOutcome.NEED_MORE_INFO}
    if outcome in conditional and not conditions:
        raise ValueError(f"{outcome.value} requires at least one concrete condition")
    if (artifact_id is None) != (artifact_version is None):
        raise ValueError("an artifact reference must pin the immutable version it read")


class Project(ProjectEnvelope):
    """A counterparty check: its companies, open question and latest outcomes.

    ``workflow_status`` is neither a run status nor a risk assessment.
    """

    companies: list[ProjectCompany] = Field(default_factory=list, max_length=MAX_PROJECT_COMPANIES)
    last_open_question: NonEmptyString | None = None
    latest_artifact: ArtifactPreview | None = None
    latest_decision: UserDecision | None = None

    @model_validator(mode="after")
    def validate_companies(self) -> Self:
        """Forbid the same company twice in one active composition."""
        seen: set[CompanyId] = set()
        for company in self.companies:
            if company.company_id in seen:
                raise ValueError(f"company {company.company_id} is already in the project")
            seen.add(company.company_id)
        return self


class ProjectFact(ContractModel):
    """One deal term of the project context.

    A company-specific term names its company: the 80% advance offered by one
    counterparty is never mixed into the proposal of another.
    """

    schema_version: SchemaVersion = "0.1"
    id: UUID
    project_id: ProjectId
    key: ProjectFactKey
    value: FactValueScalar | None = None
    value_type: ValueType
    unit: NonEmptyString | None = None
    currency: CurrencyCode | None = None
    company_id: CompanyId | None = None
    provenance_ref: EvidenceRefId
    """Where the term came from: the user's message, a document or a derivation."""

    confirmation_status: ConfirmationStatus
    version: int = Field(ge=1)
    supersedes_id: UUID | None = None

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        """Apply the whitelist rules of the key to the submitted value."""
        _validate_project_fact_value(self.key, self.value, self.value_type, self.currency)
        return self


_MONEY_FACT_KEYS = frozenset({ProjectFactKey.AMOUNT})
_FACT_KEY_VALUE_TYPES: dict[ProjectFactKey, ValueType] = {
    ProjectFactKey.COUNTERPARTY_ROLE: ValueType.ENUM,
    ProjectFactKey.SUBJECT: ValueType.STRING,
    ProjectFactKey.AMOUNT: ValueType.DECIMAL,
    ProjectFactKey.PAYMENT_TYPE: ValueType.STRING,
    ProjectFactKey.ADVANCE_PERCENT: ValueType.DECIMAL,
    ProjectFactKey.DELIVERY_DEADLINE: ValueType.DATE,
    ProjectFactKey.DELIVERY_TERMS: ValueType.STRING,
    ProjectFactKey.USER_PRIORITY: ValueType.STRING,
}


def _validate_project_fact_value(
    key: ProjectFactKey,
    value: FactValueScalar | None,
    value_type: ValueType,
    currency: CurrencyCode | None,
) -> None:
    """Enforce the type, currency and range rules of one deal term.

    Raises:
        ValueError: If the value contradicts the key's declared type, if money
            arrives without a currency, if a currency is attached to something
            that is not money, if the advance share leaves ``0..100``, or if
            the role is not a known one.
    """
    expected = _FACT_KEY_VALUE_TYPES[key]
    if value_type is not expected:
        raise ValueError(f"{key.value} must be a {expected.value} value")
    if key in _MONEY_FACT_KEYS and currency is None:
        raise ValueError(f"{key.value} is money and requires a currency")
    if key not in _MONEY_FACT_KEYS and currency is not None:
        raise ValueError(f"{key.value} is not money and must not carry a currency")
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError(f"{key.value} must be transported as a string")
    if value_type is ValueType.DECIMAL:
        amount = parse_decimal_string(value)
        if key is ProjectFactKey.ADVANCE_PERCENT and not 0 <= amount <= 100:
            raise ValueError("advance_percent must be between 0 and 100")
    elif value_type is ValueType.DATE:
        parse_calendar_date(value)
    elif key is ProjectFactKey.COUNTERPARTY_ROLE and value not in set(CounterpartyRole):
        raise ValueError(f"{value!r} is not a known counterparty role")
    elif not value:
        raise ValueError(f"{key.value} must not be an empty string")


class ProjectFactChange(ContractModel):
    """One requested change to a deal term.

    ``value=None`` clears the term. The version it becomes is assigned by the
    server, so a client cannot overwrite history by choosing a version.
    """

    key: ProjectFactKey
    value: FactValueScalar | None = None
    value_type: ValueType
    unit: NonEmptyString | None = None
    currency: CurrencyCode | None = None
    company_id: CompanyId | None = None
    provenance_ref: EvidenceRefId | None = None
    confirmation_status: ConfirmationStatus

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        """Apply the same whitelist rules the stored term is held to."""
        _validate_project_fact_value(self.key, self.value, self.value_type, self.currency)
        return self


class CreateProjectRequest(ContractModel):
    """Start one counterparty check. This creates no LLM run by itself."""

    title: NonEmptyString | None = None
    initial_question: NonEmptyString | None = None
    client_request_id: ClientRequestId
    """Repeating the same id returns the same project instead of a duplicate."""


class UpdateProjectRequest(ContractModel):
    """Rename a project. A rename does not change the deal context."""

    title: NonEmptyString


class DeleteProjectRequest(ContractModel):
    """Delete a project, optionally guarded by the version the client saw."""

    expected_version: int | None = Field(default=None, ge=0)


class ProjectDeletionStatus(ContractModel):
    """Accepted deletion of a project.

    Access is closed and any active run is cancelled before cleanup, so an
    accepted deletion is not yet a completed one.
    """

    schema_version: SchemaVersion = "0.1"
    project_id: ProjectId
    state: ProjectDeletionState
    active_run_cancelled: bool
    requested_at: UtcDatetime
    error_code: ErrorCode | None = None


class AddCompanyItem(ContractModel):
    """One requested company, named either by INN or by local company id."""

    inn: NonEmptyString | None = None
    company_id: CompanyId | None = None

    @model_validator(mode="after")
    def validate_selector(self) -> Self:
        """Require exactly one selector, so the intent stays unambiguous."""
        if (self.inn is None) == (self.company_id is None):
            raise ValueError("name the company either by inn or by company_id, not both")
        return self


class AddCompaniesRequest(ContractModel):
    """Add several companies to a project under one expected context version."""

    items: list[AddCompanyItem] = Field(min_length=1, max_length=MAX_PROJECT_COMPANIES)
    expected_context_version: int = Field(ge=0)


class AddCompanyResult(ContractModel):
    """What happened to one requested company.

    An invalid row does not by itself block the valid ones; exceeding the
    company limit rejects the batch instead.
    """

    requested: AddCompanyItem
    outcome: CompanyAddOutcome
    company_id: CompanyId | None = None
    report_id: ReportId | None = None
    error_code: ErrorCode | None = None
    message: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Require the resolved identity on success and a reason on failure."""
        resolved = {CompanyAddOutcome.ADDED, CompanyAddOutcome.ALREADY_PRESENT}
        if self.outcome in resolved:
            if self.company_id is None:
                raise ValueError(
                    f"a {self.outcome.value} item must name the company it resolved to"
                )
            if self.error_code is not None:
                raise ValueError(f"a {self.outcome.value} item must not carry an error code")
        elif self.error_code is None:
            raise ValueError(f"a {self.outcome.value} item must explain itself with an error code")
        return self


class ProjectCompaniesResponse(ContractModel):
    """The composition of a project after a change to it."""

    schema_version: SchemaVersion = "0.1"
    project_id: ProjectId
    companies: list[ProjectCompany] = Field(default_factory=list)
    context_version: int = Field(ge=0)


class AddCompaniesResponse(ProjectCompaniesResponse):
    """Per-item results plus the resulting composition and context version."""

    results: list[AddCompanyResult] = Field(min_length=1)


class RemoveCompanyRequest(ContractModel):
    """Remove one company from the current composition.

    Historical sources and earlier conclusions are kept; only the active
    composition changes.
    """

    expected_context_version: int = Field(ge=0)


class UpdateProjectFactsRequest(ContractModel):
    """Change deal terms under the context version the client last saw."""

    changes: list[ProjectFactChange] = Field(min_length=1)
    expected_context_version: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        """Forbid two changes to the same term in one request."""
        seen: set[tuple[str, str | None]] = set()
        for change in self.changes:
            target = (change.key.value, str(change.company_id) if change.company_id else None)
            if target in seen:
                raise ValueError(f"{change.key.value} is changed twice in one request")
            seen.add(target)
        return self


class ProjectFactsResponse(ContractModel):
    """Deal terms of a project and the context version they belong to."""

    schema_version: SchemaVersion = "0.1"
    project_id: ProjectId
    facts: list[ProjectFact] = Field(default_factory=list)
    context_version: int = Field(ge=0)


class CreateThreadRequest(ContractModel):
    """Open another chat inside the project. Documents and terms stay shared."""

    title: NonEmptyString | None = None
    client_request_id: ClientRequestId


class UpdateThreadRequest(ContractModel):
    """Rename or archive one chat.

    Archiving with an active run is confirmed by the UI first; it never
    silently cancels the run.
    """

    title: NonEmptyString | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        """Require at least one actual change."""
        if self.title is None and self.archived is None:
            raise ValueError("nothing to change")
        return self

    def target_status(self) -> ThreadStatus | None:
        """Return the status this request asks for, if it asks for one."""
        if self.archived is None:
            return None
        return ThreadStatus.ARCHIVED if self.archived else ThreadStatus.ACTIVE


class CreateDecisionRequest(ContractModel):
    """Record the user's own decision.

    The author is taken from the authenticated caller and is never accepted
    from this body.
    """

    outcome: DecisionOutcome
    rationale: NonEmptyString
    conditions: list[NonEmptyString] = Field(default_factory=list)
    company_ids: list[CompanyId] = Field(default_factory=list)
    based_on_artifact_id: ArtifactId | None = None
    based_on_artifact_version: int | None = Field(default=None, ge=1)
    context_version: int = Field(ge=0)
    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)
    supersedes_id: DecisionId | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Hold the request to the same invariants as the stored decision."""
        _validate_decision_shape(
            self.outcome,
            self.conditions,
            self.based_on_artifact_id,
            self.based_on_artifact_version,
        )
        return self
