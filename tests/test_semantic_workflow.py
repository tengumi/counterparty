"""LLM понимает запрос, но адресаты, память и факты проверяются полным графом."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.contracts import GroundedAnswer
from counterparty_agent.ai.router import IntentPlan, RouterResult
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import AnalysisResult, CounterpartySnapshot
from counterparty_agent.workflow.builder import build_graph
from counterparty_agent.workflow.contracts import WorkflowContext, WorkflowResult
from counterparty_agent.workflow.semantic import _target_plan


@pytest.fixture(scope="module")
def source() -> JsonCounterpartySource:
    path = Path(Settings().snapshot_json_path)
    if not path.is_file():
        pytest.skip("Реальный snapshot не настроен")
    return JsonCounterpartySource.from_path(path)


@pytest.fixture
def harness(source: JsonCounterpartySource, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Подменяем только решения модели; поиск, аналитика, граф и ledger настоящие."""

    class Harness:
        graph = build_graph(InMemorySaver())
        evaluated_at: datetime = source.snapshots[0].report_at + timedelta(days=30)
        plan = IntentPlan(action="ask")
        failure: str | None = None

        def __init__(self) -> None:
            self.routes: list[tuple[str, dict[str, Any]]] = []
            self.answers: list[tuple[str, str]] = []

        async def run(
            self, question: str = "", *, thread: str = "one", **kwargs: Any
        ) -> WorkflowResult:
            context = WorkflowContext(
                source,
                self.evaluated_at,
                question=question,
                settings=Settings(_env_file=None, llm_api_key=SecretStr("test-only-key")),
                **kwargs,
            )
            await self.graph.ainvoke(
                {}, config={"configurable": {"thread_id": thread}}, context=context
            )
            assert context.result is not None
            return context.result

        async def state(self, thread: str = "one") -> dict[str, Any]:
            state = await self.graph.aget_state({"configurable": {"thread_id": thread}})
            return dict(state.values)

    harness = Harness()

    async def route(
        settings: Any, question: str, session: dict[str, Any], **kwargs: Any
    ) -> RouterResult:
        harness.routes.append((question, session))
        return RouterResult(
            None if harness.failure else harness.plan,
            "llm_unavailable" if harness.failure else "routed",
            True,
            "test-model",
        )

    async def answer(
        settings: Any,
        question: str,
        snapshot: CounterpartySnapshot,
        analysis: AnalysisResult,
        **kwargs: Any,
    ) -> GroundedAnswer:
        harness.answers.append((question, snapshot.snapshot_id))
        fact = next(
            item for item in build_fact_catalog(snapshot, analysis) if item.topic == "bank_signal"
        )
        return GroundedAnswer(
            "answered", fact.claim.text, (fact.claim,), (fact.fact_id,), "test-model", True
        )

    monkeypatch.setattr("counterparty_agent.workflow.semantic.route_intent", route)
    monkeypatch.setattr("counterparty_agent.workflow.single.answer_question", answer)
    return harness


@pytest.mark.parametrize(
    "question",
    [
        "Из-за чего этот контрагент надежен?",
        "А каккие есть судебные дела?",
        "На чём основана эта оценка?",
    ],
)
async def test_free_followup_reaches_llm_with_current_company(
    source: JsonCounterpartySource,
    harness: Any,
    question: str,
) -> None:
    snapshot = source.snapshots[0]
    await harness.run(snapshot.identity.inn)
    assert not harness.routes
    result = await harness.run(question)
    assert result.status == "answered" and result.snapshot is snapshot
    assert result.llm_used and result.answer_claims
    assert harness.answers == [(question, snapshot.snapshot_id)]
    assert harness.routes[0][1]["selected_company"]["inn"] == snapshot.identity.inn


