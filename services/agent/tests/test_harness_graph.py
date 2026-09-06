"""The harness answers a business question through MCP tools (AG-01..AG-03)."""

from uuid import UUID

import pytest
from harness_fixtures import CAPITAL_REF, INN, PROCEEDS_REF, ScriptedChatModel, report_tools
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from counterparty_agent.config import AgentSettings
from counterparty_agent.harness import (
    AgentContext,
    CompanyContext,
    DeterministicChatModel,
    RunEvidenceLedger,
    build_context,
    create_chat_model,
    create_harness,
    run_turn,
    validate_answer,
)

PROJECT = UUID("33333333-3333-4333-8333-333333333333")
THREAD_A = UUID("44444444-4444-4444-8444-444444444444")
THREAD_B = UUID("55555555-5555-4555-8555-555555555555")
TENANT = UUID("22222222-2222-4222-8222-222222222222")
REPORT = UUID("de305d54-75b4-431b-adb2-eb6b9e546014")
QUESTION = f"Supplier {INN} wants an 80 percent prepayment. What do the figures say?"


def context_for(thread_id: UUID, title: str = "Delivery terms") -> AgentContext:
    """Build the context of one thread of the shared project."""
    return build_context(
        project_id=PROJECT,
        tenant_id=TENANT,
        title="Supply check",
        workflow_status="in_progress",
        context_version=1,
        companies=[
            CompanyContext(company_id=UUID(int=1), report_id=REPORT, slot=1, role="supplier")
        ],
        thread_id=thread_id,
        thread_title=title,
        thread_status="active",
    )


def config_for(thread_id: UUID) -> RunnableConfig:
    """Build the checkpoint config LangGraph keys the thread state by."""
    return {"configurable": {"thread_id": str(thread_id)}, "recursion_limit": 12}


def test_the_default_provider_needs_no_model_api() -> None:
    """The default provider needs no model api."""
    model = create_chat_model(AgentSettings())
    assert isinstance(model, DeterministicChatModel)


async def test_the_agent_answers_from_mcp_tools_with_resolvable_refs() -> None:
    """The agent answers from mcp tools with resolvable refs."""
    ledger = RunEvidenceLedger()
    graph = create_harness(
        model=DeterministicChatModel(),
        tools=report_tools(),
        context=context_for(THREAD_A),
        ledger=ledger,
        checkpointer=InMemorySaver(),
    )
    result = await run_turn(graph, question=QUESTION, config=config_for(THREAD_A), ledger=ledger)

    assert PROCEEDS_REF in result.observed_refs
    assert CAPITAL_REF in result.observed_refs
    assert f"[evidence:{PROCEEDS_REF}]" in result.answer
    assert result.grounded
    assert validate_answer(result.answer, ledger).ok


async def test_a_missing_section_is_named_instead_of_reported_as_zero() -> None:
    """A missing section is named instead of reported as zero."""
    ledger = RunEvidenceLedger()
    graph = create_harness(
        model=DeterministicChatModel(),
        tools=report_tools(),
        context=context_for(THREAD_A),
        ledger=ledger,
        checkpointer=InMemorySaver(),
    )
    result = await run_turn(graph, question=QUESTION, config=config_for(THREAD_A), ledger=ledger)
    assert "licenses" in result.answer


async def test_an_ungrounded_answer_is_repaired_before_it_is_published() -> None:
    """The model gets one chance to cite; what stays ungrounded is removed."""
    model = ScriptedChatModel(
        script=[
            AIMessage(content="Capitals are -300000 and the supplier is safe."),
            AIMessage(content="Capitals are -300000 and the supplier is safe."),
        ]
    )
    ledger = RunEvidenceLedger(refs={PROCEEDS_REF})
    graph = create_harness(
        model=model,
        tools=report_tools(),
        context=context_for(THREAD_A),
        ledger=ledger,
        checkpointer=InMemorySaver(),
    )
    result = await run_turn(graph, question=QUESTION, config=config_for(THREAD_A), ledger=ledger)

    assert result.model_repair_attempted
    assert not result.grounded
    assert "-300000" not in result.answer
    assert validate_answer(result.answer, ledger).ok


