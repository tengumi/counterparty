"""Подтверждение кандидатов, фокус и атомарное изменение группы."""

from __future__ import annotations

import secrets

from langgraph.runtime import Runtime

from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import (
    CounterpartyCandidate,
    ResolutionStatus,
)
from counterparty_agent.query import resolve_query
from counterparty_agent.workflow.contracts import (
    ComparisonSelection,
    ComparisonSlotState,
    InvalidCandidateSelection,
    WorkflowContext,
    WorkflowResult,
    WorkflowState,
)
from counterparty_agent.workflow.intents import _COMPARISON_SLOT_MESSAGES, _CONFIRM_ANSWER


def _focus_clarification(context: WorkflowContext) -> WorkflowState:
    context.result = WorkflowResult(
        "comparison_focus_required",
        "Укажите одну существующую позицию сравнения, например «карточка №2». "
        "Для вопроса всей группе напишите «по группе».",
    )
    return {"status": "comparison_focus_required"}


def _keep_committed_comparison(
    context: WorkflowContext, status: str, message: str
) -> WorkflowState:
    """Показать прежнюю группу, явно отделяя её от неподтверждённого изменения."""

    context._pending_response_status = status
    context._pending_response_message = message
    context._preserve_comparison_state = True
    context._comparison_question = False
    context._focus_question = False
    context._target_snapshot_ids = list(context._base_snapshot_ids)
    return {"status": "load_comparison"}


