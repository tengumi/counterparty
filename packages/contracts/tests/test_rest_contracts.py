"""REST DTOs: projects, companies, threads, deal terms and user decisions."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from counterparty_contracts import (
    MAX_PROJECT_COMPANIES,
    AddCompaniesRequest,
    AddCompanyItem,
    AddCompanyResult,
    ArtifactFreshness,
    ArtifactId,
    ArtifactPreview,
    ClientRequestId,
    CompanyAddOutcome,
    CompanyId,
    CompanySummary,
    ConfirmationStatus,
    CounterpartyRole,
    CreateDecisionRequest,
    CreateProjectRequest,
    DecisionId,
    DecisionOutcome,
    ErrorCode,
    Page,
    PageInfo,
    Project,
    ProjectCompany,
    ProjectFact,
    ProjectFactChange,
    ProjectFactKey,
    ProjectId,
    ReportId,
    ThreadId,
    ThreadSummary,
    UpdateProjectFactsRequest,
    UpdateThreadRequest,
    UserDecision,
    UserId,
    ValueType,
    WorkflowStatus,
)
from counterparty_contracts.envelopes import ThreadEnvelope

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
PROJECT_ID = ProjectId(UUID("00000000-0000-4000-8000-000000000001"))
THREAD_ID = ThreadId(UUID("00000000-0000-4000-8000-000000000002"))
USER_ID = UserId(UUID("00000000-0000-4000-8000-000000000003"))


def company(company_id: CompanyId | None = None) -> ProjectCompany:
    """Build one company of a project composition."""
    return ProjectCompany(
        company_id=company_id or CompanyId(uuid4()),
        report_id=ReportId(uuid4()),
        inn="7449088645",
        short_name="Компания Пример",
        added_at=NOW,
    )


def project(**overrides: object) -> Project:
    """Build a minimal valid project."""
    payload: dict[str, object] = {
        "id": str(PROJECT_ID),
        "title": "Проверка поставщика",
        "default_thread_id": str(THREAD_ID),
        "threads_count": 1,
        "context_version": 0,
        "workflow_status": WorkflowStatus.IN_PROGRESS,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return Project.model_validate(payload)


def test_thread_summary_is_the_thread_envelope() -> None:
    """The REST name and the contract v0 envelope are one type, not two."""
    assert ThreadSummary is ThreadEnvelope


def test_project_extends_the_envelope_without_renaming_fields() -> None:
    """The envelope fields keep their names inside the fuller DTO."""
    assert set(ThreadEnvelope.model_fields) <= set(ThreadSummary.model_fields)
    assert {"id", "default_thread_id", "context_version", "workflow_status"} <= set(
        Project.model_fields
    )


def test_project_rejects_the_same_company_twice() -> None:
    """One counterparty appears once in an active composition."""
    duplicate = company(CompanyId(UUID("00000000-0000-4000-8000-000000000004")))
    with pytest.raises(ValidationError, match="already in the project"):
        project(companies=[duplicate.model_dump(mode="json")] * 2)


def test_project_composition_is_capped_at_twenty() -> None:
    """The comparison limit is expressed in the type, not left to callers."""
    too_many = [company().model_dump(mode="json") for _ in range(MAX_PROJECT_COMPANIES + 1)]
    with pytest.raises(ValidationError):
        project(companies=too_many)


def test_project_carries_the_latest_artifact_preview_only() -> None:
    """A newer version does not rewrite what was already referenced."""
    preview = ArtifactPreview(
        artifact_id=ArtifactId(uuid4()),
        version=2,
        title="Вывод по авансу",
        source_thread_id=THREAD_ID,
        created_at=NOW,
        freshness=ArtifactFreshness.OUTDATED,
        available=True,
    )
    assert project(latest_artifact=preview.model_dump(mode="json")).latest_artifact == preview


def test_company_summary_requires_a_date_with_its_report() -> None:
    """A named snapshot always says how old it is."""
    with pytest.raises(ValidationError, match="latest report"):
        CompanySummary(
            company_id=CompanyId(uuid4()),
            inn="7449088645",
            short_name="Компания",
            latest_report_id=ReportId(uuid4()),
        )


def test_add_company_item_needs_exactly_one_selector() -> None:
    """A company is named by INN or by id, never by both or neither."""
    assert AddCompanyItem(inn="7449088645").company_id is None
    with pytest.raises(ValidationError, match="not both"):
        AddCompanyItem(inn="7449088645", company_id=CompanyId(uuid4()))
    with pytest.raises(ValidationError, match="not both"):
        AddCompanyItem()


def test_add_batch_is_capped_rather_than_truncated() -> None:
    """A batch larger than the limit is rejected as a whole."""
    items = [{"inn": f"744908864{index % 10}"} for index in range(MAX_PROJECT_COMPANIES + 1)]
    with pytest.raises(ValidationError):
        AddCompaniesRequest(items=items, expected_context_version=0)  # type: ignore[arg-type]


def test_add_result_explains_every_outcome() -> None:
    """Success resolves an identity; failure carries a reason."""
    added = AddCompanyResult(
        requested=AddCompanyItem(inn="7449088645"),
        outcome=CompanyAddOutcome.ADDED,
        company_id=CompanyId(uuid4()),
    )
    assert added.error_code is None
    with pytest.raises(ValidationError, match="error code"):
        AddCompanyResult(
            requested=AddCompanyItem(inn="0000000000"), outcome=CompanyAddOutcome.NOT_FOUND
        )
    with pytest.raises(ValidationError, match="must name the company"):
        AddCompanyResult(
            requested=AddCompanyItem(inn="7449088645"), outcome=CompanyAddOutcome.ALREADY_PRESENT
        )
    invalid = AddCompanyResult(
        requested=AddCompanyItem(inn="1"),
        outcome=CompanyAddOutcome.INVALID,
        error_code=ErrorCode.VALIDATION_ERROR,
    )
    assert invalid.outcome is CompanyAddOutcome.INVALID


def fact(**overrides: object) -> ProjectFact:
    """Build a stored deal term, overriding single fields."""
    payload: dict[str, object] = {
        "id": str(uuid4()),
        "project_id": str(PROJECT_ID),
        "key": ProjectFactKey.AMOUNT,
        "value": "2400000.00",
        "value_type": ValueType.DECIMAL,
        "currency": "RUB",
        "provenance_ref": "ev-user-message",
        "confirmation_status": ConfirmationStatus.USER_CONFIRMED,
        "version": 1,
    }
    payload.update(overrides)
    return ProjectFact.model_validate(payload)


def test_deal_amount_requires_a_currency() -> None:
    """Money without a currency is not a comparable amount."""
    assert fact().currency == "RUB"
    with pytest.raises(ValidationError, match="requires a currency"):
        fact(currency=None)


def test_advance_percent_stays_within_range_and_carries_no_currency() -> None:
    """The advance share is a percentage, not an amount."""
    assert fact(key=ProjectFactKey.ADVANCE_PERCENT, value="80", currency=None).value == "80"
    with pytest.raises(ValidationError, match="between 0 and 100"):
        fact(key=ProjectFactKey.ADVANCE_PERCENT, value="180", currency=None)
    with pytest.raises(ValidationError, match="must not carry a currency"):
        fact(key=ProjectFactKey.ADVANCE_PERCENT, value="80")


def test_deal_term_type_follows_its_key() -> None:
    """A whitelisted key pins the type of its value."""
    with pytest.raises(ValidationError, match="must be a decimal value"):
        fact(value_type=ValueType.STRING)


def test_counterparty_role_is_whitelisted() -> None:
    """An unknown role is refused rather than stored as free text."""
    valid = fact(
        key=ProjectFactKey.COUNTERPARTY_ROLE,
        value=CounterpartyRole.SUPPLIER.value,
        value_type=ValueType.ENUM,
        currency=None,
    )
    assert valid.value == "supplier"
    with pytest.raises(ValidationError, match="not a known counterparty role"):
        fact(
            key=ProjectFactKey.COUNTERPARTY_ROLE,
            value="партнёр",
            value_type=ValueType.ENUM,
            currency=None,
        )


def test_delivery_deadline_is_a_calendar_day() -> None:
    """A deadline the user states is a day, not an instant we invented."""
    assert (
        fact(
            key=ProjectFactKey.DELIVERY_DEADLINE,
            value="2026-12-31",
            value_type=ValueType.DATE,
            currency=None,
        ).value_type
        is ValueType.DATE
    )
    with pytest.raises(ValidationError):
        fact(
            key=ProjectFactKey.DELIVERY_DEADLINE,
            value="31.12.2026",
            value_type=ValueType.DATE,
            currency=None,
        )


def test_facts_patch_states_the_version_it_expected() -> None:
    """Optimistic concurrency is part of the request, not an afterthought."""
    change = ProjectFactChange(
        key=ProjectFactKey.ADVANCE_PERCENT,
        value="80",
        value_type=ValueType.DECIMAL,
        confirmation_status=ConfirmationStatus.USER_CONFIRMED,
    )
    request = UpdateProjectFactsRequest(changes=[change], expected_context_version=3)
    assert request.expected_context_version == 3
    with pytest.raises(ValidationError, match="changed twice"):
        UpdateProjectFactsRequest(changes=[change, change], expected_context_version=3)


def test_company_specific_terms_do_not_collide() -> None:
    """The same term for two counterparties is two changes, not a conflict."""
    first = ProjectFactChange(
        key=ProjectFactKey.ADVANCE_PERCENT,
        value="80",
        value_type=ValueType.DECIMAL,
        company_id=CompanyId(uuid4()),
        confirmation_status=ConfirmationStatus.USER_CONFIRMED,
    )
    second = first.model_copy(update={"company_id": CompanyId(uuid4()), "value": "20"})
    assert (
        len(UpdateProjectFactsRequest(changes=[first, second], expected_context_version=1).changes)
        == 2
    )


def decision(**overrides: object) -> UserDecision:
    """Build a recorded user decision, overriding single fields."""
    payload: dict[str, object] = {
        "id": str(DecisionId(uuid4())),
        "project_id": str(PROJECT_ID),
        "outcome": DecisionOutcome.READY,
        "rationale": "Условия приемлемы",
        "context_version": 4,
        "author_user_id": str(USER_ID),
        "created_at": NOW,
    }
    payload.update(overrides)
    return UserDecision.model_validate(payload)


def test_conditional_outcomes_require_a_concrete_condition() -> None:
    """A conditional decision names its condition instead of a disclaimer."""
    assert decision(
        outcome=DecisionOutcome.READY_WITH_CONDITIONS, conditions=["Аванс не более 30%"]
    ).conditions == ["Аванс не более 30%"]
    with pytest.raises(ValidationError, match="at least one concrete condition"):
        decision(outcome=DecisionOutcome.READY_WITH_CONDITIONS)
    with pytest.raises(ValidationError, match="at least one concrete condition"):
        decision(outcome=DecisionOutcome.NEED_MORE_INFO)


def test_artifact_reference_pins_the_version_it_read() -> None:
    """A decision cites an immutable artifact version, not a moving target."""
    with pytest.raises(ValidationError, match="pin the immutable version"):
        decision(based_on_artifact_id=str(ArtifactId(uuid4())))


def test_decision_without_an_artifact_is_valid() -> None:
    """The user may record a decision when no AI conclusion exists."""
    assert decision().based_on_artifact_id is None


def test_create_decision_request_does_not_accept_an_author() -> None:
    """Authorship comes from authorization, never from the request body."""
    assert "author_user_id" not in CreateDecisionRequest.model_fields
    request = CreateDecisionRequest(
        outcome=DecisionOutcome.NOT_READY, rationale="Отрицательный капитал", context_version=1
    )
    assert request.outcome is DecisionOutcome.NOT_READY


def test_create_project_request_is_idempotent_by_client_request_id() -> None:
    """A repeated submission is deduplicated by the client request id."""
    request = CreateProjectRequest(client_request_id=ClientRequestId(uuid4()))
    assert request.title is None


def test_thread_update_requires_an_actual_change() -> None:
    """An empty PATCH is rejected instead of silently doing nothing."""
    with pytest.raises(ValidationError, match="nothing to change"):
        UpdateThreadRequest()
    assert UpdateThreadRequest(archived=True).target_status() is not None
    assert UpdateThreadRequest(title="Новый чат").target_status() is None


def test_pages_are_cursor_based_and_capped() -> None:
    """List responses page by cursor and never exceed the maximum limit."""
    page = Page[CompanySummary](items=[], page=PageInfo(limit=20, has_more=True, next_cursor="c1"))
    assert page.page.next_cursor == "c1"
    with pytest.raises(ValidationError):
        PageInfo(limit=101, has_more=False)


def test_public_dtos_reject_unknown_fields() -> None:
    """A closed contract does not quietly accept an extra field."""
    with pytest.raises(ValidationError):
        project(unexpected="value")
