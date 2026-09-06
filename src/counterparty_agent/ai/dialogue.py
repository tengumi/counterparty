"""Короткая память диалога: контекст продолжения, а не новые факты о компании."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from counterparty_agent.ai.contracts import ApprovedFact, GroundedStatus, ReviewDraft, ReviewTopic

if TYPE_CHECKING:
    from counterparty_agent.ai.deal import DealContext

DialogueOutcome = GroundedStatus | Literal["routing_failed", "needs_clarification"]


class RememberedAction(BaseModel):
    """Ранее показанное действие; основания нужно заново найти в текущем каталоге."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=700, repr=False)
    fact_ids: list[str] = Field(max_length=32)


class RememberedFact(BaseModel):
    """Ранее использованный текст каталога; не пересказ модели и не основание нового ответа."""

    model_config = ConfigDict(extra="forbid")
    fact_id: str = Field(max_length=200)
    topic: ReviewTopic
    metric: str | None = Field(default=None, max_length=80)
    text: str = Field(min_length=1, max_length=600, repr=False)


class DialogueMemory(BaseModel):
    """Хранится с условиями в строке сессии, никогда не в checkpoint или логах."""

    model_config = ConfigDict(extra="forbid")
    outcome: DialogueOutcome
    previous_question: str = Field(max_length=1200, repr=False)
    unresolved_question: str | None = Field(default=None, max_length=1200, repr=False)
    topics: list[ReviewTopic] = Field(default_factory=list, max_length=6)
    recommended_actions: list[RememberedAction] = Field(default_factory=list, max_length=2)
    recent_facts: list[RememberedFact] = Field(default_factory=list, max_length=8)
    snapshot_ids: list[str] = Field(max_length=100)
    source_hash: str
    context_revision: int


def dialogue_context(
    deal: DealContext, snapshot_ids: Sequence[str], source_hash: str
) -> dict[str, Any] | None:
    """Проекция той же проверки и условий; старые советы не становятся evidence."""

    memory = deal.dialogue
    if (
        memory is None
        or not snapshot_ids
        or set(memory.snapshot_ids) != set(snapshot_ids)
        or memory.source_hash != source_hash
        or memory.context_revision != deal.context_revision
    ):
        return None
    question_limit, action_limit = (250, 180) if memory.recent_facts else (600, 500)
    projected: dict[str, Any] = {
        "usage": "untrusted_conversation_context_not_evidence",
        "outcome": memory.outcome,
        "previous_question": _context_text(memory.previous_question, question_limit),
        "unresolved_question": _context_text(memory.unresolved_question, question_limit)
        if memory.unresolved_question
        else None,
        "topics": memory.topics,
        # Источники проверяются по текущему каталогу; старые ID модель не получает.
        "recommended_actions": [
            {"text": _context_text(action.text, action_limit)}
            for action in memory.recommended_actions
            if len(action.text) <= action_limit
        ],
        "questions_truncated": any(
            len(value or "") > question_limit
            for value in (memory.previous_question, memory.unresolved_question)
        ),
    }
    projected["recent_facts"] = []
    if len(json.dumps(projected, ensure_ascii=False)) > 4000:
        projected["recommended_actions"] = []
    # Содержательные сведения имеют приоритет перед служебными границами/датой отчёта.
    ordered = sorted(
        memory.recent_facts,
        key=lambda fact: fact.topic not in {"finance", "enforcement", "arbitration", "documents"},
    )
    for fact in ordered:
        item = fact.model_dump(exclude={"fact_id"})
        projected["recent_facts"].append(item)
        if len(json.dumps(projected, ensure_ascii=False)) > 4000:
            projected["recent_facts"].pop()
        if len(projected["recent_facts"]) == 4:
            break
    return projected


def _context_text(value: str, limit: int) -> str:
    """Не передавать управляющие символы; вопрос остаётся недоверенной сокращённой цитатой."""

    printable = "".join(char if char.isprintable() else " " for char in value)
    return " ".join(printable.split())[:limit]


def _fact_topic(fact: ApprovedFact) -> ReviewTopic:
    """Тема из серверных метаданных каталога, не из свободного запроса пользователя."""

    key = fact.metric or fact.topic
    if "enforcement" in key or key == "debt_total_unavailable":
        return "enforcement"
    if key.startswith("arbitration"):
        return "arbitration"
    if (
        fact.topic == "granular_metric"
        or key.startswith("financial")
        or key
        in {
            "profitability_unknown",
            "capital_status_boundary",
        }
    ):
        return "finance"
    if fact.topic in {"document", "user_document", "document_coverage"}:
        return "documents"
    if "license" in key:
        return "licenses"
    if key in {"provider_negative_signal", "reputation_summary"}:
        return "reputation"
    if key.startswith("report_") or key == "money_units_confirmed":
        return "data_quality"
    return "company"


