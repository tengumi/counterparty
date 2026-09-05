"""Загрузка группы, построение матрицы и групповой диалог."""

from __future__ import annotations

from langgraph.runtime import Runtime

from counterparty_agent.ai.selector import answer_comparison_question
from counterparty_agent.ai.validation import validate_comparison_answer
from counterparty_agent.analytics.comparison import compare_snapshots, validate_comparison
from counterparty_agent.analytics.core import analyze_snapshot, validate_analysis
from counterparty_agent.workflow.contracts import WorkflowContext, WorkflowResult, WorkflowState
from counterparty_agent.workflow.review_session import wants_review
from counterparty_agent.workflow.selection import _comparison_selection_views


def _load_comparison(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    del state
    context = runtime.context
    snapshots = tuple(context.source.get_snapshot(item) for item in context._target_snapshot_ids)
    if len(snapshots) < 2 or any(item is None for item in snapshots):
        context.result = WorkflowResult(
            "comparison_incomplete",
            "Не все карточки сравнения доступны. Отправьте полный список компаний заново.",
        )
        return {
            "selected_snapshot_ids": [],
            "comparison_slots": [],
            "status": "comparison_incomplete",
        }
    context._snapshots = tuple(item for item in snapshots if item is not None)
    if len({item.company_id for item in context._snapshots}) != len(context._snapshots):
        raise ValueError("Сравнение должно содержать разные компании")
    return {"status": "analyze_comparison"}


def _analyze_comparison(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    del state
    context = runtime.context
    if not context._snapshots:
        raise RuntimeError("Карточки для сравнения не загружены")
    context._analyses = tuple(
        analyze_snapshot(item, evaluated_at=context.evaluated_at) for item in context._snapshots
    )
    context._comparison = compare_snapshots(context._snapshots, evaluated_at=context.evaluated_at)
    return {"status": "validate_comparison"}


def _validate_comparison(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    context = runtime.context
    if context._comparison is None or len(context._snapshots) != len(context._analyses):
        raise RuntimeError("Результат сравнения для проверки не сформирован")
    for snapshot, analysis in zip(context._snapshots, context._analyses, strict=True):
        validate_analysis(analysis, snapshot)
    validate_comparison(context._comparison, context._snapshots)
    if context._preserve_comparison_state:
        context._focus_snapshot_id = (
            None if context._clear_focus_requested else state.get("focused_snapshot_id")
        )
    if context._focus_snapshot_id is not None:
        focused = [
            (snapshot, analysis)
            for snapshot, analysis in zip(context._snapshots, context._analyses, strict=True)
            if snapshot.snapshot_id == context._focus_snapshot_id
        ]
        if len(focused) != 1:
            raise ValueError("Фокус не принадлежит подтверждённому сравнению")
        context._snapshot, context._analysis = focused[0]
    if context._comparison_question:
        return {"status": "answer_comparison_question"}
    if context._focus_question:
        return {"status": "answer_focused_question"}
    return {"status": "compose_comparison"}


async def _answer_comparison_question(
    state: WorkflowState, runtime: Runtime[WorkflowContext]
) -> WorkflowState:
    context = runtime.context
    if wants_review(context):
        return {"status": "compose_comparison"}
    if context._comparison is None:
        raise RuntimeError("Сравнение для ответа не проверено")
    if context.settings is None:
        context.result = WorkflowResult(
            "llm_unavailable",
            "AI-помощник не настроен. Проверенная сравнительная таблица доступна без модели.",
        )
        return {"status": "compose_comparison"}
    context._grounded_answer = await answer_comparison_question(
        context.settings,
        context.question,
        context._snapshots,
        context._comparison,
        previous_fact_ids=tuple(state.get("last_comparison_fact_ids", [])[:8]),
        client=context.llm_client,
    )
    return {"status": "validate_comparison_answer"}


def _validate_comparison_answer(
    state: WorkflowState, runtime: Runtime[WorkflowContext]
) -> WorkflowState:
    del state
    context = runtime.context
    if context._comparison is None or context._grounded_answer is None:
        raise RuntimeError("Ответ по сравнению отсутствует")
    grounded = context._grounded_answer
    try:
        validate_comparison_answer(grounded, context._snapshots, context._comparison)
    except ValueError:
        context._grounded_answer = None
        context.result = WorkflowResult(
            "validation_failed",
            "Ответ AI-помощник не прошёл проверку по группе. "
            "Проверенная сравнительная таблица остаётся доступна.",
            llm_used=grounded.used_llm,
        )
        return {"status": "compose_comparison"}
    context.result = WorkflowResult(
        grounded.status,
        grounded.answer,
        answer_claims=grounded.claims,
        mode="llm"
        if grounded.used_llm and grounded.status in {"answered", "insufficient_data"}
        else "deterministic",
        model=grounded.model,
        llm_used=grounded.used_llm,
    )
    return {"status": "compose_comparison"}


def _compose_comparison(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    context = runtime.context
    if context._comparison is None:
        raise RuntimeError("Проверенное сравнение отсутствует")
    if context.result is None:
        if context._pending_response_status is not None:
            status, answer = context._pending_response_status, context._pending_response_message
        elif context._focus_snapshot_id is not None:
            position = context._target_snapshot_ids.index(context._focus_snapshot_id) + 1
            status, answer = (
                "focused",
                (
                    f"Открыта карточка №{position} из текущего сравнения. "
                    "Можно задавать вопросы по ней; остальные компании остаются в группе."
                ),
            )
        else:
            status, answer = (
                "compared",
                (
                    "Построена проверенная сравнительная таблица по всем указанным компаниям. "
                    "Это сопоставление доступных фактов, а не рейтинг надёжности. "
                    "Можно задать вопрос по группе или открыть «карточка №2»."
                ),
            )
        context.result = WorkflowResult(status, answer)
    slots = context._staged_comparison_slots or state.get("comparison_slots", [])
    context.result.comparison = context._comparison
    context.result.snapshots = context._snapshots
    context.result.analyses = context._analyses
    context.result.comparison_selections = _comparison_selection_views(slots, context.source)
    context.result.focus_snapshot_id = context._focus_snapshot_id
    context.result.snapshot = context._snapshot if context._focus_snapshot_id is not None else None
    context.result.analysis = context._analysis if context._focus_snapshot_id is not None else None
    context.result.comparison_pending = (
        state.get("comparison_extension_pending", False)
        and context._staged_comparison_slots is None
    )
    if context._preserve_comparison_state:
        if context._clear_focus_requested:
            return {
                "status": context.result.status,
                "focused_snapshot_id": None,
                "last_fact_ids": [],
            }
        return {"status": context.result.status}
    snapshot_ids = [item.snapshot_id for item in context._snapshots]
    group_facts = (
        list(state.get("last_comparison_fact_ids", [])[:8])
        if snapshot_ids == state.get("selected_snapshot_ids", [])
        else []
    )
    focused_facts = (
        list(state.get("last_fact_ids", [])[:8])
        if context._focus_snapshot_id is not None
        and context._focus_snapshot_id == state.get("focused_snapshot_id")
        else []
    )
    if context._grounded_answer is not None and context._grounded_answer.status == "answered":
        if context._comparison_question:
            group_facts = list(context._grounded_answer.fact_ids[:8])
        elif context._focus_question:
            focused_facts = list(context._grounded_answer.fact_ids[:8])
    return {
        "selected_snapshot_id": None,
        "pending_snapshot_ids": [],
        "last_fact_ids": focused_facts,
        "last_comparison_fact_ids": group_facts,
        "selected_snapshot_ids": snapshot_ids,
        "comparison_slots": slots,
        "focused_snapshot_id": context._focus_snapshot_id,
        "comparison_extension_pending": False,
        "status": context.result.status,
    }