async def test_a_sibling_thread_history_never_reaches_the_model() -> None:
    """Two chats of one project share the project layer, not their messages."""
    model = DeterministicChatModel()
    checkpointer = InMemorySaver()
    ledger_a = RunEvidenceLedger()
    graph_a = create_harness(
        model=model,
        tools=report_tools(),
        context=context_for(THREAD_A, "Delivery terms"),
        ledger=ledger_a,
        checkpointer=checkpointer,
    )
    await run_turn(graph_a, question=QUESTION, config=config_for(THREAD_A), ledger=ledger_a)

    seen_before = len(model.seen_prompts)
    ledger_b = RunEvidenceLedger()
    graph_b = create_harness(
        model=model,
        tools=report_tools(),
        context=context_for(THREAD_B, "Warehouse letter"),
        ledger=ledger_b,
        checkpointer=checkpointer,
    )
    await run_turn(
        graph_b,
        question="Who signed the warehouse letter?",
        config=config_for(THREAD_B),
        ledger=ledger_b,
    )

    later = model.seen_prompts[seen_before:]
    assert later
    for prompt in later:
        texts = [message.text() for message in prompt if isinstance(message, HumanMessage)]
        assert all(QUESTION not in text for text in texts)
        assert all("Delivery terms" not in message.text() for message in prompt)


async def test_the_same_thread_keeps_its_own_history() -> None:
    """The same thread keeps its own history."""
    model = DeterministicChatModel()
    checkpointer = InMemorySaver()
    ledger = RunEvidenceLedger()
    graph = create_harness(
        model=model,
        tools=report_tools(),
        context=context_for(THREAD_A),
        ledger=ledger,
        checkpointer=checkpointer,
    )
    await run_turn(graph, question=QUESTION, config=config_for(THREAD_A), ledger=ledger)
    await run_turn(
        graph, question="And what about capitals?", config=config_for(THREAD_A), ledger=ledger
    )

    last = model.seen_prompts[-1]
    assert any(QUESTION in message.text() for message in last)


async def test_without_an_inn_the_agent_asks_instead_of_guessing() -> None:
    """Without an inn the agent asks instead of guessing."""
    ledger = RunEvidenceLedger()
    graph = create_harness(
        model=DeterministicChatModel(),
        tools=report_tools(),
        context=build_context(
            project_id=PROJECT,
            tenant_id=TENANT,
            title="Supply check",
            workflow_status="draft",
            context_version=0,
            companies=[],
            thread_id=THREAD_A,
            thread_title="New chat",
            thread_status="active",
        ),
        ledger=ledger,
        checkpointer=InMemorySaver(),
    )
    result = await run_turn(
        graph,
        question="Is this counterparty safe?",
        config=config_for(THREAD_A),
        ledger=ledger,
    )
    assert result.answer.endswith("?")
    assert result.observed_refs == ()


@pytest.mark.parametrize("provider", ["deterministic"])
def test_the_provider_comes_from_configuration(provider: str) -> None:
    """The provider comes from configuration."""
    settings = AgentSettings(model_provider=provider, model_id="custom-id")
    assert create_chat_model(settings).model_id == "custom-id"  # type: ignore[attr-defined]


def test_real_provider_uses_configured_endpoint_and_secret() -> None:
    """Configure an OpenAI-compatible provider without making a network call."""
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    settings = AgentSettings(
        model_provider="openai",
        model_id="configured-model",
        model_base_url="https://example.test/v1",
        model_api_key=SecretStr("test-secret"),
        model_max_tokens=4096,
    )
    model = create_chat_model(settings)
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "configured-model"
    assert model.max_tokens == 4096
    assert model.openai_api_base == "https://example.test/v1"
    assert isinstance(model.openai_api_key, SecretStr)
    assert model.openai_api_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(settings)
