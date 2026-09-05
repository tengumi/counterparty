"""Загрузка, анализ и диалог одной компании."""

from __future__ import annotations

from langgraph.runtime import Runtime

from counterparty_agent.ai.selector import answer_question
from counterparty_agent.ai.validation import validate_grounded_answer
from counterparty_agent.analytics.core import analyze_snapshot, validate_analysis
from counterparty_agent.workflow.contracts import WorkflowContext, WorkflowResult, WorkflowState
from counterparty_agent.workflow.review_session import wants_review
from counterparty_agent.workflow.selection import _no_selection


def _load_snapshot(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    del state
    context = runtime.context
    if context._target_snapshot_id is not None:
        context._snapshot = context.source.get_snapshot(context._target_snapshot_id)
    if context._snapshot is None:
        return _no_selection(context)
    return {"status": "analyze"}


def _analyze(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    del state
    context = runtime.context
    if context._snapshot is None:
        raise RuntimeError("Карточка для анализа не загружена")
    context._analysis = analyze_snapshot(context._snapshot, evaluated_at=context.evaluated_at)
    return {"status": "validate"}


def _validate(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    del state
    context = runtime.context
    if context._snapshot is None or context._analysis is None:
        raise RuntimeError("Анализ для проверки не сформирован")
    validate_analysis(context._analysis, context._snapshot)
    return {"status": "answer_question" if context._qa_requested else "compose"}


async def _answer_question(
    state: WorkflowState, runtime: Runtime[WorkflowContext]
) -> WorkflowState:
    """Передать адаптеру только проверенный снимок и ID предыдущей темы."""

    context = runtime.context
    if wants_review(context):
        return {"status": "compose_comparison" if context._focus_question else "compose"}
    if context._snapshot is None or context._analysis is None:
        raise RuntimeError("Проверенные данные для вопроса отсутствуют")
    if context.settings is None:
        context.result = WorkflowResult(
            "llm_unavailable",
            "AI-помощник не настроен. Карточка доступна; для ответов нужен API-ключ.",
            snapshot=context._snapshot,
            analysis=context._analysis,
        )
        return {"status": "compose_comparison" if context._focus_question else "compose"}
    previous_fact_ids = (
        tuple(state.get("last_fact_ids", [])[:8])
        if (
            state.get("selected_snapshot_id") == context._snapshot.snapshot_id
            or state.get("focused_snapshot_id") == context._snapshot.snapshot_id
        )
        else ()
    )
    context._grounded_answer = await answer_question(
        context.settings,
        context.question,
        context._snapshot,
        context._analysis,
        previous_fact_ids=previous_fact_ids,
        client=context.llm_client,
    )
    return {"status": "validate_answer"}


def _validate_answer(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    """Повторно сверить отобранные моделью факты до публикации и записи памяти."""

    del state
    context = runtime.context
    if context._snapshot is None or context._analysis is None or context._grounded_answer is None:
        raise RuntimeError("Ответ для проверки не сформирован")
    grounded = context._grounded_answer
    try:
        validate_grounded_answer(grounded, context._snapshot, context._analysis)
    except ValueError:
        context._grounded_answer = None
        context.result = WorkflowResult(
            "validation_failed",
            "Ответ модели не прошёл проверку по источникам. "
            "Проверенная карточка остаётся доступна.",
            snapshot=context._snapshot,
            analysis=context._analysis,
            llm_used=grounded.used_llm,
        )
        return {"status": "compose_comparison" if context._focus_question else "compose"}
    context.result = WorkflowResult(
        grounded.status,
        grounded.answer,
        snapshot=context._snapshot,
        analysis=context._analysis,
        answer_claims=grounded.claims,
        mode=(
            "llm"
            if grounded.used_llm and grounded.status in {"answered", "insufficient_data"}
            else "deterministic"
        ),
        model=grounded.model,
        llm_used=grounded.used_llm,
    )
    return {"status": "compose_comparison" if context._focus_question else "compose"}


def _compose(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    context = runtime.context
    if state.get("status") == "compose":
        if context._snapshot is None or context._analysis is None:
            raise RuntimeError("Проверенный анализ отсутствует")
        if context.result is None:
            context.result = WorkflowResult(
                "analyzed",
                "Показана карточка и проверенные выводы по доступному отчёту. "
                "Источники доступны у каждого вывода. Можно задать вопрос по этой компании.",
                snapshot=context._snapshot,
                analysis=context._analysis,
            )
        if context._routing_preserve_single:
            context.result.snapshot = context._snapshot
            context.result.analysis = context._analysis
            return {"status": context.result.status}
        previous_fact_ids = (
            state.get("last_fact_ids", [])[:8]
            if state.get("selected_snapshot_id") == context._snapshot.snapshot_id
            else []
        )
        if context._grounded_answer is not None and context._grounded_answer.status == "answered":
            previous_fact_ids = list(context._grounded_answer.fact_ids[:8])
        return {
            "selected_snapshot_id": context._snapshot.snapshot_id,
            "pending_snapshot_ids": [],
            "selected_snapshot_ids": [],
            "comparison_slots": [],
            "focused_snapshot_id": None,
            "last_comparison_fact_ids": [],
            "comparison_extension_pending": False,
            "last_fact_ids": previous_fact_ids,
            "status": context.result.status,
        }
    if context.result is None:
        raise RuntimeError("Результат workflow отсутствует")
    return {"status": context.result.status}