async def test_first_message_can_find_and_answer_without_exact_command(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    snapshot = source.snapshots[0]
    question = f"Мне предлагают договор с ИНН {snapshot.identity.inn}, что известно о его рисках?"
    harness.plan = IntentPlan(action="ask", targets=(snapshot.identity.inn,))
    result = await harness.run(question)
    assert result.status == "answered" and result.snapshot is snapshot
    assert harness.routes[0][0] == question and harness.answers[0][0] == question


async def test_lookup_by_natural_name_uses_resolver_and_marks_router_call(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    snapshot = source.snapshots[0]
    name = snapshot.identity.short_name
    harness.plan = IntentPlan(action="lookup", targets=(name,))
    result = await harness.run(f"Мне нужна информация: {name}")
    assert result.status == "analyzed" and result.snapshot is snapshot
    assert result.mode == "deterministic" and result.llm_used
    assert not harness.answers


@pytest.mark.parametrize(
    "question",
    [
        "Какая прибыль у ООО Ромашка?",
        "Какие риски у компании «Точно не найденная фирма»?",
    ],
)
async def test_model_cannot_drop_new_company_and_answer_previous_card(
    source: JsonCounterpartySource,
    harness: Any,
    question: str,
) -> None:
    snapshot = source.snapshots[0]
    await harness.run(snapshot.identity.inn)
    result = await harness.run(question)
    assert result.status == "routing_failed" and not harness.answers
    assert not result.answer_claims and result.snapshot is snapshot
    assert (await harness.state())["selected_snapshot_id"] == snapshot.snapshot_id


async def test_model_cannot_drop_or_correct_explicit_identifier(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    first, second = source.snapshots[:2]
    await harness.run(first.identity.inn)
    result = await harness.run(f"Есть ли суды у ИНН {second.identity.inn}?")
    assert result.status == "routing_failed" and not harness.answers
    assert (await harness.state())["selected_snapshot_id"] == first.snapshot_id


async def test_unknown_literal_target_does_not_fall_back_to_previous_card(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    await harness.run(source.snapshots[0].identity.inn)
    name = 'ООО "Точно-неизвестный-контрагент-для-проверки"'
    harness.plan = IntentPlan(action="ask", targets=(name,))
    result = await harness.run(f"Есть ли судебные дела у {name}?")
    assert result.status in {"not_found", "needs_confirmation"}
    assert not harness.answers and not result.answer_claims


async def test_failed_router_preserves_single_topic_and_session_privacy(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    snapshot = source.snapshots[0]
    await harness.run(snapshot.identity.inn)
    await harness.run("Что известно?")
    before = await harness.state()
    harness.failure = "provider"
    result = await harness.run("На чём основана оценка?")
    after = await harness.state()
    assert result.status == "llm_unavailable" and result.snapshot is snapshot
    assert result.llm_used and not result.answer_claims
    assert {k: v for k, v in before.items() if k != "status"} == {
        k: v for k, v in after.items() if k != "status"
    }
    assert "Что известно" not in repr(after) and "approved_facts" not in repr(after)
    harness.failure = None
    empty = await harness.run("Какие у неё риски?", thread="other")
    assert empty.status == "no_selection"
    assert harness.routes[-1][1]["selected_company"] is None
    assert harness.routes[-1][1]["companies"] == []


async def _group(source: JsonCounterpartySource, harness: Any) -> WorkflowResult:
    targets = tuple(item.identity.inn for item in source.snapshots[:3])
    harness.plan = IntentPlan(action="compare", targets=targets)
    return await harness.run("Сопоставь предложения: " + "; ".join(targets))


async def test_group_focus_then_compare_her_means_one_company(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    first = await _group(source, harness)
    assert first.status == "compared"
    harness.plan = IntentPlan(action="show", position=2)
    await harness.run("Давай подробнее про вторую")
    target = source.snapshots[3]
    harness.plan = IntentPlan(
        action="compare", targets=(target.identity.inn,), include_current=True
    )
    result = await harness.run(f"Сравни её с ИНН {target.identity.inn}")
    assert result.status == "compared"
    assert result.snapshots == (source.snapshots[1], target)


async def test_compare_current_without_focus_requires_clarification(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    await _group(source, harness)
    target = source.snapshots[3]
    harness.plan = IntentPlan(
        action="compare", targets=(target.identity.inn,), include_current=True
    )
    result = await harness.run(f"Сравни её с ИНН {target.identity.inn}")
    assert result.status == "comparison_focus_required"
    assert result.snapshots == source.snapshots[:3]


async def test_period_at_start_cannot_be_hidden_by_fragment_spans(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    targets = tuple(item.identity.inn for item in source.snapshots[:2])
    harness.plan = IntentPlan(action="compare", targets=targets)
    result = await harness.run(f"Сравни 2024 ИНН {targets[0]} и ИНН {targets[1]}")
    assert result.status == "comparison_unsupported_period" and result.comparison is None


async def test_invalid_ordinal_cannot_silently_select_an_existing_position(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    await _group(source, harness)
    harness.plan = IntentPlan(action="ask", position=1)
    result = await harness.run("Почему 99 требует внимания?")
    assert result.status == "comparison_focus_required" and not harness.answers
    assert result.snapshots == source.snapshots[:3]


async def test_addition_and_group_failure_keep_committed_selection(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    await _group(source, harness)
    target = source.snapshots[3]
    harness.plan = IntentPlan(action="add_to_comparison", targets=(target.identity.inn,))
    added = await harness.run(f"Давайте включим в эту группу ИНН {target.identity.inn}")
    assert added.snapshots == source.snapshots[:4]
    harness.failure = "provider"
    result = await harness.run("Как дела у этой группы?")
    assert result.status == "llm_unavailable" and result.snapshots == added.snapshots
    assert not result.answer_claims


async def test_no_key_does_not_turn_arbitrary_question_into_company_search(
    source: JsonCounterpartySource,
) -> None:
    graph = build_graph(InMemorySaver())
    context = WorkflowContext(
        source,
        source.snapshots[0].report_at,
        question="Из-за чего этот контрагент надежен?",
        settings=Settings(_env_file=None, llm_api_key=None),
    )
    await graph.ainvoke({}, config={"configurable": {"thread_id": "offline"}}, context=context)
    assert context.result is not None and context.result.status == "llm_unavailable"
    assert not context.result.llm_used and not context.result.candidates


async def test_explicit_large_list_does_not_depend_on_llm_output_limit(
    source: JsonCounterpartySource,
    harness: Any,
) -> None:
    snapshots = source.snapshots[:100]
    assert len(snapshots) > 10
    result = await harness.run(
        "Сравни " + "; ".join(f"ИНН {item.identity.inn}" for item in snapshots)
    )
    assert result.status == "compared" and result.snapshots == snapshots
    assert not harness.routes and not result.llm_used


def test_target_spans_refer_to_original_question_not_fragments() -> None:
    question = "Сравни 2024: ООО Ромашка и ООО Василёк"
    plan = _target_plan(
        IntentPlan(action="compare", targets=("ООО Ромашка", "ООО Василёк")),
        question,
    )
    for mention in plan.mentions:
        assert question[mention.span_start : mention.span_end] == mention.raw_text


async def test_named_comparison_does_not_ignore_requested_year(harness: Any) -> None:
    harness.plan = IntentPlan(action="compare", targets=("ООО Ромашка", "ООО Василёк"))
    result = await harness.run("Сравни 2024: ООО Ромашка и ООО Василёк")
    assert result.status == "comparison_unsupported_period"