def _resolve_entities(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    context = runtime.context
    if context._plan is None:
        raise RuntimeError("План поиска не сформирован")
    resolution = resolve_query(context._plan, context.source).results[0]
    if resolution.status is ResolutionStatus.RESOLVED:
        return _select_single_target(state, context, resolution.candidates[0].snapshot_id)
    if resolution.status in {ResolutionStatus.AMBIGUOUS, ResolutionStatus.NEEDS_CONFIRMATION}:
        context.result = WorkflowResult(
            "needs_confirmation", _CONFIRM_ANSWER, list(resolution.candidates)
        )
        return {
            "pending_snapshot_ids": [item.snapshot_id for item in resolution.candidates],
            "status": "needs_confirmation",
        }
    if resolution.status is ResolutionStatus.INVALID_IDENTIFIER:
        context.result = WorkflowResult(
            "invalid_identifier", "Проверьте длину и контрольную сумму ИНН или ОГРН."
        )
        return {"status": "invalid_identifier"}
    context.result = WorkflowResult(
        "not_found",
        "Компания не найдена в подключённом JSON. Уточните ИНН, ОГРН или название. "
        "Это не означает, что компания не существует или не имеет рисков.",
    )
    return {"status": "not_found"}


def _select_single_target(
    state: WorkflowState, context: WorkflowContext, snapshot_id: str
) -> WorkflowState:
    if snapshot_id in context._base_snapshot_ids:
        context._focus_snapshot_id = snapshot_id
        context._focus_question = context._qa_requested
        context._comparison_question = False
        update = _restore_comparison(state, context)
        update["pending_snapshot_ids"] = []
        return update
    context._target_snapshot_id = snapshot_id
    context._focus_snapshot_id = None
    context._base_snapshot_ids = []
    context._comparison_extension = False
    return {
        "status": "load",
        "selected_snapshot_ids": [],
        "comparison_slots": [],
        "focused_snapshot_id": None,
        "last_comparison_fact_ids": [],
        "comparison_extension_pending": False,
    }


def _resolve_comparison(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    """Разрешить все позиции списка, не пропуская ошибки и неоднозначные названия."""

    del state
    context = runtime.context
    if context._plan is None or len(context._plan.mentions) < 2:
        raise RuntimeError("Список компаний для сравнения не сформирован")
    resolutions = resolve_query(context._plan, context.source).results
    slots: list[ComparisonSlotState] = []
    for position, resolution in enumerate(resolutions, start=1):
        status = resolution.status.value
        snapshot_id = None
        candidate_ids: list[str] = []
        if resolution.status is ResolutionStatus.RESOLVED:
            snapshot_id = resolution.candidates[0].snapshot_id
        elif resolution.status in {ResolutionStatus.AMBIGUOUS, ResolutionStatus.NEEDS_CONFIRMATION}:
            status = "needs_confirmation"
            candidate_ids = [item.snapshot_id for item in resolution.candidates]
        slots.append(
            ComparisonSlotState(
                selection_id=f"selection_{secrets.token_hex(12)}",
                position=position,
                status=status,
                snapshot_id=snapshot_id,
                candidate_snapshot_ids=candidate_ids,
            )
        )
    return _comparison_outcome(context, slots)


def _resolve_addition(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    """Подготовить расширение, сохраняя подтверждённую группу до проверки результата."""

    del state
    context = runtime.context
    if context._plan is None or not context._base_snapshot_ids:
        raise RuntimeError("Контекст добавления не сформирован")
    slots = [
        ComparisonSlotState(
            selection_id=f"selection_{secrets.token_hex(12)}",
            position=index,
            status="resolved",
            snapshot_id=snapshot_id,
            candidate_snapshot_ids=[],
        )
        for index, snapshot_id in enumerate(context._base_snapshot_ids, start=1)
    ]
    for offset, resolution in enumerate(
        resolve_query(context._plan, context.source).results, start=1
    ):
        status = resolution.status.value
        snapshot_id = None
        candidate_ids: list[str] = []
        if resolution.status is ResolutionStatus.RESOLVED:
            snapshot_id = resolution.candidates[0].snapshot_id
        elif resolution.status in {ResolutionStatus.AMBIGUOUS, ResolutionStatus.NEEDS_CONFIRMATION}:
            status = "needs_confirmation"
            candidate_ids = [item.snapshot_id for item in resolution.candidates]
        slots.append(
            ComparisonSlotState(
                selection_id=f"selection_{secrets.token_hex(12)}",
                position=len(context._base_snapshot_ids) + offset,
                status=status,
                snapshot_id=snapshot_id,
                candidate_snapshot_ids=candidate_ids,
            )
        )
    return _comparison_outcome(context, slots)


def _confirm_comparison_selection(state: WorkflowState, context: WorkflowContext) -> WorkflowState:
    """Принять выбор только для текущей ожидающей позиции и её списка кандидатов."""

    slots = _copy_comparison_slots(state.get("comparison_slots", []))
    selected = next(
        (item for item in slots if item["selection_id"] == context.candidate_selection_id), None
    )
    snapshot_id = context.candidate_snapshot_id
    if (
        selected is None
        or selected["status"] != "needs_confirmation"
        or snapshot_id is None
        or snapshot_id not in selected["candidate_snapshot_ids"]
    ):
        raise InvalidCandidateSelection("Выбор не входит в текущий список этой позиции сравнения")
    snapshot = context.source.get_snapshot(snapshot_id)
    if snapshot is None:
        raise InvalidCandidateSelection("Карточка выбранного кандидата больше недоступна")
    for slot in slots:
        if slot["status"] != "resolved" or slot["snapshot_id"] is None:
            continue
        other = context.source.get_snapshot(slot["snapshot_id"])
        if other is not None and other.company_id == snapshot.company_id:
            raise InvalidCandidateSelection("Эта компания уже подтверждена в другой позиции")
    selected["status"] = "resolved"
    selected["snapshot_id"] = snapshot_id
    selected["candidate_snapshot_ids"] = []
    return _comparison_outcome(context, slots)


def _restore_comparison(state: WorkflowState, context: WorkflowContext) -> WorkflowState:
    """Восстановить группу без сохранённых названий, вопросов и результатов расчётов."""

    slots = _copy_comparison_slots(state.get("comparison_slots", []))
    if state.get("comparison_extension_pending") and context._base_snapshot_ids:
        failed = any(item["status"] not in {"resolved", "needs_confirmation"} for item in slots)
        return _keep_committed_comparison(
            context,
            "comparison_addition_incomplete"
            if failed
            else "comparison_addition_needs_confirmation",
            "Добавление ещё не завершено. Ниже прежняя подтверждённая группа; "
            "уточните новые позиции перед вопросами об обновлённом сравнении.",
        )
    if slots:
        return _comparison_outcome(context, slots)
    context._target_snapshot_ids = list(state.get("selected_snapshot_ids", []))
    if len(context._target_snapshot_ids) >= 2:
        return {"status": "load_comparison"}
    context.result = WorkflowResult(
        "no_comparison", "В этой сессии пока нет сравнения. Укажите не менее 2 разных компаний."
    )
    return {"selected_snapshot_ids": [], "comparison_slots": [], "status": "no_comparison"}


def _copy_comparison_slots(slots: list[ComparisonSlotState]) -> list[ComparisonSlotState]:
    return [
        ComparisonSlotState(
            selection_id=item["selection_id"],
            position=item["position"],
            status=item["status"],
            snapshot_id=item["snapshot_id"],
            candidate_snapshot_ids=list(item["candidate_snapshot_ids"]),
        )
        for item in slots
    ]


def _comparison_outcome(
    context: WorkflowContext, slots: list[ComparisonSlotState]
) -> WorkflowState:
    """Сравнивать только полностью подтверждённый список разных компаний."""

    seen_companies: set[str] = set()
    for slot in slots:
        snapshot_id = slot["snapshot_id"]
        if slot["status"] != "resolved" or snapshot_id is None:
            continue
        snapshot = context.source.get_snapshot(snapshot_id)
        if snapshot is None:
            slot["status"] = "not_found"
            slot["snapshot_id"] = None
        elif snapshot.company_id in seen_companies:
            slot["status"] = "duplicate"
        else:
            seen_companies.add(snapshot.company_id)
    if len(slots) >= 2 and all(item["status"] == "resolved" for item in slots):
        context._target_snapshot_ids = [
            item["snapshot_id"] for item in slots if item["snapshot_id"] is not None
        ]
        if context._comparison_extension:
            # Не записывать готовый staging до валидации: после 409 остаётся прежний выбор.
            context._staged_comparison_slots = slots
            return {"status": "load_comparison"}
        return {"comparison_slots": slots, "status": "load_comparison"}
    has_failures = any(item["status"] not in {"resolved", "needs_confirmation"} for item in slots)
    status = "comparison_incomplete" if has_failures else "comparison_needs_confirmation"
    answer = (
        "Сравнение пока не построено: нужно подтвердить или исправить все позиции списка. "
        "Компании с ошибками не исключаются автоматически. "
        "Для исправления реквизитов или повторов отправьте весь список заново."
    )
    if context._comparison_extension and context._base_snapshot_ids:
        update = _keep_committed_comparison(
            context,
            "comparison_addition_incomplete"
            if has_failures
            else "comparison_addition_needs_confirmation",
            "Добавление ещё не завершено. Показана прежняя подтверждённая группа. "
            "Подтвердите новых кандидатов или повторите команду добавления "
            "с исправленными данными.",
        )
        update["comparison_slots"] = slots
        update["comparison_extension_pending"] = True
        return update
    context.result = WorkflowResult(
        status, answer, comparison_selections=_comparison_selection_views(slots, context.source)
    )
    return {"comparison_slots": slots, "selected_snapshot_ids": [], "status": status}


def _comparison_selection_views(
    slots: list[ComparisonSlotState], source: JsonCounterpartySource
) -> list[ComparisonSelection]:
    result = []
    for slot in slots:
        snapshot_id = slot["snapshot_id"]
        ids = [snapshot_id] if snapshot_id is not None else slot["candidate_snapshot_ids"]
        result.append(
            ComparisonSelection(
                selection_id=slot["selection_id"],
                position=slot["position"],
                status=slot["status"],
                snapshot_id=snapshot_id,
                candidates=_restore_candidates(ids, source),
                message=_COMPARISON_SLOT_MESSAGES.get(
                    slot["status"], "Уточните эту позицию в новом полном списке компаний."
                ),
            )
        )
    return result


def _no_selection(context: WorkflowContext) -> WorkflowState:
    context.result = WorkflowResult(
        "no_selection", "В этой сессии компания ещё не выбрана. Введите ИНН, ОГРН или название."
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
        "status": "no_selection",
    }


def _require_confirmation(context: WorkflowContext, pending_ids: list[str]) -> WorkflowState:
    candidates = _restore_candidates(pending_ids, context.source)
    if len(candidates) != len(pending_ids):
        return _no_selection(context)
    context.result = WorkflowResult("needs_confirmation", _CONFIRM_ANSWER, candidates)
    return {"status": "needs_confirmation"}


def _restore_candidates(
    snapshot_ids: list[str], source: JsonCounterpartySource
) -> list[CounterpartyCandidate]:
    """Восстановить реквизиты без выдуманного fuzzy-score или повторного поиска."""

    candidates = []
    for rank, snapshot_id in enumerate(snapshot_ids, start=1):
        snapshot = source.get_snapshot(snapshot_id)
        if snapshot is None:
            continue
        candidates.append(
            CounterpartyCandidate(
                company_id=snapshot.company_id,
                snapshot_id=snapshot.snapshot_id,
                inn=snapshot.identity.inn,
                ogrn=snapshot.identity.ogrn,
                full_name=snapshot.identity.full_name,
                short_name=snapshot.identity.short_name,
                party_type=snapshot.identity.party_type,
                raw_status=snapshot.status.raw_status,
                rank=rank,
            )
        )
    return candidates
