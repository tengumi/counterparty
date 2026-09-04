"""Выбор фактов моделью, ограниченный repair и безопасный отказ."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from counterparty_agent.analytics.common import AnalysisValidationError
from counterparty_agent.models import (
    AnalysisResult,
    ComparisonResult,
    CounterpartySnapshot,
)

if TYPE_CHECKING:
    from counterparty_agent.config import Settings

from counterparty_agent.ai import transport
from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.comparison_catalog import build_comparison_fact_catalog
from counterparty_agent.ai.contracts import (
    ApprovedFact,
    GroundedAnswer,
    LlmContextLimitError,
    LlmInvalidResponseError,
    _FactSelection,
)
from counterparty_agent.ai.periods import _has_nonannual_period, _select_relative_period
from counterparty_agent.ai.prompts import _GROUP_SELECTOR_PROMPT, _SELECTOR_PROMPT
from counterparty_agent.ai.topics import (
    needs_attention_explanation,
    required_group_topics,
    topic_key,
)
from counterparty_agent.ai.transport import _request_completion, build_messages
from counterparty_agent.ai.validation import _safe_answer


async def answer_question(
    settings: Settings,
    question: str,
    snapshot: CounterpartySnapshot,
    analysis: AnalysisResult,
    previous_fact_ids: Sequence[str] = (),
    *,
    client: Any | None = None,
) -> GroundedAnswer:
    """AI-помощник выбирает факты; пользователю показывается только проверенный текст сервера."""

    if not settings.llm_configured:
        return _safe_answer("llm_unavailable", used_llm=False, model=None)
    try:
        catalog = {item.fact_id: item for item in build_fact_catalog(snapshot, analysis)}
        if _has_nonannual_period(question):
            return _safe_answer("insufficient_data", used_llm=False, model=None)
        previous_facts = [catalog[key] for key in previous_fact_ids[-8:] if key in catalog]
        attention_explanation = needs_attention_explanation(question, previous_facts)
        catalog, resolved_period = _select_relative_period(question, catalog, previous_facts)
        required_topics = {"bank_signal", "attention_signal"} if attention_explanation else set()
        if attention_explanation:
            catalog = {key: item for key, item in catalog.items() if item.topic in required_topics}
        if not catalog or not required_topics <= {item.topic for item in catalog.values()}:
            return _safe_answer("insufficient_data", used_llm=False, model=None)
        context = {
            "approved_facts": [
                {
                    "fact_id": item.fact_id,
                    "topic": item.topic,
                    "period": item.period,
                    "metric": item.metric,
                    "text": item.claim.text,
                    "evidence_ids": item.claim.evidence_ids,
                }
                for item in catalog.values()
            ],
            "previous_fact_ids": [item.fact_id for item in previous_facts],
            "previous_facts": [
                {
                    "fact_id": item.fact_id,
                    "topic": item.topic,
                    "period": item.period,
                    "metric": item.metric,
                    "text": item.claim.text,
                }
                for item in previous_facts
            ],
            "resolved_period": resolved_period,
        }
        if attention_explanation:
            context["answer_mode"] = "attention_explanation"
            context["required_topics"] = sorted(required_topics)
        messages = build_messages(question, context)
        messages[0]["content"] = _SELECTOR_PROMPT
    except (AnalysisValidationError, LlmContextLimitError, ValueError, KeyError, StopIteration):
        return _safe_answer("validation_failed", used_llm=False, model=None)

    return await _invoke_fact_selector(
        settings, messages, catalog, client=client, required_topics=required_topics
    )


async def _invoke_fact_selector(
    settings: Settings,
    messages: list[dict[str, str]],
    catalog: dict[str, ApprovedFact],
    *,
    client: Any | None,
    required_topics: set[str] | None = None,
) -> GroundedAnswer:
    """Общий транспорт выбора: одна попытка исправления и серверный рендер текста."""

    llm_client = client
    used_llm = False
    try:
        if llm_client is None:
            llm_client = transport.create_client(settings)
        for attempt in range(2):
            used_llm = True
            try:
                result = await _request_completion(settings, messages, llm_client, json_mode=True)
                selected = _FactSelection.model_validate_json(result.answer)
                if any(key not in catalog for key in selected.fact_ids):
                    raise LlmInvalidResponseError("Модель выбрала недоступный факт")
                if selected.status == "insufficient_data":
                    return _safe_answer(
                        "insufficient_data", used_llm=True, model=settings.llm_model
                    )
                topics = {topic_key(catalog[key]) for key in selected.fact_ids}
                if required_topics and not required_topics <= topics:
                    raise LlmInvalidResponseError("Ответ не покрывает явно запрошенные показатели")
                fact_ids = selected.fact_ids
                if required_topics and "bank_signal" in required_topics:
                    # Сначала граница банковской оценки, затем независимые сигналы.
                    fact_ids = tuple(
                        sorted(fact_ids, key=lambda key: catalog[key].topic != "bank_signal")
                    )
                claims = tuple(catalog[key].claim for key in fact_ids)
                return GroundedAnswer(
                    "answered",
                    "\n\n".join(claim.text for claim in claims),
                    claims,
                    fact_ids,
                    settings.llm_model,
                    True,
                )
            except (LlmInvalidResponseError, ValidationError):
                if attempt == 0:
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Предыдущий ответ не прошёл проверку. Повтори выбор по текущему "
                                "каталогу: только JSON, допустимый status и не более 8 разных "
                                "существующих fact_id. Не добавляй текст. При отсутствии ответа "
                                'верни {"status":"insufficient_data","fact_ids":[]}.'
                                + (
                                    " Для содержательного ответа обязательны темы: "
                                    + ", ".join(sorted(required_topics))
                                    + "."
                                    if required_topics
                                    else ""
                                )
                            ),
                        }
                    )
        return _safe_answer("validation_failed", used_llm=True, model=settings.llm_model)
    except Exception:
        return _safe_answer(
            "llm_unavailable", used_llm=used_llm, model=settings.llm_model if used_llm else None
        )
    finally:
        if client is None and llm_client is not None:
            try:
                await llm_client.close()
            except Exception:
                pass  # Ошибка освобождения соединения не раскрывает payload и не меняет ответ.


async def answer_comparison_question(
    settings: Settings,
    question: str,
    snapshots: Sequence[CounterpartySnapshot],
    comparison: ComparisonResult,
    previous_fact_ids: Sequence[str] = (),
    *,
    client: Any | None = None,
) -> GroundedAnswer:
    """Ответить по всей группе, не передавая отчёты или расчёты во власть модели."""

    if not settings.llm_configured:
        return _safe_answer("llm_unavailable", used_llm=False, model=None)
    try:
        catalog = {
            item.fact_id: item for item in build_comparison_fact_catalog(snapshots, comparison)
        }
        previous = [catalog[key] for key in previous_fact_ids[-8:] if key in catalog]
        catalog, resolved_period = _select_relative_period(question, catalog, previous)
        # Каталог группы содержит лишь год текущей матрицы; другие относительные даты не угадываем.
        if re.search(
            r"\b(?:позапрошл\w*\s+год\w*|прошлогодн\w*|"
            r"(?:следующ|будущ|текущ)\w*\s+год\w*|год(?:ом)?\s+(?:раньше|назад|ранее))\b",
            question.lower(),
        ):
            catalog = {}
        # Годовые значения нельзя выдавать за квартальные, месячные или многолетние.
        if _has_nonannual_period(question) or re.search(
            r"\bпоследни(?:е|х)\s+(?:\d+|[а-я]+)\s+(?:лет|год(?:а|ов)?)\b",
            question.lower(),
        ):
            catalog = {}
        explicit_years = {int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", question)}
        if explicit_years:
            if len(explicit_years) != 1 or explicit_years != {comparison.financial_year}:
                catalog = {}
            else:
                catalog = {
                    key: item for key, item in catalog.items() if item.period in explicit_years
                }
        if not catalog:
            return _safe_answer("insufficient_data", used_llm=False, model=None)
        context = {
            "company_count": len(comparison.snapshot_ids),
            "comparison_period": comparison.financial_year,
            "resolved_period": resolved_period,
            "previous_fact_ids": [item.fact_id for item in previous],
            "approved_facts": [
                {
                    "fact_id": item.fact_id,
                    "topic": item.topic,
                    "period": item.period,
                    "metric": item.metric,
                    "text": (
                        item.claim.text
                        if len(comparison.snapshot_ids) <= 10
                        else f"Показатель {item.metric or item.topic}. Полные значения всех "
                        f"{len(comparison.snapshot_ids)} компаний подставит сервер."
                    ),
                }
                for item in catalog.values()
            ],
            "previous_facts": [
                {
                    "fact_id": item.fact_id,
                    "topic": item.topic,
                    "period": item.period,
                    "metric": item.metric,
                }
                for item in previous
            ],
        }
        messages = build_messages(question, context)
        messages[0]["content"] = _GROUP_SELECTOR_PROMPT
    except (AnalysisValidationError, LlmContextLimitError, ValueError, KeyError, StopIteration):
        return _safe_answer("validation_failed", used_llm=False, model=None)
    return await _invoke_fact_selector(
        settings,
        messages,
        catalog,
        client=client,
        required_topics=required_group_topics(question),
    )
