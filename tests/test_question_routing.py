"""Короткие ссылки на компании ведут в адресный Q&A, не меняя состав группы."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from benchmarks.synthetic import synthetic_factory
from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.contracts import GroundedAnswer
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import AnalysisResult, CounterpartySnapshot
from counterparty_agent.workflow.builder import build_graph
from counterparty_agent.workflow.contracts import WorkflowContext, WorkflowResult
from counterparty_agent.workflow.intents import _is_question, _ordinal_positions

NOW = datetime(2026, 9, 5, tzinfo=UTC)


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> JsonCounterpartySource:
    path = tmp_path_factory.mktemp("question-routing") / "synthetic.json"
    path.write_text(json.dumps(synthetic_factory(n=3).reports), encoding="utf-8")
    return JsonCounterpartySource.from_path(path)


async def _run(graph: Any, source: JsonCounterpartySource, question: str) -> WorkflowResult:
    context = WorkflowContext(
        source, NOW, question=question, settings=Settings(_env_file=None, llm_api_key=None)
    )
    await graph.ainvoke({}, config={"configurable": {"thread_id": "routing"}}, context=context)
    assert context.result is not None
    return context.result


def _mock_single_answer(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    async def answer(
        settings: Settings,
        question: str,
        snapshot: CounterpartySnapshot,
        analysis: AnalysisResult,
        **kwargs: Any,
    ) -> GroundedAnswer:
        calls.append(snapshot.snapshot_id)
        fact = next(
            item for item in build_fact_catalog(snapshot, analysis) if item.topic == "bank_signal"
        )
        return GroundedAnswer(
            "answered", fact.claim.text, (fact.claim,), (fact.fact_id,), "synthetic", True
        )

    async def unexpected_group_answer(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Адресный вопрос не должен отвечать по всей группе")

    monkeypatch.setattr("counterparty_agent.workflow.single.answer_question", answer)
    monkeypatch.setattr(
        "counterparty_agent.workflow.comparison.answer_comparison_question",
        unexpected_group_answer,
    )


@pytest.mark.parametrize(
    "question",
    [
        "А почему 1 требует внимания?",
        "А почему №1 требует внимания?",
        "Почему первая требует внимания?",
        "Почему 1-я требует внимания?",
        "Какие риски у 1?",
        "Почему у 1 суды?",
        "1 требует внимания?",
    ],
)
async def test_shorthand_question_selects_one_company_and_keeps_comparison(
    source: JsonCounterpartySource, monkeypatch: pytest.MonkeyPatch, question: str
) -> None:
    graph = build_graph(InMemorySaver())
    first, second = source.snapshots[:2]
    await _run(graph, source, f"Сравни ИНН {first.identity.inn}; ИНН {second.identity.inn}")
    await _run(graph, source, "карточка №2")
    calls: list[str] = []
    _mock_single_answer(monkeypatch, calls)

    result = await _run(graph, source, question)

    assert result.status == "answered"
    assert result.snapshot is first and result.focus_snapshot_id == first.snapshot_id
    assert result.snapshots == (first, second) and result.comparison is not None
    assert calls == [first.snapshot_id]
    assert result.answer_claims and result.llm_used


@pytest.mark.parametrize(
    "question",
    [
        "Почему 0 требует внимания?",
        "Почему 99 требует внимания?",
        "Почему №99 требует внимания?",
        "Почему 1 и 2 требуют внимания?",
        "Почему 1, 2 требуют внимания?",
        "Почему первая или №2 требует внимания?",
        "Почему №1 или вторая требует внимания?",
    ],
)
async def test_invalid_reference_never_falls_back_to_last_focus(
    source: JsonCounterpartySource, monkeypatch: pytest.MonkeyPatch, question: str
) -> None:
    graph = build_graph(InMemorySaver())
    first, second = source.snapshots[:2]
    await _run(graph, source, f"Сравни ИНН {first.identity.inn}; ИНН {second.identity.inn}")
    await _run(graph, source, "карточка №2")
    calls: list[str] = []
    _mock_single_answer(monkeypatch, calls)

    result = await _run(graph, source, question)

    assert result.status == "comparison_focus_required"
    assert result.snapshot is None and not result.answer_claims and not result.llm_used
    assert not calls


@pytest.mark.parametrize(
    "question",
    [
        "Почему 2025 требует внимания?",
        "Почему 1 января требует внимания?",
        "Почему 01.02.2025 требует внимания?",
        "Почему 2025-01-02 требует внимания?",
        "Почему 1 квартал требует внимания?",
        "Почему первый квартал требует внимания?",
        "Почему 1 млн рублей требует внимания?",
        "Почему 1 000 рублей требует внимания?",
        "Почему 1,5 млн требует внимания?",
        "Почему 1% требует внимания?",
        "Почему 1 судебное дело требует внимания?",
    ],
)
def test_dates_and_amounts_are_not_company_positions(question: str) -> None:
    assert _ordinal_positions(question.casefold()) == []


@pytest.mark.parametrize("question", ["почему требует внимания", "требует внимания", "риск"])
def test_attention_and_risk_phrases_are_questions(question: str) -> None:
    assert _is_question(question)


async def test_explicit_identifier_takes_precedence_over_shorthand(
    source: JsonCounterpartySource, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = build_graph(InMemorySaver())
    first, second, explicit = source.snapshots
    await _run(graph, source, f"Сравни ИНН {first.identity.inn}; ИНН {second.identity.inn}")
    calls: list[str] = []
    _mock_single_answer(monkeypatch, calls)

    result = await _run(
        graph, source, f"Почему 1 требует внимания? Вопрос про ИНН {explicit.identity.inn}"
    )

    assert result.status == "answered" and result.snapshot is explicit
    assert result.focus_snapshot_id is None and result.comparison is None
    assert calls == [explicit.snapshot_id]


async def test_targeted_attention_runs_real_graph_catalog_selector_and_validation(
    source: JsonCounterpartySource,
) -> None:
    """Подменён только сетевой транспорт; компания и основания проходят весь граф."""

    graph = build_graph(InMemorySaver())
    first, second = source.snapshots[:2]
    await _run(graph, source, f"Сравни ИНН {first.identity.inn}; ИНН {second.identity.inn}")
    await _run(graph, source, "карточка №2")
    seen_topics: list[set[str]] = []
    router_calls: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> Any:
        content = kwargs["messages"][1]["content"]
        payload = json.loads(content.split("<INPUT_DATA>\n", 1)[1].split("\n</INPUT_DATA>", 1)[0])
        if "session" in payload:
            router_calls.append(payload)
            output = {"action": "ask", "position": 1}
        else:
            facts = payload["approved_facts"]
            seen_topics.append({item["topic"] for item in facts})
            selected = [
                next(item["fact_id"] for item in facts if item["topic"] == topic)
                for topic in ("bank_signal", "attention_signal")
            ]
            selected.append(
                next(item["fact_id"] for item in facts if item["metric"] == "reason_unavailable")
            )
            output = {"status": "answered", "fact_ids": selected}
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(output)),
                    finish_reason="stop",
                )
            ]
        )

    context = WorkflowContext(
        source,
        NOW,
        question="А почему 1 требует внимания?",
        settings=Settings(_env_file=None, llm_api_key=SecretStr("unit-test-not-a-real-key")),
        llm_client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    await graph.ainvoke({}, config={"configurable": {"thread_id": "routing"}}, context=context)
    result = context.result
    assert result is not None and result.status == "answered" and result.llm_used
    assert result.focus_snapshot_id == first.snapshot_id and result.snapshots == (first, second)
    assert len(router_calls) == 1
    assert router_calls[0]["session"]["focused_position"] == 2
    assert seen_topics == [{"bank_signal", "attention_signal"}]
    assert len(result.answer_claims) == 3
    analysis = analyze_snapshot(first, evaluated_at=NOW)
    allowed = {item.evidence_id for item in (*first.evidence, *analysis.derived_evidence)}
    assert all(set(claim.evidence_ids) <= allowed for claim in result.answer_claims)
    state = await graph.aget_state({"configurable": {"thread_id": "routing"}})
    assert state.values["focused_snapshot_id"] == first.snapshot_id
    assert len(state.values["last_fact_ids"]) == 3
