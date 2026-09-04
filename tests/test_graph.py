"""Проверки workflow и памяти на выданном JSON с подменой сетевого адаптера AI-помощник."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.comparison_catalog import build_comparison_fact_catalog
from counterparty_agent.ai.contracts import GroundedAnswer
from counterparty_agent.ai.validation import invalid_grounded_answer
from counterparty_agent.config import Settings
from counterparty_agent.data.identifiers import company_core_name
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import (
    AnalysisResult,
    ComparisonResult,
    CounterpartySnapshot,
    ResolutionStatus,
)
from counterparty_agent.workflow import intents as workflow_module
from counterparty_agent.workflow.builder import build_graph
from counterparty_agent.workflow.contracts import (
    InvalidCandidateSelection,
    WorkflowContext,
    WorkflowResult,
)


@pytest.fixture(scope="module")
def source() -> JsonCounterpartySource:
    """Не добавлять в репозиторий копии карточек и реальные идентификаторы."""

    path = Path(Settings().snapshot_json_path)
    if not path.is_file():
        pytest.skip("Реальный snapshot не настроен в COUNTERPARTY_SNAPSHOT_JSON_PATH")
    return JsonCounterpartySource.from_path(path)


@pytest.fixture(scope="module")
def evaluated_at(source: JsonCounterpartySource) -> datetime:
    return source.snapshots[0].report_at + timedelta(days=30)


@pytest.fixture
async def graph(tmp_path: Path) -> AsyncIterator[Any]:
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "sessions.sqlite3")) as saver:
        yield build_graph(saver)


async def _run(graph: Any, context: WorkflowContext, thread: str = "session-one") -> WorkflowResult:
    await graph.ainvoke({}, config={"configurable": {"thread_id": thread}}, context=context)
    assert context.result is not None
    return context.result


async def test_exact_lookup_runs_analysis_validation_then_composition_without_llm(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    from counterparty_agent.workflow import single

    original_analyze = single.analyze_snapshot
    original_validate = single.validate_analysis

    def analyze(*args: Any, **kwargs: Any) -> Any:
        calls.append("analyze")
        return original_analyze(*args, **kwargs)

    def validate(*args: Any, **kwargs: Any) -> Any:
        calls.append("validate")
        return original_validate(*args, **kwargs)

    async def unexpected_llm(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Детерминированный workflow обратился к LLM", pytrace=False)

    monkeypatch.setattr("counterparty_agent.workflow.single.analyze_snapshot", analyze)
    monkeypatch.setattr("counterparty_agent.workflow.single.validate_analysis", validate)
    monkeypatch.setattr("counterparty_agent.workflow.single.answer_question", unexpected_llm)
    snapshot = source.snapshots[0]
    result = await _run(
        graph, WorkflowContext(source, evaluated_at, question=f"ИНН {snapshot.identity.inn}")
    )

    assert calls == ["analyze", "validate"]
    assert result.status == "analyzed"
    assert result.snapshot is snapshot
    assert result.analysis is not None
    assert result.analysis.bank_risk == snapshot.bank_risk
    assert not result.candidates
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values == {
        "selected_snapshot_id": snapshot.snapshot_id,
        "pending_snapshot_ids": [],
        "source_hash": source.source_hash,
        "status": "analyzed",
        "last_fact_ids": [],
        "selected_snapshot_ids": [],
        "comparison_slots": [],
        "focused_snapshot_id": None,
        "last_comparison_fact_ids": [],
        "comparison_extension_pending": False,
    }


async def test_typo_requires_confirmation_and_only_current_candidate_can_be_selected(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    typo = _fuzzy_query(source)
    first = await _run(graph, WorkflowContext(source, evaluated_at, question=typo))
    assert first.status == "needs_confirmation"
    assert first.snapshot is None and first.analysis is None
    assert 1 <= len(first.candidates) <= 3
    ids = {item.snapshot_id for item in first.candidates}
    forged_id = next(item.snapshot_id for item in source.snapshots if item.snapshot_id not in ids)

    with pytest.raises(InvalidCandidateSelection, match="текущий список"):
        await _run(graph, WorkflowContext(source, evaluated_at, candidate_snapshot_id=forged_id))

    selected = first.candidates[0].snapshot_id
    second = await _run(
        graph, WorkflowContext(source, evaluated_at, candidate_snapshot_id=selected)
    )
    assert second.status == "analyzed"
    assert second.snapshot is not None and second.snapshot.snapshot_id == selected
    with pytest.raises(InvalidCandidateSelection):
        await _run(graph, WorkflowContext(source, evaluated_at, candidate_snapshot_id=selected))


async def test_restore_pending_candidates_preserves_order_without_inventing_scores(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    first = await _run(graph, WorkflowContext(source, evaluated_at, question=_fuzzy_query(source)))
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.status == "needs_confirmation"
    assert [item.snapshot_id for item in restored.candidates] == [
        item.snapshot_id for item in first.candidates
    ]
    assert all(item.match_score is None for item in restored.candidates)
    assert restored.snapshot is None


async def test_restore_keeps_pending_single_lookup_over_completed_group_until_selection(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    typo = _fuzzy_query(source)
    candidate_ids = {item.snapshot_id for item in source.find_by_name_fuzzy(typo).candidates}
    base = tuple(item for item in source.snapshots if item.snapshot_id not in candidate_ids)[:2]
    await _create_group(graph, source, evaluated_at, base)
    await _run(graph, WorkflowContext(source, evaluated_at, question="карточка №1"))
    pending = await _run(graph, WorkflowContext(source, evaluated_at, question=f"Найди {typo}"))
    assert pending.status == "needs_confirmation"
    before = await graph.aget_state({"configurable": {"thread_id": "session-one"}})

    for _ in range(2):
        restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
        assert restored.status == "needs_confirmation" and restored.comparison is None
        assert [item.snapshot_id for item in restored.candidates] == [
            item.snapshot_id for item in pending.candidates
        ]
        assert all(item.match_score is None for item in restored.candidates)
    after = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert after.values["pending_snapshot_ids"] == before.values["pending_snapshot_ids"]
    assert after.values["selected_snapshot_ids"] == before.values["selected_snapshot_ids"]
    assert after.values["focused_snapshot_id"] == before.values["focused_snapshot_id"]

    selected_id = restored.candidates[0].snapshot_id
    selected = await _run(
        graph, WorkflowContext(source, evaluated_at, candidate_snapshot_id=selected_id)
    )
    assert selected.status == "analyzed" and selected.snapshot is not None
    assert selected.snapshot.snapshot_id == selected_id
    assert selected.comparison is None


async def test_explicit_return_to_comparison_cancels_pending_single_lookup(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    await _create_group(graph, source, evaluated_at, source.snapshots[:2])
    pending = await _run(
        graph, WorkflowContext(source, evaluated_at, question=f"Найди {_fuzzy_query(source)}")
    )
    assert pending.status == "needs_confirmation"
    restored = await _run(graph, WorkflowContext(source, evaluated_at, question="Покажи сравнение"))
    assert restored.status == "compared" and restored.comparison is not None
    with pytest.raises(InvalidCandidateSelection):
        await _run(
            graph,
            WorkflowContext(
                source, evaluated_at, candidate_snapshot_id=pending.candidates[0].snapshot_id
            ),
        )


async def test_new_lookup_replaces_pending_candidates(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    first = await _run(graph, WorkflowContext(source, evaluated_at, question=_fuzzy_query(source)))
    selected = first.candidates[0].snapshot_id
    result = await _run(graph, WorkflowContext(source, evaluated_at, question="ИНН 123"))
    assert result.status == "invalid_identifier"
    with pytest.raises(InvalidCandidateSelection):
        await _run(graph, WorkflowContext(source, evaluated_at, candidate_snapshot_id=selected))


async def test_card_memory_is_scoped_and_unknown_question_is_not_a_fake_answer(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    first = await _run(
        graph, WorkflowContext(source, evaluated_at, question=source.snapshots[0].identity.inn)
    )
    reopened = await _run(graph, WorkflowContext(source, evaluated_at, question="Покажи карточку!"))
    assert reopened.snapshot is first.snapshot
    assert reopened.status == "analyzed"

    unrelated = await _run(
        graph, WorkflowContext(source, evaluated_at, question="покажи карточку"), "session-two"
    )
    assert unrelated.status == "no_selection"
    assert unrelated.snapshot is None

    unavailable = await _run(
        graph, WorkflowContext(source, evaluated_at, question="А сколько у неё судов?")
    )
    assert unavailable.status == "llm_unavailable"
    assert unavailable.snapshot is first.snapshot and unavailable.analysis is not None
    assert "не настроен" in unavailable.answer
    assert unavailable.llm_used is False


async def test_multiple_companies_do_not_silently_select_first(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    first, second = source.snapshots[:2]
    result = await _run(
        graph,
        WorkflowContext(
            source, evaluated_at, question=f"Сравни {first.identity.inn} и {second.identity.inn}"
        ),
    )
    assert result.status == "compared"
    assert result.snapshot is None and not result.candidates
    assert result.snapshots == (first, second)
    assert result.comparison is not None
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.status == "compared" and restored.snapshots == (first, second)


async def test_not_found_does_not_mean_absent_risk(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    result = await _run(
        graph,
        WorkflowContext(source, evaluated_at, question="несуществующееимядляпроверкимаршрута"),
    )
    assert result.status == "not_found"
    assert "не означает" in result.answer
    assert result.snapshot is None and result.analysis is None


@pytest.mark.parametrize("label, attribute", [("ИНН", "inn"), ("ОГРН", "ogrn")])
@pytest.mark.parametrize("prefix", ["Подбери похожих на", "Найди группу похожих на", "Сравни"])
async def test_similar_and_single_entity_comparison_do_not_fall_back_to_lookup(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    label: str,
    attribute: str,
    prefix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_analysis(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Неподдерживаемое намерение ошибочно запустило анализ", pytrace=False)

    monkeypatch.setattr("counterparty_agent.workflow.single.analyze_snapshot", unexpected_analysis)
    identifier = getattr(source.snapshots[0].identity, attribute)
    result = await _run(
        graph, WorkflowContext(source, evaluated_at, question=f"{prefix} {label} {identifier}")
    )
    expected = "comparison_invalid_count" if prefix == "Сравни" else "unsupported"
    assert result.status == expected
    assert result.snapshot is None and result.analysis is None
    assert not result.candidates
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.status == "no_selection"


async def test_changed_source_invalidates_selection_and_pending_ids(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    await _run(
        graph, WorkflowContext(source, evaluated_at, question=source.snapshots[0].identity.inn)
    )
    changed = JsonCounterpartySource(source.snapshots, source_hash="0" * 64)
    restored = await _run(graph, WorkflowContext(changed, evaluated_at, restore=True))
    assert restored.status == "no_selection"

    first = await _run(
        graph, WorkflowContext(source, evaluated_at, question=_fuzzy_query(source)), "pending"
    )
    with pytest.raises(InvalidCandidateSelection):
        await _run(
            graph,
            WorkflowContext(
                changed, evaluated_at, candidate_snapshot_id=first.candidates[0].snapshot_id
            ),
            "pending",
        )
    restored = await _run(graph, WorkflowContext(changed, evaluated_at, restore=True), "pending")
    assert restored.status == "no_selection"


async def test_validation_failure_never_publishes_or_remembers_unvalidated_selection(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*args: Any, **kwargs: Any) -> None:
        raise ValueError("Проверка доказательств отклонена")

    monkeypatch.setattr("counterparty_agent.workflow.single.validate_analysis", reject)
    context = WorkflowContext(source, evaluated_at, question=source.snapshots[0].identity.inn)
    with pytest.raises(ValueError, match="Проверка доказательств"):
        await _run(graph, context)
    assert context.result is None
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["selected_snapshot_id"] is None


async def test_sqlite_restart_keeps_only_opaque_session_context(
    tmp_path: Path, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    path = tmp_path / "persistent.sqlite3"
    snapshot = source.snapshots[0]
    question = f"ИНН {snapshot.identity.inn}; private_request_marker_do_not_persist"
    context = WorkflowContext(source, evaluated_at, question=question)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = build_graph(saver)
        first = await _run(graph, context)
        assert first.status == "analyzed"
        async for checkpoint in saver.alist(None):
            values = checkpoint.checkpoint["channel_values"]
            application_keys = {key for key in values if not key.startswith(("__", "branch:"))}
            assert application_keys <= {
                "selected_snapshot_id",
                "pending_snapshot_ids",
                "source_hash",
                "status",
                "last_fact_ids",
                "selected_snapshot_ids",
                "comparison_slots",
                "focused_snapshot_id",
                "last_comparison_fact_ids",
                "comparison_extension_pending",
            }

    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        restored = await _run(
            build_graph(saver), WorkflowContext(source, evaluated_at, restore=True)
        )
        assert restored.status == "analyzed"
        assert restored.snapshot is snapshot

    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT checkpoint, metadata FROM checkpoints").fetchall()
        rows += connection.execute("SELECT value, channel FROM writes").fetchall()
    stored = b"".join(
        value if isinstance(value, bytes) else str(value).encode() for row in rows for value in row
    )
    forbidden = (
        "private_request_marker_do_not_persist",
        question,
        snapshot.identity.inn,
        snapshot.identity.full_name,
        "financial_statements",
        "derived_evidence",
        "canonical_path",
        "typed_value",
    )
    for index, value in enumerate(forbidden):
        if value.encode() in stored:
            pytest.fail(f"Лишние данные в SQLite, проверка {index}", pytrace=False)
    assert "private_request_marker_do_not_persist" not in repr(context)


@pytest.mark.parametrize(
    "question",
    [
        "Какая выручка?",
        "А за предыдущий год?",
        "А за 2023?",
        "А в 2022?",
        "Какие риски?",
        "Поясни подробнее",
        "А сколько у неё судов?",
        "Расскажи о финансах",
        "Покажи суды",
        "Что с судами?",
        "Какая выручка у неё в 2022?",
        "Есть судебные дела?",
        "Каковы финансовые показатели?",
    ],
)
async def test_follow_up_uses_selected_card_and_checks_grounding(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    snapshot = source.snapshots[0]
    await _run(graph, WorkflowContext(source, evaluated_at, question=snapshot.identity.inn))
    result = await _run(graph, _qa_context(source, evaluated_at, question))

    assert result.status == "answered"
    assert result.snapshot is snapshot
    assert result.mode == "llm" and result.llm_used is True
    assert result.answer_claims
    assert calls == [(snapshot.snapshot_id, ())]
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert len(state.values["last_fact_ids"]) == 1


async def test_qa_requires_selection_and_pending_candidate_wins_over_old_card(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    empty = await _run(graph, _qa_context(source, evaluated_at, "Какая выручка?"), "empty")
    assert empty.status == "no_selection"
    await _run(
        graph, WorkflowContext(source, evaluated_at, question=source.snapshots[0].identity.inn)
    )
    pending = await _run(
        graph, WorkflowContext(source, evaluated_at, question=_fuzzy_query(source))
    )
    result = await _run(graph, _qa_context(source, evaluated_at, "Какие у неё суды?"))
    assert result.status == "needs_confirmation"
    assert result.snapshot is None
    assert [item.snapshot_id for item in result.candidates] == [
        item.snapshot_id for item in pending.candidates
    ]
    assert not calls
    confirmed = await _run(
        graph,
        WorkflowContext(
            source,
            evaluated_at,
            candidate_snapshot_id=result.candidates[0].snapshot_id,
            settings=Settings(llm_api_key=None, _env_file=None),
        ),
    )
    assert confirmed.status == "analyzed"
    assert not calls


async def test_qa_context_is_ids_only_and_does_not_cross_company_or_thread(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    first, second = source.snapshots[:2]
    await _run(graph, WorkflowContext(source, evaluated_at, question=first.identity.inn))
    answered = await _run(graph, _qa_context(source, evaluated_at, "Какие риски?"))
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    topic = tuple(state.values["last_fact_ids"])
    assert topic and answered.answer_claims
    await _run(graph, _qa_context(source, evaluated_at, "А за предыдущий год?"))
    assert calls[-1] == (first.snapshot_id, topic)

    switched = await _run(
        graph, _qa_context(source, evaluated_at, f"Какая выручка у ИНН {second.identity.inn}?")
    )
    assert switched.snapshot is second and switched.status == "answered"
    assert calls[-1] == (second.snapshot_id, ())
    isolated = await _run(graph, _qa_context(source, evaluated_at, "Какие риски?"), "other")
    assert isolated.status == "no_selection"

    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.status == "analyzed" and restored.snapshot is second
    assert len(calls) == 3
    changed = JsonCounterpartySource(source.snapshots, source_hash="1" * 64)
    result = await _run(graph, _qa_context(changed, evaluated_at, "Какая выручка?"))
    assert result.status == "no_selection"
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["last_fact_ids"] == []


async def test_question_with_quoted_name_resolves_target_before_qwen(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    snapshot = next(
        item
        for item in source.snapshots
        if source.find_by_name_exact(company_core_name(item.identity.short_name)).status
        is ResolutionStatus.RESOLVED
    )
    name = company_core_name(snapshot.identity.short_name)
    result = await _run(graph, _qa_context(source, evaluated_at, f"Какая выручка у «{name}»?"))
    assert result.status == "answered" and result.snapshot is snapshot
    assert calls == [(snapshot.snapshot_id, ())]


@pytest.mark.parametrize(
    "question, expected",
    [
        ("несуществующееимядляпроверкимаршрута", "not_found"),
        ("Какая выручка у «несуществующееимядляпроверкимаршрута»?", "not_found"),
        ("Какая выручка у ИНН 123?", "invalid_identifier"),
        ("Какая выручка у Ромашки?", "needs_company_identifier"),
        ("Какая выручка у компании Ромашка?", "needs_company_identifier"),
        ("Расскажи про ООО НЕИЗВЕСТНАЯ", "needs_company_identifier"),
        ("Покажи суды по Ромашке", "needs_company_identifier"),
        ("Какая выручка Ромашки?", "needs_company_identifier"),
    ],
)
async def test_unknown_named_target_never_reuses_selected_company(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    expected: str,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    await _run(
        graph, WorkflowContext(source, evaluated_at, question=source.snapshots[0].identity.inn)
    )
    result = await _run(graph, _qa_context(source, evaluated_at, question))
    assert result.status == expected
    assert result.snapshot is None and result.analysis is None
    assert not calls


async def test_grounding_rejection_preserves_card_and_previous_topic(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    await _run(
        graph, WorkflowContext(source, evaluated_at, question=source.snapshots[0].identity.inn)
    )
    answered = await _run(graph, _qa_context(source, evaluated_at, "Какие риски?"))
    before = await graph.aget_state({"configurable": {"thread_id": "session-one"}})

    async def altered(*args: Any, **kwargs: Any) -> GroundedAnswer:
        return GroundedAnswer(
            "answered",
            "Выдуманный вывод модели",
            answered.answer_claims,
            tuple(before.values["last_fact_ids"]),
            "qwen3.7-plus",
            True,
        )

    monkeypatch.setattr("counterparty_agent.workflow.single.answer_question", altered)
    rejected = await _run(graph, _qa_context(source, evaluated_at, "Поясни подробнее"))
    assert rejected.status == "validation_failed"
    assert rejected.snapshot is answered.snapshot
    assert rejected.answer_claims == ()
    assert "Выдуманный" not in rejected.answer
    after = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert after.values["last_fact_ids"] == before.values["last_fact_ids"]

    async def invalid(*args: Any, **kwargs: Any) -> GroundedAnswer:
        return invalid_grounded_answer(used_llm=True)

    monkeypatch.setattr("counterparty_agent.workflow.single.answer_question", invalid)
    fallback = await _run(graph, _qa_context(source, evaluated_at, "Поясни подробнее"))
    assert fallback.status == "validation_failed" and fallback.snapshot is answered.snapshot
    assert fallback.mode == "deterministic" and fallback.llm_used is True


async def test_missing_key_does_not_remove_selected_card(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    snapshot = source.snapshots[0]
    await _run(graph, WorkflowContext(source, evaluated_at, question=snapshot.identity.inn))
    unavailable = await _run(graph, _qa_context(source, evaluated_at, "Какие риски?"))
    assert unavailable.status == "llm_unavailable"
    assert unavailable.snapshot is snapshot and unavailable.analysis is not None
    assert not unavailable.answer_claims and not unavailable.llm_used
    assert unavailable.mode == "deterministic"
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["selected_snapshot_id"] == snapshot.snapshot_id


async def test_qa_checkpoint_keeps_fact_ids_without_question_or_claims(
    tmp_path: Path,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    path = tmp_path / "qa.sqlite3"
    snapshot = source.snapshots[0]
    question = "Какие риски? private_qa_marker_never_persist"
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = build_graph(saver)
        await _run(graph, WorkflowContext(source, evaluated_at, question=snapshot.identity.inn))
        answered = await _run(graph, _qa_context(source, evaluated_at, question))
        state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
        topic = tuple(state.values["last_fact_ids"])
        assert topic
        async for checkpoint in saver.alist(None):
            values = checkpoint.checkpoint["channel_values"]
            keys = {key for key in values if not key.startswith(("__", "branch:"))}
            assert keys <= {
                "selected_snapshot_id",
                "pending_snapshot_ids",
                "source_hash",
                "status",
                "last_fact_ids",
                "selected_snapshot_ids",
                "comparison_slots",
                "focused_snapshot_id",
                "last_comparison_fact_ids",
                "comparison_extension_pending",
            }

    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        result = await _run(
            build_graph(saver), _qa_context(source, evaluated_at, "А за прошлый год?")
        )
        assert result.status == "answered"
        assert calls[-1] == (snapshot.snapshot_id, topic)

    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT checkpoint, metadata FROM checkpoints").fetchall()
        rows += connection.execute("SELECT value, channel FROM writes").fetchall()
    stored = b"".join(
        value if isinstance(value, bytes) else str(value).encode() for row in rows for value in row
    )
    forbidden = (
        question,
        "private_qa_marker_never_persist",
        answered.answer,
        snapshot.identity.inn,
    )
    for index, value in enumerate(forbidden):
        if value.encode() in stored:
            pytest.fail(f"Лишние данные Q&A в SQLite, проверка {index}", pytrace=False)


@pytest.mark.parametrize("count", [2, 10])
async def test_comparison_keeps_every_column_and_never_calls_qwen(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    async def unexpected_llm(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Сравнение не должно вызывать AI-помощник", pytrace=False)

    monkeypatch.setattr("counterparty_agent.workflow.single.answer_question", unexpected_llm)
    snapshots = source.snapshots[:count]
    question = "Сравни " + "; ".join(f"ИНН {item.identity.inn}" for item in snapshots)
    result = await _run(graph, _qa_context(source, evaluated_at, question))
    assert result.status == "compared"
    assert result.snapshots == snapshots
    assert len(result.analyses) == count
    assert result.comparison is not None
    expected_ids = tuple(item.snapshot_id for item in snapshots)
    assert result.comparison.snapshot_ids == expected_ids
    assert all(
        tuple(cell.snapshot_id for cell in row.cells) == expected_ids
        for row in result.comparison.rows
    )
    assert result.snapshot is None and result.analysis is None
    assert result.mode == "deterministic" and not result.llm_used
    assert [item.position for item in result.comparison_selections] == list(range(1, count + 1))
    assert all(item.status == "resolved" for item in result.comparison_selections)
    assert all(
        item.candidates and item.candidates[0].snapshot_id == item.snapshot_id
        for item in result.comparison_selections
    )
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["selected_snapshot_id"] is None
    assert state.values["selected_snapshot_ids"] == list(expected_ids)


@pytest.mark.parametrize("count", [1])
async def test_comparison_rejects_count_before_analysis(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Неверное количество компаний запустило анализ", pytrace=False)

    monkeypatch.setattr("counterparty_agent.workflow.single.analyze_snapshot", unexpected)
    question = "Сравни " + "; ".join(
        f"ИНН {item.identity.inn}" for item in source.snapshots[:count]
    )
    result = await _run(graph, WorkflowContext(source, evaluated_at, question=question))
    assert result.status == "comparison_invalid_count"
    assert result.comparison is None and not result.snapshots
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.status == "no_selection"


async def test_comparison_never_silently_replaces_explicit_year(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail(
            "Запрос заданного года ошибочно запустил автоматическое сравнение", pytrace=False
        )

    monkeypatch.setattr("counterparty_agent.workflow.comparison.compare_snapshots", unexpected)
    first, second = source.snapshots[:2]
    question = f"Сравни ИНН {first.identity.inn}; ИНН {second.identity.inn} за 2020 год"
    result = await _run(graph, WorkflowContext(source, evaluated_at, question=question))
    assert result.status == "comparison_unsupported_period"
    assert result.comparison is None and not result.snapshots
    assert "Уберите указание периода" in result.answer


@pytest.mark.parametrize("name", ['ООО "2020"', 'ООО "За 2020 год"', "ООО 2020"])
def test_year_inside_company_name_is_not_a_comparison_period(name: str) -> None:
    question = f'Сравни {name}; ООО "Пример"'
    plan = workflow_module._parse_workflow_query(question)
    assert not workflow_module._has_unsupported_comparison_period(question, plan)


async def test_mixed_invalid_comparison_keeps_all_positions_without_partial_table(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    snapshot = source.snapshots[0]
    question = (
        f'Сравни ИНН {snapshot.identity.inn}; ИНН 123; ООО "несуществующееимядляпроверкимаршрута"'
    )
    result = await _run(graph, WorkflowContext(source, evaluated_at, question=question))
    assert result.status == "comparison_incomplete"
    assert result.comparison is None and result.snapshots == () and result.analyses == ()
    assert [item.status for item in result.comparison_selections] == [
        "resolved",
        "invalid_identifier",
        "not_found",
    ]
    assert [item.position for item in result.comparison_selections] == [1, 2, 3]
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.status == "comparison_incomplete"
    assert [item.selection_id for item in restored.comparison_selections] == [
        item.selection_id for item in result.comparison_selections
    ]
    corrected = await _run(
        graph,
        WorkflowContext(
            source,
            evaluated_at,
            question=f"Сравни ИНН {snapshot.identity.inn}; ИНН {source.snapshots[1].identity.inn}",
        ),
    )
    assert corrected.status == "compared"


@pytest.mark.parametrize("repeat_identifier", [False, True])
async def test_comparison_never_silently_deduplicates_same_company(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime, repeat_identifier: bool
) -> None:
    first, second = source.snapshots[:2]
    duplicate = f"ИНН {first.identity.inn}" if repeat_identifier else f"ОГРН {first.identity.ogrn}"
    question = f"Сравни ИНН {first.identity.inn}; {duplicate}; ИНН {second.identity.inn}"
    result = await _run(graph, WorkflowContext(source, evaluated_at, question=question))
    assert result.status == "comparison_incomplete"
    assert result.comparison is None and not result.snapshots
    assert [item.status for item in result.comparison_selections] == [
        "resolved",
        "duplicate",
        "resolved",
    ]
    assert [item.position for item in result.comparison_selections] == [1, 2, 3]
    assert result.comparison_selections[1].snapshot_id == first.snapshot_id


async def test_comparison_confirms_each_slot_and_rejects_forged_or_replayed_selection(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    first_typo, second_typo = _independent_fuzzy_queries(source)
    question = f"Сравни {first_typo}; {second_typo}"
    result = await _run(graph, WorkflowContext(source, evaluated_at, question=question))
    assert result.status == "comparison_needs_confirmation"
    assert [item.status for item in result.comparison_selections] == ["needs_confirmation"] * 2
    first_slot, second_slot = result.comparison_selections
    first_id = first_slot.candidates[0].snapshot_id
    second_id = second_slot.candidates[0].snapshot_id
    for slot_id, snapshot_id in [
        (None, first_id),
        ("selection_" + "0" * 24, first_id),
        (first_slot.selection_id, second_id),
        (first_slot.selection_id, None),
    ]:
        with pytest.raises(InvalidCandidateSelection):
            await _run(
                graph,
                WorkflowContext(
                    source,
                    evaluated_at,
                    candidate_selection_id=slot_id,
                    candidate_snapshot_id=snapshot_id,
                ),
            )
    selected = await _run(
        graph,
        WorkflowContext(
            source,
            evaluated_at,
            candidate_selection_id=first_slot.selection_id,
            candidate_snapshot_id=first_id,
        ),
    )
    assert selected.status == "comparison_needs_confirmation" and selected.comparison is None
    assert [item.status for item in selected.comparison_selections] == [
        "resolved",
        "needs_confirmation",
    ]
    with pytest.raises(InvalidCandidateSelection):
        await _run(
            graph,
            WorkflowContext(
                source,
                evaluated_at,
                candidate_selection_id=first_slot.selection_id,
                candidate_snapshot_id=first_id,
            ),
        )
    complete = await _run(
        graph,
        WorkflowContext(
            source,
            evaluated_at,
            candidate_selection_id=second_slot.selection_id,
            candidate_snapshot_id=second_id,
        ),
    )
    assert complete.status == "compared"
    assert tuple(item.snapshot_id for item in complete.snapshots) == (first_id, second_id)
    with pytest.raises(InvalidCandidateSelection):
        await _run(
            graph,
            WorkflowContext(
                source,
                evaluated_at,
                candidate_selection_id=second_slot.selection_id,
                candidate_snapshot_id=second_id,
            ),
        )


async def test_comparison_candidate_cannot_repeat_an_already_resolved_company(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    typo = _fuzzy_query(source)
    candidate = source.find_by_name_fuzzy(typo).candidates[0]
    snapshot = source.get_snapshot(candidate.snapshot_id)
    assert snapshot is not None
    result = await _run(
        graph,
        WorkflowContext(
            source, evaluated_at, question=f"Сравни ИНН {snapshot.identity.inn}; {typo}"
        ),
    )
    assert result.status == "comparison_needs_confirmation"
    slot = result.comparison_selections[1]
    with pytest.raises(InvalidCandidateSelection, match="другой позиции"):
        await _run(
            graph,
            WorkflowContext(
                source,
                evaluated_at,
                candidate_selection_id=slot.selection_id,
                candidate_snapshot_id=snapshot.snapshot_id,
            ),
        )
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.comparison_selections[1].status == "needs_confirmation"


async def test_group_question_never_answers_old_company_and_explicit_member_preserves_group(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    group_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    _mock_group_answer(monkeypatch, group_calls)
    old, first, second = source.snapshots[:3]
    await _run(graph, WorkflowContext(source, evaluated_at, question=old.identity.inn))
    await _run(graph, _qa_context(source, evaluated_at, "Какие риски?"))
    calls.clear()
    await _run(
        graph,
        WorkflowContext(
            source,
            evaluated_at,
            question=f"Сравни ИНН {first.identity.inn}; ИНН {second.identity.inn}",
        ),
    )
    question = await _run(graph, _qa_context(source, evaluated_at, "Какая выручка?"))
    assert question.status == "answered"
    assert question.comparison is not None and question.snapshots == (first, second)
    assert question.snapshot is None and question.llm_used and not calls
    assert group_calls == [((first.snapshot_id, second.snapshot_id), ())]
    restored = await _run(
        graph, WorkflowContext(source, evaluated_at, question="Покажи сравнение!")
    )
    assert restored.status == "compared" and restored.snapshots == (first, second)

    single = await _run(
        graph, _qa_context(source, evaluated_at, f"Какая выручка у ИНН {first.identity.inn}?")
    )
    assert single.status == "answered" and single.snapshot is first
    assert calls == [(first.snapshot_id, ())]
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["selected_snapshot_ids"] == [first.snapshot_id, second.snapshot_id]
    assert state.values["focused_snapshot_id"] == first.snapshot_id
    reopened = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert reopened.status == "focused" and reopened.snapshot is first
    external = await _run(graph, WorkflowContext(source, evaluated_at, question=old.identity.inn))
    assert external.status == "analyzed" and external.comparison is None
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert not state.values["comparison_slots"] and not state.values["selected_snapshot_ids"]


async def test_pending_group_question_preserves_clarifications_and_session_scope(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    first_typo, second_typo = _independent_fuzzy_queries(source)
    pending = await _run(
        graph, WorkflowContext(source, evaluated_at, question=f"Сравни {first_typo}; {second_typo}")
    )
    answered = await _run(graph, _qa_context(source, evaluated_at, "Какие риски?"))
    assert answered.status == "comparison_needs_confirmation"
    assert answered.snapshot is None and answered.comparison is None and not calls
    assert [item.selection_id for item in answered.comparison_selections] == [
        item.selection_id for item in pending.comparison_selections
    ]
    empty = await _run(graph, WorkflowContext(source, evaluated_at, restore=True), "other-thread")
    assert empty.status == "no_selection"
    slot = pending.comparison_selections[0]
    with pytest.raises(InvalidCandidateSelection):
        await _run(
            graph,
            WorkflowContext(
                source,
                evaluated_at,
                candidate_selection_id=slot.selection_id,
                candidate_snapshot_id=slot.candidates[0].snapshot_id,
            ),
            "other-thread",
        )
    changed = JsonCounterpartySource(source.snapshots, source_hash="2" * 64)
    with pytest.raises(InvalidCandidateSelection):
        await _run(
            graph,
            WorkflowContext(
                changed,
                evaluated_at,
                candidate_selection_id=slot.selection_id,
                candidate_snapshot_id=slot.candidates[0].snapshot_id,
            ),
        )
    cleared = await _run(graph, WorkflowContext(changed, evaluated_at, restore=True))
    assert cleared.status == "no_selection"


async def test_rejected_comparison_never_publishes_or_remembers_unvalidated_result(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*args: Any, **kwargs: Any) -> None:
        raise ValueError("Проверка сравнения отклонена")

    monkeypatch.setattr("counterparty_agent.workflow.comparison.validate_comparison", reject)
    first, second = source.snapshots[:2]
    context = WorkflowContext(
        source, evaluated_at, question=f"Сравни {first.identity.inn} и {second.identity.inn}"
    )
    with pytest.raises(ValueError, match="Проверка сравнения"):
        await _run(graph, context)
    assert context.result is None
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["selected_snapshot_id"] is None
    assert state.values["selected_snapshot_ids"] == []


async def test_sqlite_restores_pending_and_complete_group_without_pii_or_matrix(
    tmp_path: Path, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    path = tmp_path / "comparison.sqlite3"
    first_typo, second_typo = _independent_fuzzy_queries(source)
    question = f"Сравни {first_typo}; {second_typo}; private_comparison_query_marker"
    # Маркер не является отдельной компанией: после точки с запятой нет реквизитов или ОПФ.
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        first = await _run(
            build_graph(saver), WorkflowContext(source, evaluated_at, question=question)
        )
        assert first.status == "comparison_needs_confirmation"
        original_ids = [item.selection_id for item in first.comparison_selections]

    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = build_graph(saver)
        restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
        assert [item.selection_id for item in restored.comparison_selections] == original_ids
        assert all(
            candidate.match_score is None
            for slot in restored.comparison_selections
            for candidate in slot.candidates
        )
        for slot in restored.comparison_selections:
            result = await _run(
                graph,
                WorkflowContext(
                    source,
                    evaluated_at,
                    candidate_selection_id=slot.selection_id,
                    candidate_snapshot_id=slot.candidates[0].snapshot_id,
                ),
            )
        assert result.status == "compared"
        snapshot_ids = [item.snapshot_id for item in result.snapshots]

    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = build_graph(saver)
        restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
        assert restored.status == "compared"
        assert [item.snapshot_id for item in restored.snapshots] == snapshot_ids
        async for checkpoint in saver.alist(None):
            values = checkpoint.checkpoint["channel_values"]
            keys = {key for key in values if not key.startswith(("__", "branch:"))}
            assert keys <= {
                "selected_snapshot_id",
                "pending_snapshot_ids",
                "source_hash",
                "status",
                "last_fact_ids",
                "selected_snapshot_ids",
                "comparison_slots",
                "focused_snapshot_id",
                "last_comparison_fact_ids",
                "comparison_extension_pending",
            }
            for slot in values.get("comparison_slots", []):
                assert set(slot) == {
                    "selection_id",
                    "position",
                    "status",
                    "snapshot_id",
                    "candidate_snapshot_ids",
                }

    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT checkpoint, metadata FROM checkpoints").fetchall()
        rows += connection.execute("SELECT value, channel FROM writes").fetchall()
    stored = b"".join(
        value if isinstance(value, bytes) else str(value).encode() for row in rows for value in row
    )
    forbidden = [
        question,
        first_typo,
        second_typo,
        "private_comparison_query_marker",
        "display_value",
        "financial_statements",
        "typed_value",
        "evidence_ids",
    ]
    forbidden.extend(item.identity.inn for item in restored.snapshots)
    forbidden.extend(item.identity.full_name for item in restored.snapshots)
    for index, value in enumerate(forbidden):
        if value.encode() in stored:
            pytest.fail(f"Лишние данные сравнения в SQLite, проверка {index}", pytrace=False)


@pytest.mark.parametrize("question", ["карточка №2", "Подробнее про вторую", "Подробнее про 2-ю"])
async def test_ordinal_focus_and_restore_keep_comparison_without_model(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    group_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    _mock_group_answer(monkeypatch, group_calls)
    first, second = source.snapshots[:2]
    await _create_group(graph, source, evaluated_at, (first, second))
    focused = await _run(graph, _qa_context(source, evaluated_at, question))
    assert focused.status == "focused" and focused.focus_snapshot_id == second.snapshot_id
    assert focused.snapshot is second and focused.snapshots == (first, second)
    assert focused.comparison is not None and not focused.llm_used
    assert not calls and not group_calls
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.focus_snapshot_id == second.snapshot_id
    unfocused = await _run(
        graph, WorkflowContext(source, evaluated_at, question="Покажи сравнение")
    )
    assert unfocused.focus_snapshot_id is None and unfocused.snapshot is None
    assert unfocused.snapshots == (first, second)


@pytest.mark.parametrize("question", ["карточка №99", "подробнее про первую и вторую"])
async def test_invalid_or_ambiguous_ordinal_never_answers_last_focus(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    await _create_group(graph, source, evaluated_at, source.snapshots[:2])
    await _run(graph, WorkflowContext(source, evaluated_at, question="карточка №1"))
    result = await _run(graph, _qa_context(source, evaluated_at, question))
    assert result.status == "comparison_focus_required"
    assert not result.answer_claims and not result.llm_used and not calls
    assert result.snapshot is None


@pytest.mark.parametrize(
    "question", ["ООО «Второй»", "Сравни «Первый» и «Второй»", "Какая прибыль за первый квартал?"]
)
def test_company_names_and_calendar_ordinals_are_not_focus_positions(question: str) -> None:
    assert workflow_module._ordinal_positions(question.casefold()) == []


async def test_explicit_new_company_in_group_request_is_not_ignored(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    _mock_group_answer(monkeypatch, group_calls)
    await _create_group(graph, source, evaluated_at, source.snapshots[:2])
    result = await _run(
        graph,
        _qa_context(source, evaluated_at, "Сравни их с «несуществующееимядляпроверкимаршрута»"),
    )
    assert result.status != "answered" and not group_calls and not result.llm_used
    assert not result.answer_claims


async def test_explicit_identifier_is_not_replaced_by_an_ordinal_focus(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    await _create_group(graph, source, evaluated_at, source.snapshots[:2])
    request = f"Какая выручка у ИНН {source.snapshots[2].identity.inn}; подробнее про вторую"
    result = await _run(graph, _qa_context(source, evaluated_at, request))
    assert result.snapshot is source.snapshots[2]
    assert result.focus_snapshot_id is None and result.comparison is None


async def test_group_and_focused_topics_are_separate_and_group_question_clears_focus(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    group_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    _mock_grounded_answer(monkeypatch, calls)
    _mock_group_answer(monkeypatch, group_calls)
    first, second = source.snapshots[:2]
    await _create_group(graph, source, evaluated_at, (first, second))
    await _run(graph, _qa_context(source, evaluated_at, "У кого какие риски?"))
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    group_topic = tuple(state.values["last_comparison_fact_ids"])
    assert group_topic and state.values["last_fact_ids"] == []
    await _run(graph, WorkflowContext(source, evaluated_at, question="карточка №2"))
    first_answer = await _run(graph, _qa_context(source, evaluated_at, "У неё какая выручка?"))
    assert first_answer.status == "answered" and first_answer.snapshot is second
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    focused_topic = tuple(state.values["last_fact_ids"])
    assert focused_topic and tuple(state.values["last_comparison_fact_ids"]) == group_topic
    await _run(graph, _qa_context(source, evaluated_at, "Поясни подробнее"))
    assert calls == [(second.snapshot_id, ()), (second.snapshot_id, focused_topic)]
    grouped = await _run(graph, _qa_context(source, evaluated_at, "У всех какие риски?"))
    assert grouped.status == "answered" and grouped.focus_snapshot_id is None
    assert grouped.snapshot is None and grouped.snapshots == (first, second)
    assert group_calls[-1] == ((first.snapshot_id, second.snapshot_id), group_topic)
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["last_fact_ids"] == [] and state.values["focused_snapshot_id"] is None


@pytest.mark.parametrize(
    "failed_addition", ["ИНН 123", 'ООО "несуществующееимядляпроверкимаршрута"', "duplicate"]
)
async def test_failed_addition_preserves_committed_group_focus_and_topics(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
    failed_addition: str,
) -> None:
    group_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    _mock_group_answer(monkeypatch, group_calls)
    first, second, third = source.snapshots[:3]
    await _create_group(graph, source, evaluated_at, (first, second))
    await _run(graph, _qa_context(source, evaluated_at, "По группе какие риски?"))
    await _run(graph, WorkflowContext(source, evaluated_at, question="карточка №2"))
    before = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    request = f"ИНН {first.identity.inn}" if failed_addition == "duplicate" else failed_addition
    failed = await _run(
        graph, WorkflowContext(source, evaluated_at, question=f"Добавь к сравнению {request}")
    )
    assert failed.status == "comparison_addition_incomplete" and failed.comparison_pending
    assert failed.snapshots == (first, second) and failed.snapshot is second
    assert len(failed.comparison_selections) == 3
    after = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert after.values["selected_snapshot_ids"] == before.values["selected_snapshot_ids"]
    assert after.values["last_comparison_fact_ids"] == before.values["last_comparison_fact_ids"]
    assert after.values["focused_snapshot_id"] == before.values["focused_snapshot_id"]
    pending_question = await _run(graph, _qa_context(source, evaluated_at, "У кого какие риски?"))
    assert pending_question.status == "comparison_addition_incomplete"
    assert len(group_calls) == 1 and not pending_question.llm_used
    corrected = await _run(
        graph,
        WorkflowContext(
            source, evaluated_at, question=f"Добавь к сравнению ИНН {third.identity.inn}"
        ),
    )
    assert corrected.snapshots == (first, second, third) and not corrected.comparison_pending
    assert corrected.focus_snapshot_id == second.snapshot_id
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["last_comparison_fact_ids"] == []


async def test_fuzzy_addition_restores_then_commits_only_after_confirmation(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    _mock_group_answer(monkeypatch, group_calls)
    typo = _fuzzy_query(source)
    candidates = source.find_by_name_fuzzy(typo).candidates
    candidate_ids = {item.snapshot_id for item in candidates}
    base = tuple(item for item in source.snapshots if item.snapshot_id not in candidate_ids)[:2]
    await _create_group(graph, source, evaluated_at, base)
    await _run(graph, _qa_context(source, evaluated_at, "По группе какие риски?"))
    pending = await _run(
        graph, WorkflowContext(source, evaluated_at, question=f"Добавь к сравнению {typo}")
    )
    assert pending.status == "comparison_addition_needs_confirmation" and pending.comparison_pending
    assert pending.snapshots == base and len(pending.comparison_selections) == 3
    selected = pending.comparison_selections[-1]
    assert selected.status == "needs_confirmation"
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.comparison_pending and restored.snapshots == base
    assert restored.comparison_selections[-1].selection_id == selected.selection_id
    confirmed = await _run(
        graph,
        WorkflowContext(
            source,
            evaluated_at,
            candidate_selection_id=selected.selection_id,
            candidate_snapshot_id=selected.candidates[0].snapshot_id,
        ),
    )
    assert confirmed.status == "compared" and not confirmed.comparison_pending
    assert confirmed.snapshots[:2] == base and len(confirmed.snapshots) == 3
    assert len(group_calls) == 1
    with pytest.raises(InvalidCandidateSelection):
        await _run(
            graph,
            WorkflowContext(
                source,
                evaluated_at,
                candidate_selection_id=selected.selection_id,
                candidate_snapshot_id=selected.candidates[0].snapshot_id,
            ),
        )


async def test_addition_extends_beyond_ten_company_group(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    base = source.snapshots[:10]
    await _create_group(graph, source, evaluated_at, base)
    result = await _run(
        graph,
        WorkflowContext(
            source,
            evaluated_at,
            question=f"Добавь к сравнению ИНН {source.snapshots[10].identity.inn}",
        ),
    )
    assert result.status == "compared" and result.snapshots == source.snapshots[:11]
    assert not result.comparison_pending
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["selected_snapshot_ids"] == [
        item.snapshot_id for item in source.snapshots[:11]
    ]


async def test_show_comparison_clears_focus_even_with_pending_addition(
    graph: Any, source: JsonCounterpartySource, evaluated_at: datetime
) -> None:
    await _create_group(graph, source, evaluated_at, source.snapshots[:2])
    await _run(graph, WorkflowContext(source, evaluated_at, question="карточка №2"))
    await _run(graph, WorkflowContext(source, evaluated_at, question="Добавь к сравнению ИНН 123"))
    restored = await _run(graph, WorkflowContext(source, evaluated_at, question="Покажи сравнение"))
    assert restored.comparison_pending and restored.comparison is not None
    assert restored.focus_snapshot_id is None and restored.snapshot is None
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert state.values["focused_snapshot_id"] is None
    assert state.values["comparison_extension_pending"]


async def test_addition_validation_failure_never_commits_staging_and_restore_remains_usable(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from counterparty_agent.workflow.comparison import validate_comparison as original

    typo = _fuzzy_query(source)
    candidate_ids = {item.snapshot_id for item in source.find_by_name_fuzzy(typo).candidates}
    base = tuple(item for item in source.snapshots if item.snapshot_id not in candidate_ids)[:2]
    await _create_group(graph, source, evaluated_at, base)

    def reject_expansion(
        comparison: ComparisonResult, snapshots: tuple[CounterpartySnapshot, ...]
    ) -> None:
        if len(snapshots) > 2:
            raise ValueError("Расширение не прошло проверку")
        original(comparison, snapshots)

    monkeypatch.setattr(
        "counterparty_agent.workflow.comparison.validate_comparison", reject_expansion
    )
    extra = next(item for item in source.snapshots if item not in base)
    with pytest.raises(ValueError, match="Расширение"):
        await _run(
            graph,
            WorkflowContext(
                source, evaluated_at, question=f"Добавь к сравнению ИНН {extra.identity.inn}"
            ),
        )
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.snapshots == base and not restored.comparison_pending
    pending = await _run(
        graph, WorkflowContext(source, evaluated_at, question=f"Добавь к сравнению {typo}")
    )
    slot = pending.comparison_selections[-1]
    with pytest.raises(ValueError, match="Расширение"):
        await _run(
            graph,
            WorkflowContext(
                source,
                evaluated_at,
                candidate_selection_id=slot.selection_id,
                candidate_snapshot_id=slot.candidates[0].snapshot_id,
            ),
        )
    restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
    assert restored.snapshots == base and restored.comparison_pending
    assert restored.comparison_selections[-1].status == "needs_confirmation"
    monkeypatch.setattr("counterparty_agent.workflow.comparison.validate_comparison", original)
    committed = await _run(
        graph,
        WorkflowContext(
            source,
            evaluated_at,
            candidate_selection_id=slot.selection_id,
            candidate_snapshot_id=slot.candidates[0].snapshot_id,
        ),
    )
    assert len(committed.snapshots) == 3 and not committed.comparison_pending


async def test_group_answer_rejection_preserves_last_successful_topic(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    _mock_group_answer(monkeypatch, calls)
    await _create_group(graph, source, evaluated_at, source.snapshots[:2])
    answered = await _run(graph, _qa_context(source, evaluated_at, "У кого какие риски?"))
    state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    topic = tuple(state.values["last_comparison_fact_ids"])

    async def altered(*args: Any, **kwargs: Any) -> GroundedAnswer:
        return GroundedAnswer(
            "answered",
            "Неподтверждённый текст",
            answered.answer_claims,
            topic,
            "qwen3.7-plus",
            True,
        )

    monkeypatch.setattr(
        "counterparty_agent.workflow.comparison.answer_comparison_question", altered
    )
    rejected = await _run(graph, _qa_context(source, evaluated_at, "По группе поясни подробнее"))
    assert rejected.status == "validation_failed" and rejected.comparison is not None
    assert not rejected.answer_claims and "Неподтверждённый текст" not in rejected.answer
    after = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
    assert tuple(after.values["last_comparison_fact_ids"]) == topic


async def test_group_focus_topic_and_pending_extension_survive_sqlite_without_raw_context(
    tmp_path: Path,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "group-dialogue.sqlite3"
    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    single_calls: list[tuple[str, tuple[str, ...]]] = []
    _mock_group_answer(monkeypatch, calls)
    _mock_grounded_answer(monkeypatch, single_calls)
    base = source.snapshots[:2]
    question = "По группе какие риски? private_group_dialogue_marker"
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = build_graph(saver)
        await _create_group(graph, source, evaluated_at, base)
        answered = await _run(graph, _qa_context(source, evaluated_at, question))
        await _run(graph, WorkflowContext(source, evaluated_at, question="карточка №2"))
        await _run(graph, _qa_context(source, evaluated_at, "У неё какая выручка?"))
        topic_state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
        await _run(
            graph, WorkflowContext(source, evaluated_at, question="Добавь к сравнению ИНН 123")
        )
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = build_graph(saver)
        restored = await _run(graph, WorkflowContext(source, evaluated_at, restore=True))
        assert restored.snapshots == base and restored.comparison_pending
        assert restored.focus_snapshot_id == base[1].snapshot_id
        state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
        assert (
            state.values["last_comparison_fact_ids"]
            == topic_state.values["last_comparison_fact_ids"]
        )
        assert state.values["last_fact_ids"] == topic_state.values["last_fact_ids"]
        isolated = await _run(graph, WorkflowContext(source, evaluated_at, restore=True), "other")
        assert isolated.status == "no_selection" and isolated.focus_snapshot_id is None
        changed = JsonCounterpartySource(source.snapshots, source_hash="9" * 64)
        cleared = await _run(graph, WorkflowContext(changed, evaluated_at, restore=True))
        assert cleared.status == "no_selection"
        cleared_state = await graph.aget_state({"configurable": {"thread_id": "session-one"}})
        for key in (
            "last_fact_ids",
            "last_comparison_fact_ids",
            "selected_snapshot_ids",
            "comparison_slots",
        ):
            assert cleared_state.values[key] == []
        assert cleared_state.values["focused_snapshot_id"] is None
        assert not cleared_state.values["comparison_extension_pending"]
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT checkpoint, metadata FROM checkpoints").fetchall()
        rows += connection.execute("SELECT value, channel FROM writes").fetchall()
    stored = b"".join(
        value if isinstance(value, bytes) else str(value).encode() for row in rows for value in row
    )
    forbidden = [
        question,
        "private_group_dialogue_marker",
        answered.answer,
        "display_value",
        "financial_statements",
    ]
    forbidden.extend(item.identity.inn for item in base)
    forbidden.extend(item.identity.full_name for item in base)
    for index, value in enumerate(forbidden):
        if value.encode() in stored:
            pytest.fail(
                f"Лишние данные группового диалога в SQLite, проверка {index}", pytrace=False
            )


async def _create_group(
    graph: Any,
    source: JsonCounterpartySource,
    evaluated_at: datetime,
    snapshots: tuple[CounterpartySnapshot, ...],
) -> WorkflowResult:
    question = "Сравни " + "; ".join(f"ИНН {item.identity.inn}" for item in snapshots)
    result = await _run(graph, WorkflowContext(source, evaluated_at, question=question))
    assert result.status == "compared"
    return result


def _mock_group_answer(
    monkeypatch: pytest.MonkeyPatch, calls: list[tuple[tuple[str, ...], tuple[str, ...]]]
) -> None:
    async def grounded(
        settings: Settings,
        question: str,
        snapshots: tuple[CounterpartySnapshot, ...],
        comparison: ComparisonResult,
        previous_fact_ids: tuple[str, ...] = (),
        *,
        client: Any = None,
    ) -> GroundedAnswer:
        del settings, question, client
        calls.append((tuple(item.snapshot_id for item in snapshots), previous_fact_ids))
        fact = next(
            item
            for item in build_comparison_fact_catalog(snapshots, comparison)
            if item.topic == "comparison_bank_signal"
        )
        return GroundedAnswer(
            "answered", fact.claim.text, (fact.claim,), (fact.fact_id,), "qwen3.7-plus", True
        )

    monkeypatch.setattr(
        "counterparty_agent.workflow.comparison.answer_comparison_question", grounded
    )


def _independent_fuzzy_queries(source: JsonCounterpartySource) -> tuple[str, str]:
    """Найти два реальных имени с опечатками и непересекающимися кандидатами."""

    found: list[str] = []
    used: set[str] = set()
    for snapshot in source.snapshots:
        words = snapshot.identity.short_name.split()
        choices = [
            (index, word) for index, word in enumerate(words) if len(company_core_name(word)) >= 5
        ]
        if not choices:
            continue
        index, word = max(choices, key=lambda item: len(item[1]))
        position = len(word) // 2
        words[index] = word[:position] + word[position + 1 :]
        typo = " ".join(words)
        if source.find_by_name_exact(typo).status is not ResolutionStatus.NOT_FOUND:
            continue
        resolution = source.find_by_name_fuzzy(typo)
        ids = {item.snapshot_id for item in resolution.candidates}
        if resolution.status is not ResolutionStatus.NEEDS_CONFIRMATION or ids & used:
            continue
        found.append(typo)
        used.update(ids)
        if len(found) == 2:
            return found[0], found[1]
    raise AssertionError("В выданном snapshot не найден независимый fuzzy-сценарий")


def _qa_context(
    source: JsonCounterpartySource, evaluated_at: datetime, question: str
) -> WorkflowContext:
    return WorkflowContext(
        source, evaluated_at, question=question, settings=Settings(llm_api_key=None, _env_file=None)
    )


def _mock_grounded_answer(
    monkeypatch: pytest.MonkeyPatch, calls: list[tuple[str, tuple[str, ...]]]
) -> None:
    async def grounded(
        settings: Settings,
        question: str,
        snapshot: CounterpartySnapshot,
        analysis: AnalysisResult,
        previous_fact_ids: tuple[str, ...] = (),
        *,
        client: Any = None,
    ) -> GroundedAnswer:
        del settings, question, client
        calls.append((snapshot.snapshot_id, previous_fact_ids))
        fact = next(
            item for item in build_fact_catalog(snapshot, analysis) if item.topic == "bank_signal"
        )
        return GroundedAnswer(
            "answered", fact.claim.text, (fact.claim,), (fact.fact_id,), "qwen3.7-plus", True
        )

    monkeypatch.setattr("counterparty_agent.workflow.single.answer_question", grounded)


def _fuzzy_query(source: JsonCounterpartySource) -> str:
    """Внести опечатку в реальное название, не сохраняя его в тестовом коде."""

    for snapshot in source.snapshots:
        words = snapshot.identity.short_name.split()
        choices = [
            (index, word) for index, word in enumerate(words) if len(company_core_name(word)) >= 5
        ]
        if not choices:
            continue
        index, word = max(choices, key=lambda item: len(item[1]))
        position = len(word) // 2
        words[index] = word[:position] + word[position + 1 :]
        typo = " ".join(words)
        if source.find_by_name_exact(typo).status is ResolutionStatus.NOT_FOUND:
            result = source.find_by_name_fuzzy(typo)
            if result.status is ResolutionStatus.NEEDS_CONFIRMATION:
                return typo
    raise AssertionError("В выданном snapshot не найден сценарий с опечаткой")
