"""Context assembly and thread isolation of the prompt layers (AG-02)."""

from uuid import UUID

from counterparty_agent.harness import (
    AgentContext,
    CompanyContext,
    build_context,
    thread_workspace_root,
)

TENANT = UUID("22222222-2222-4222-8222-222222222222")
PROJECT = UUID("33333333-3333-4333-8333-333333333333")
THREAD_A = UUID("44444444-4444-4444-8444-444444444444")
THREAD_B = UUID("55555555-5555-4555-8555-555555555555")
COMPANY = UUID("11111111-1111-4111-8111-111111111111")
REPORT = UUID("de305d54-75b4-431b-adb2-eb6b9e546014")


def context(thread_id: UUID, title: str) -> AgentContext:
    """Build a context for one thread of the shared project."""
    return build_context(
        project_id=PROJECT,
        tenant_id=TENANT,
        title="Supply check",
        workflow_status="in_progress",
        context_version=4,
        companies=[
            CompanyContext(
                company_id=COMPANY, report_id=REPORT, slot=2, role="supplier", inn="7449088645"
            ),
            CompanyContext(company_id=COMPANY, report_id=REPORT, slot=1, role="supplier"),
        ],
        thread_id=thread_id,
        thread_title=title,
        thread_status="active",
    )


def test_project_layer_carries_its_version_and_pinned_reports() -> None:
    """Project layer carries its version and pinned reports."""
    rendered = context(THREAD_A, "Delivery terms").render()
    assert "4" in rendered
    assert str(REPORT) in rendered


def test_a_thread_context_never_mentions_a_sibling_thread() -> None:
    """Threads of one project share the project layer, not each other."""
    rendered = context(THREAD_A, "Delivery terms").render()
    assert "Delivery terms" in rendered
    assert "Warehouse letter" not in rendered
    assert str(THREAD_B) not in rendered


def test_the_workspace_root_is_scoped_to_the_thread() -> None:
    """The workspace root is scoped to the thread."""
    rendered = context(THREAD_A, "Delivery terms").render()
    assert thread_workspace_root(PROJECT, THREAD_A) in rendered
    assert thread_workspace_root(PROJECT, THREAD_B) not in rendered