def _remembered_facts(
    previous: Sequence[RememberedFact],
    draft: ReviewDraft | None,
    catalog: Mapping[str, ApprovedFact] | None,
) -> list[RememberedFact]:
    """Свежие подтверждённые основания плюс прежние темы; максимум восемь без дублей."""

    fresh: list[RememberedFact] = []
    if draft is not None and catalog is not None:
        blocks = sorted(draft.blocks, key=lambda block: block.kind != "fact")
        for key in dict.fromkeys(key for block in blocks for key in block.fact_ids):
            fact = catalog.get(key)
            if (
                fact is None
                or fact.topic == "deal_context"
                or len(fact.claim.text) > 600
                or len(fact.fact_id) > 200
                or len(fact.metric or fact.topic) > 80
            ):
                continue
            fresh.append(
                RememberedFact(
                    fact_id=fact.fact_id,
                    topic=_fact_topic(fact),
                    metric=fact.metric or fact.topic,
                    text=fact.claim.text,
                )
            )
    unique: dict[str, RememberedFact] = {}
    for remembered in [*fresh, *previous]:
        unique.setdefault(remembered.fact_id, remembered)
    candidates = list(unique.values())
    first_by_topic: dict[str, RememberedFact] = {}
    for remembered in candidates:
        first_by_topic.setdefault(remembered.topic, remembered)
    leading = list(first_by_topic.values())
    chosen = {fact.fact_id for fact in leading}
    return [*leading, *(fact for fact in candidates if fact.fact_id not in chosen)][:8]


def remember_dialogue(
    deal: DealContext,
    question: str,
    status: str,
    snapshot_ids: Sequence[str],
    source_hash: str,
    *,
    topics: Sequence[ReviewTopic] = (),
    draft: ReviewDraft | None = None,
    catalog: Mapping[str, ApprovedFact] | None = None,
) -> None:
    """Записать исход, но не скрытый черновик, полный ответ или гипотезу как условие."""

    if status not in {
        "answered",
        "insufficient_data",
        "validation_failed",
        "llm_unavailable",
        "routing_failed",
        "needs_clarification",
    }:
        return
    if not question.strip() or not snapshot_ids:
        return
    previous = dialogue_context(deal, snapshot_ids, source_hash)
    actions: list[RememberedAction] = []
    if status == "answered" and draft is not None and catalog is not None:
        for block in draft.blocks:
            if block.kind != "action" or not all(key in catalog for key in block.fact_ids):
                continue
            # Обрезанное предложение нельзя выдавать за прежнюю рекомендацию целиком.
            if len(block.text) <= 700:
                actions.append(RememberedAction(text=block.text, fact_ids=block.fact_ids))
            if len(actions) == 2:
                break
    elif previous is not None and deal.dialogue is not None:
        actions = [action.model_copy(deep=True) for action in deal.dialogue.recommended_actions]
    recent = _remembered_facts(
        deal.dialogue.recent_facts if previous is not None and deal.dialogue else (),
        draft if status == "answered" else None,
        catalog if status == "answered" else None,
    )
    clipped = question.strip()[:1200]
    deal.dialogue = DialogueMemory(
        outcome=cast(DialogueOutcome, status),
        previous_question=clipped,
        unresolved_question=None if status == "answered" else clipped,
        topics=list(dict.fromkeys(topics or (previous["topics"] if previous else [])))[:6],
        recommended_actions=actions,
        recent_facts=recent,
        snapshot_ids=list(snapshot_ids),
        source_hash=source_hash,
        context_revision=deal.context_revision,
    )


def conversation_reply(previous: dict[str, Any] | None, *, has_selection: bool) -> str:
    """Служебное восстановление не требует выдумывать сведения или заново искать компанию."""

    if not has_selection:
        return (
            "Я могу помочь проверить компанию, сравнить контрагентов и обсудить условия сделки. "
            "Укажите ИНН, ОГРН или название, чтобы начать."
        )
    outcome = previous.get("outcome") if previous else None
    explanation = (
        "Предыдущий ответ не удалось подтвердить по доступным данным, поэтому я его не показал. "
        if outcome == "validation_failed"
        else "При подготовке предыдущего ответа произошла ошибка подключения. "
        if outcome == "llm_unavailable"
        else "Для предыдущего ответа не хватило подтверждённых данных. "
        if outcome == "insufficient_data"
        else "Я не смог правильно разобрать предыдущий вопрос. Это ошибка обработки запроса. "
        if outcome in {"routing_failed", "needs_clarification"}
        else ""
    )
    return (
        "Я могу продолжить помогать с этой проверкой. "
        + explanation
        + "Компанию и уже указанные условия повторять не нужно. "
        "Можем разобрать последний вопрос: что подтверждено, чего мы не знаем "
        "и какие варианты действий можно рассмотреть."
    )
