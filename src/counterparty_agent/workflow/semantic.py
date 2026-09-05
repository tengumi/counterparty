"""Семантический вход графа и исполнение ограниченного плана без доверия к модели."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from langgraph.runtime import Runtime

from counterparty_agent.ai.deal import DealPatch
from counterparty_agent.ai.router import IntentPlan, route_intent
from counterparty_agent.models import EntityKind, EntityMention, QueryIntent, QueryPlan
from counterparty_agent.query import QueryParseError, parse_query
from counterparty_agent.workflow.contracts import WorkflowContext, WorkflowResult, WorkflowState
from counterparty_agent.workflow.intents import (
    _ADD_COMPARISON,
    _LEGAL_FORM_IN_QUESTION,
    _REOPEN_COMPARISON_REQUESTS,
    _REOPEN_REQUESTS,
    _UNSUPPORTED_ANSWER,
    _has_named_target,
    _has_unsupported_comparison_period,
    _is_question,
    _ordinal_positions,
    _parse_workflow_query,
)
from counterparty_agent.workflow.review_session import is_short_relative_question, previous_topics
from counterparty_agent.workflow.selection import (
    _focus_clarification,
    _keep_committed_comparison,
    _no_selection,
    _require_confirmation,
    _restore_comparison,
)

_IDENTIFIER_ONLY = re.compile(r"(?:(?:ИНН|ОГРН)\s*[:№]?\s*)?\d{1,20}", re.IGNORECASE)
_LIST_IDENTIFIER = r"(?:(?:ИНН|ОГРН)\s*[:№]?\s*\d{1,20}|\d{10}|\d{12}|\d{13}|\d{15})"
_IDENTIFIER_LIST = re.compile(
    rf"(?:(?:сравни|сравните|сравнить|сопоставь)\s+)?{_LIST_IDENTIFIER}"
    rf"(?:\s*(?:[;,\n]|\bи\b|\bс\b)\s*{_LIST_IDENTIFIER})+",
    re.IGNORECASE,
)
_ROUTING_UNAVAILABLE = (
    "Не удалось разобрать запрос: AI-помощник сейчас недоступен. "
    "Выбранные компании сохранены. Повторите вопрос позже или введите точный ИНН/ОГРН."
)
_ROUTING_FAILED = (
    "Не удалось однозначно понять запрос. Уточните компанию и действие: "
    "найти, сравнить или задать вопрос по выбранному отчёту. Выбор компаний не изменён."
)


def _normalized(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split()).strip(" .!?;")


def _is_control(context: WorkflowContext) -> bool:
    """Идентификаторы и явные команды интерфейса не требуют семантического решения."""

    return (
        context.restore
        or context.candidate_snapshot_id is not None
        or context.candidate_selection_id is not None
        or _normalized(context.question) in _REOPEN_REQUESTS | _REOPEN_COMPARISON_REQUESTS
        or _IDENTIFIER_ONLY.fullmatch(context.question.strip()) is not None
        or _IDENTIFIER_LIST.fullmatch(context.question.strip()) is not None
        or re.fullmatch(
            r"(?:покажи\s+)?карточк[ау]\s*№\s*\d{1,6}",
            context.question.strip(),
            re.IGNORECASE,
        )
        is not None
    )


def _offline_supported(question: str) -> bool:
    """Без подключения оставляем старые явные команды, но не ищем компанию по целой фразе."""

    normalized = _normalized(question)
    plan = _parse_workflow_query(question)
    if _is_question(normalized) or _ordinal_positions(normalized):
        return True
    if plan.mentions and all(
        item.explicit or item.kind is not EntityKind.NAME for item in plan.mentions
    ):
        return True
    if plan.intent is QueryIntent.COMPARE_EXPLICIT or _ADD_COMPARISON.match(question.strip()):
        return True
    if re.fullmatch(r"[А-ЯЁA-Zа-яёa-z][А-ЯЁA-Zа-яёa-z\d.-]{0,119}", question.strip()):
        return True
    # Голое короткое название остаётся доступно в ручном режиме, предложения — нет.
    return bool(
        re.fullmatch(r"[А-ЯЁA-Z\d][А-ЯЁA-Zа-яёa-z\d«»\"' .-]{0,120}", question.strip())
    ) and (
        len(question.split()) <= 4
        and not re.search(r"\b(?:из-за|этот|этого|этой|контрагент|пожалуйста)\b", normalized)
    )


def _session_summary(state: WorkflowState, context: WorkflowContext) -> dict[str, Any]:
    """Только идентичности текущего выбора: никаких отчётов, PII контактов и чужих сессий."""

    def identity(snapshot_id: str | None) -> dict[str, str | None] | None:
        snapshot = context.source.get_snapshot(snapshot_id) if snapshot_id else None
        if snapshot is None:
            return None
        return {
            "name": snapshot.identity.short_name[:120],
            "inn": snapshot.identity.inn,
            "ogrn": snapshot.identity.ogrn,
        }

    ids = context._base_snapshot_ids
    return {
        "selected_company": identity(state.get("selected_snapshot_id")),
        "companies": [
            {"position": index, **item}
            for index, snapshot_id in enumerate(ids, 1)
            if (item := identity(snapshot_id)) is not None
        ],
        "focused_position": (
            ids.index(context._focus_snapshot_id) + 1 if context._focus_snapshot_id in ids else None
        ),
        "has_pending_selection": bool(
            state.get("pending_snapshot_ids")
            or any(item["status"] != "resolved" for item in state.get("comparison_slots", []))
        ),
        "last_topics": previous_topics(state, context),
        "review_context": context.deal.model_dump(mode="json") if context.deal else None,
    }


async def _route_intent(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    context = runtime.context
    if _is_control(context):
        return {"status": "parse_request"}
    if context.deal is not None and _normalized(context.question) == "общая проверка":
        context._intent_plan = IntentPlan(
            action="ask",
            scope="group"
            if context._base_snapshot_ids and not context._focus_snapshot_id
            else "current",
            answer_mode="analysis",
            deal_patch=DealPatch(general_check=True),
        )
        return {"status": "apply_intent"}
    if context.settings is None or not context.settings.llm_configured:
        try:
            if _offline_supported(context.question):
                return {"status": "parse_request"}
        except QueryParseError:
            pass
        return _routing_error(context, "llm_unavailable", _ROUTING_UNAVAILABLE)
    result = await route_intent(
        context.settings,
        context.question,
        _session_summary(state, context),
        client=context.llm_client,
    )
    context._routing_used_llm = result.used_llm
    context._routing_model = result.model
    if result.plan is None:
        return _routing_error(
            context,
            result.status,
            _ROUTING_UNAVAILABLE if result.status == "llm_unavailable" else _ROUTING_FAILED,
        )
    context._intent_plan = result.plan
    if (
        result.plan.action == "ask"
        and is_short_relative_question(context.question)
        and not any(result.plan.deal_patch.model_dump(exclude_none=True).values())
    ):
        context._intent_plan = result.plan.model_copy(update={"answer_mode": "facts"})
    return {"status": "apply_intent"}


def _routing_error(context: WorkflowContext, status: str, message: str) -> WorkflowState:
    context.result = WorkflowResult(status, message)
    return {"status": status}


def _target_plan(intent: IntentPlan, question: str) -> QueryPlan:
    """Модель даёт фрагменты, а тип реквизита и контрольную сумму определяет код."""

    mentions: list[EntityMention] = []
    original_text = unicodedata.normalize("NFKC", question)
    occupied: list[tuple[int, int]] = []
    for text in intent.targets:
        pattern = r"\s+".join(
            re.escape(word.casefold()).replace("ё", "е").replace("е", "[её]")
            for word in unicodedata.normalize("NFKC", text).split()
        )
        if text.strip()[0].isalnum():
            pattern = r"(?<!\w)" + pattern
        if text.strip()[-1].isalnum():
            pattern += r"(?!\w)"
        match = next(
            (
                item
                for item in re.finditer(pattern, original_text, re.IGNORECASE)
                if not any(start < item.end() and item.start() < end for start, end in occupied)
            ),
            None,
        )
        if match is None:
            raise QueryParseError("Упоминание не найдено в исходном вопросе")
        occupied.append(match.span())
        parsed = parse_query(match.group(), preserve_duplicates=True)
        if len(parsed.mentions) != 1:
            raise QueryParseError("Один фрагмент должен обозначать одну компанию")
        mention = parsed.mentions[0]
        mentions.append(
            mention.model_copy(
                update={
                    "mention_id": f"mention_{len(mentions) + 1}",
                    "explicit": True,
                    "span_start": match.start() + mention.span_start,
                    "span_end": match.start() + mention.span_end,
                }
            )
        )
    plan = QueryPlan(
        raw_query=question,
        intent=QueryIntent.COMPARE_EXPLICIT if intent.action == "compare" else QueryIntent.LOOKUP,
        mentions=tuple(mentions),
    )
    # Явно введённый реквизит нельзя отбросить, исправить моделью или заменить текущей карточкой.
    original = _parse_workflow_query(question)
    required = Counter(
        (item.kind, item.normalized_value)
        for item in original.mentions
        if item.kind is not EntityKind.NAME
    )
    actual = Counter(
        (item.kind, item.normalized_value) for item in mentions if item.kind is not EntityKind.NAME
    )
    if required != actual:
        raise QueryParseError("Модель изменила набор реквизитов")
    if not mentions and _LEGAL_FORM_IN_QUESTION.search(_normalized(question)):
        raise QueryParseError("Модель пропустила компанию с явно указанной формой организации")
    # Свободную фразу уже разобрала модель. Старый эвристический фильтр «по/у ...»
    # принимает «по этим поставщикам» или «у второго» за неизвестное название.
    # Здесь сохраняем проверку явных реквизитов, кавычек и организационных форм ниже;
    # ограниченный эвристический режим остаётся только для работы без модели.
    explicit_names = [
        item
        for item in original.mentions
        if item.kind is EntityKind.NAME
        and item.explicit
        and _has_named_target(original.model_copy(update={"mentions": (item,)}))
    ]
    for name in explicit_names:
        if not any(name.normalized_value == item.normalized_value for item in mentions):
            # Старый парсер может включить вводную фразу/год в NAME. Это не ещё одно имя:
            # принимаем дословный адресат внутри такого span, но не обрезаем явное ООО/кавычки.
            span_text = original_text[name.span_start : name.span_end]
            is_prose_span = not _LEGAL_FORM_IN_QUESTION.match(name.normalized_value) and not any(
                char in span_text for char in ('"', "«", "»", "„", "“")
            )
            if is_prose_span and any(
                name.span_start <= item.span_start and item.span_end <= name.span_end
                for item in mentions
            ):
                continue
            raise QueryParseError("Модель пропустила явно названную компанию")
    return plan


def _apply_intent(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    context = runtime.context
    intent = context._intent_plan
    if intent is None:
        raise RuntimeError("Семантический план отсутствует")
    if intent.action in {"clarify", "unsupported"}:
        return _routing_error(
            context,
            "needs_clarification" if intent.action == "clarify" else "unsupported",
            _ROUTING_FAILED if intent.action == "clarify" else _UNSUPPORTED_ANSWER,
        )
    try:
        context._plan = _target_plan(intent, context.question)
    except (QueryParseError, ValueError):
        return _routing_error(context, "routing_failed", _ROUTING_FAILED)
    context._qa_requested = intent.action == "ask"
    if intent.action in {"compare", "add_to_comparison"}:
        return _apply_group_change(state, context, intent)
    if intent.targets:
        return {"pending_snapshot_ids": [], "status": "resolve"}
    if state.get("pending_snapshot_ids"):
        return _require_confirmation(context, state["pending_snapshot_ids"])
    ids = context._base_snapshot_ids
    positions = _ordinal_positions(_normalized(context.question))
    if positions and (len(positions) != 1 or intent.position != positions[0]):
        return _focus_clarification(context)
    if intent.position is not None:
        if not 1 <= intent.position <= len(ids):
            return _focus_clarification(context)
        context._focus_snapshot_id = ids[intent.position - 1]
    elif intent.scope == "group":
        context._focus_snapshot_id = None
        context._clear_focus_requested = True
    if ids or state.get("comparison_slots") or intent.scope == "group":
        context._focus_question = context._qa_requested and context._focus_snapshot_id is not None
        context._comparison_question = context._qa_requested and not context._focus_question
        return _restore_comparison(state, context)
    context._target_snapshot_id = state.get("selected_snapshot_id")
    return {"status": "load"} if context._target_snapshot_id else _no_selection(context)


def _apply_group_change(
    state: WorkflowState, context: WorkflowContext, intent: IntentPlan
) -> WorkflowState:
    plan = context._plan
    if plan is None:
        raise RuntimeError("Список компаний не сформирован")
    if _has_unsupported_comparison_period(unicodedata.normalize("NFKC", context.question), plan):
        return _routing_error(
            context,
            "comparison_unsupported_period",
            "Выбор года сравнения пока не поддержан. Уберите указание периода: "
            "покажем последний общий год, либо один доступный с пропусками.",
        )
    if intent.action == "add_to_comparison":
        if len(context._base_snapshot_ids) < 2:
            return _routing_error(
                context, "no_comparison", "Сначала создайте сравнение хотя бы двух компаний."
            )
        context._comparison_extension = True
        return {"status": "resolve_addition"}
    if intent.include_current:
        if state.get("pending_snapshot_ids") or state.get("comparison_extension_pending"):
            return _routing_error(
                context, "needs_clarification", "Сначала завершите выбор компаний для сравнения."
            )
        current_id = context._focus_snapshot_id or state.get("selected_snapshot_id")
        if current_id is None:
            return (
                _focus_clarification(context)
                if context._base_snapshot_ids
                else _no_selection(context)
            )
        ids = [current_id]
        prefixes: list[EntityMention] = []
        for snapshot_id in ids:
            snapshot = context.source.get_snapshot(snapshot_id) if snapshot_id else None
            if snapshot is None:
                return _no_selection(context)
            prefixes.extend(parse_query(f"ИНН {snapshot.identity.inn}").mentions)
        context._plan = plan.model_copy(
            update={
                "mentions": tuple(
                    item.model_copy(update={"mention_id": f"mention_{index}"})
                    for index, item in enumerate([*prefixes, *plan.mentions], 1)
                )
            }
        )
    context._base_snapshot_ids = []
    context._focus_snapshot_id = None
    context._comparison_extension = False
    return {
        "status": "resolve_comparison",
        "selected_snapshot_id": None,
        "selected_snapshot_ids": [],
        "pending_snapshot_ids": [],
        "comparison_slots": [],
        "focused_snapshot_id": None,
        "last_fact_ids": [],
        "last_comparison_fact_ids": [],
        "comparison_extension_pending": False,
    }


def _finish_routing(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    """Метаданные вызова включают и понимание запроса, даже если карточка собрана кодом."""

    context = runtime.context
    if context.result is not None and context._routing_used_llm:
        context.result.llm_used = True
        context.result.model = context.result.model or context._routing_model
    return {"status": state["status"]}


def _retain_context(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    """Переоткрыть проверенный выбор при отказе роутера, не меняя память и pending."""

    context = runtime.context
    if context.result is None:
        raise RuntimeError("Причина отказа не сформирована")
    if state.get("pending_snapshot_ids"):
        return {"status": context.result.status}
    if context._base_snapshot_ids:
        return _keep_committed_comparison(context, context.result.status, context.result.answer)
    selected = state.get("selected_snapshot_id")
    if selected is not None:
        context._target_snapshot_id = selected
        context._qa_requested = False
        context._routing_preserve_single = True
        return {"status": "load"}
    return {"status": context.result.status}
