"""Восстановление сессии и маршрутизация запроса."""

from __future__ import annotations

from langgraph.runtime import Runtime

from counterparty_agent.models import (
    EntityKind,
    QueryIntent,
    ResolutionStatus,
)
from counterparty_agent.query import QueryParseError
from counterparty_agent.workflow.contracts import (
    InvalidCandidateSelection,
    WorkflowContext,
    WorkflowResult,
    WorkflowState,
)
from counterparty_agent.workflow.intents import (
    _ADD_COMPARISON,
    _FOCUS_CARD_REQUEST,
    _GROUP_QUESTION,
    _REOPEN_COMPARISON_REQUESTS,
    _REOPEN_REQUESTS,
    _SIMILAR_REQUEST,
    _TOPIC_REQUEST,
    _UNSUPPORTED_ANSWER,
    _has_named_target,
    _has_unsupported_comparison_period,
    _is_question,
    _ordinal_positions,
    _parse_workflow_query,
    _unclear_named_company,
)
from counterparty_agent.workflow.selection import (
    _confirm_comparison_selection,
    _focus_clarification,
    _keep_committed_comparison,
    _no_selection,
    _require_confirmation,
    _restore_comparison,
    _select_single_target,
)


def _restore_session(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    context = runtime.context
    context.result = None
    context._plan = None
    context._target_snapshot_id = None
    context._snapshot = None
    context._analysis = None
    context._qa_requested = False
    context._grounded_answer = None
    context._target_snapshot_ids = []
    context._snapshots = ()
    context._analyses = ()
    context._comparison = None
    context._comparison_question = False
    context._focus_question = False
    context._focus_snapshot_id = state.get("focused_snapshot_id")
    context._base_snapshot_ids = list(state.get("selected_snapshot_ids", []))
    context._comparison_extension = state.get("comparison_extension_pending", False)
    context._staged_comparison_slots = None
    context._pending_response_status = None
    context._pending_response_message = ""
    context._preserve_comparison_state = False
    context._clear_focus_requested = False
    context._intent_plan = None
    context._routing_used_llm = False
    context._routing_model = None
    context._routing_preserve_single = False
    if state.get("source_hash") != context.source.source_hash:
        context._focus_snapshot_id = None
        context._base_snapshot_ids = []
        context._comparison_extension = False
        return {
            "selected_snapshot_id": None,
            "pending_snapshot_ids": [],
            "source_hash": context.source.source_hash,
            "status": "ready",
            "last_fact_ids": [],
            "selected_snapshot_ids": [],
            "comparison_slots": [],
            "focused_snapshot_id": None,
            "last_comparison_fact_ids": [],
            "comparison_extension_pending": False,
        }
    return {"status": "ready"}


def _parse_request(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    context = runtime.context
    pending_ids = state.get("pending_snapshot_ids", [])
    normalized = " ".join(context.question.casefold().replace("ё", "е").split()).strip(" .!?;")

    if context.candidate_selection_id is not None:
        return _confirm_comparison_selection(state, context)
    if context.candidate_snapshot_id is not None:
        if state.get("comparison_slots") and not pending_ids:
            raise InvalidCandidateSelection("Для сравнения нужен идентификатор позиции списка")
        if context.candidate_snapshot_id not in pending_ids:
            raise InvalidCandidateSelection("Кандидат не входит в текущий список выбора")
        return _select_single_target(state, context, context.candidate_snapshot_id)

    # Обновление страницы продолжает незавершённый поиск, а не отменяет его показом группы.
    if context.restore and pending_ids:
        return _require_confirmation(context, pending_ids)

    if context.restore or normalized in _REOPEN_COMPARISON_REQUESTS:
        if state.get("comparison_slots") or state.get("selected_snapshot_ids"):
            if not context.restore:
                context._focus_snapshot_id = None
                context._clear_focus_requested = True
            return _restore_comparison(state, context)
        if normalized in _REOPEN_COMPARISON_REQUESTS:
            context.result = WorkflowResult(
                "no_comparison",
                "В этой сессии пока нет сравнения. Укажите не менее 2 разных компаний.",
            )
            return {"status": "no_comparison"}

    if context.restore or normalized in _REOPEN_REQUESTS:
        if state.get("comparison_slots") or state.get("selected_snapshot_ids"):
            if context._focus_snapshot_id is None:
                return _focus_clarification(context)
            return _restore_comparison(state, context)
        if pending_ids:
            return _require_confirmation(context, pending_ids)
        context._target_snapshot_id = state.get("selected_snapshot_id")
        if context._target_snapshot_id is not None:
            return {"status": "load"}
        return _no_selection(context)

    addition = _ADD_COMPARISON.match(context.question.strip())
    if addition is not None:
        if len(context._base_snapshot_ids) < 2:
            context.result = WorkflowResult(
                "no_comparison", "Сначала создайте сравнение хотя бы двух компаний."
            )
            return {"status": "no_comparison"}
        context._plan = _parse_workflow_query(addition.group("entities"))
        if not context._plan.mentions:
            return _keep_committed_comparison(
                context,
                "comparison_invalid_count",
                "Укажите одного или несколько новых участников.",
            )
        context._comparison_extension = True
        return {"status": "resolve_addition"}

    ordinal_positions = _ordinal_positions(normalized)
    if ordinal_positions:
        explicit_plan = _parse_workflow_query(context.question)
        if any(item.kind is not EntityKind.NAME for item in explicit_plan.mentions):
            ordinal_positions = []
    if ordinal_positions:
        if len(ordinal_positions) != 1 or not context._base_snapshot_ids:
            return _focus_clarification(context)
        position = ordinal_positions[0]
        if not 1 <= position <= len(context._base_snapshot_ids):
            return _focus_clarification(context)
        context._focus_snapshot_id = context._base_snapshot_ids[position - 1]
        context._focus_question = not bool(_FOCUS_CARD_REQUEST.search(normalized))
        return _restore_comparison(state, context)

    try:
        context._plan = _parse_workflow_query(context.question)
    except QueryParseError:
        context.result = WorkflowResult("unsupported", _UNSUPPORTED_ANSWER)
        return {"status": "unsupported"}

    if _SIMILAR_REQUEST.search(normalized):
        context.result = WorkflowResult("unsupported", _UNSUPPORTED_ANSWER)
        return {"status": "unsupported"}

    if _GROUP_QUESTION.search(normalized) and (
        state.get("comparison_slots") or context._base_snapshot_ids
    ):
        if len(context._plan.mentions) <= 1 and not _has_named_target(context._plan):
            context._comparison_question = True
            context._focus_snapshot_id = None
            return _restore_comparison(state, context)

    if context._plan.intent is QueryIntent.COMPARE_EXPLICIT or len(context._plan.mentions) > 1:
        if _has_unsupported_comparison_period(context.question, context._plan):
            context.result = WorkflowResult(
                "comparison_unsupported_period",
                "Выбор года сравнения пока не поддержан. Уберите указание периода: "
                "покажем последний общий год, либо один доступный с пропусками.",
            )
            return {"status": "comparison_unsupported_period"}
        if len(context._plan.mentions) < 2:
            context.result = WorkflowResult(
                "comparison_invalid_count",
                "Для сравнения укажите не менее 2 разных компаний. "
                "Повтор одного и того же реквизита не создаёт ещё одну компанию.",
            )
            return {
                "selected_snapshot_id": None,
                "pending_snapshot_ids": [],
                "last_fact_ids": [],
                "selected_snapshot_ids": [],
                "comparison_slots": [],
                "focused_snapshot_id": None,
                "last_comparison_fact_ids": [],
                "comparison_extension_pending": False,
                "status": "comparison_invalid_count",
            }
        context._base_snapshot_ids = []
        context._focus_snapshot_id = None
        context._comparison_extension = False
        return {
            "selected_snapshot_id": None,
            "pending_snapshot_ids": [],
            "last_fact_ids": [],
            "selected_snapshot_ids": [],
            "comparison_slots": [],
            "focused_snapshot_id": None,
            "last_comparison_fact_ids": [],
            "comparison_extension_pending": False,
            "status": "resolve_comparison",
        }

    context._qa_requested = _is_question(normalized)
    # Голое название, совпадающее с темой отчёта, сначала проверяется exact-поиском.
    if (
        context._qa_requested
        and len(context._plan.mentions) == 1
        and not context._plan.mentions[0].explicit
        and context._plan.mentions[0].normalized_value == normalized
        and _TOPIC_REQUEST.fullmatch(normalized)
        and context.source.find_by_name_exact(normalized).status is not ResolutionStatus.NOT_FOUND
    ):
        context._qa_requested = False
    if context._qa_requested and not _has_named_target(context._plan):
        if pending_ids:
            return _require_confirmation(context, pending_ids)
        if _unclear_named_company(normalized):
            context.result = WorkflowResult(
                "needs_company_identifier",
                "Не удалось однозначно определить компанию в вопросе. "
                "Укажите её ИНН, ОГРН или название в кавычках. "
                "Если вопрос о выбранной карточке, напишите «у этой компании».",
            )
            return {"status": "needs_company_identifier"}
        if state.get("comparison_slots") or state.get("selected_snapshot_ids"):
            context._focus_question = context._focus_snapshot_id is not None
            context._comparison_question = not context._focus_question
            return _restore_comparison(state, context)
        context._target_snapshot_id = state.get("selected_snapshot_id")
        if context._target_snapshot_id is None:
            return _no_selection(context)
        return {"status": "load"}

    if len(context._plan.mentions) != 1:
        context.result = WorkflowResult("unsupported", _UNSUPPORTED_ANSWER)
        return {"status": "unsupported"}
    return {
        "pending_snapshot_ids": [],
        "status": "resolve",
    }
