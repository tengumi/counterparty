"""Границы узкого ответа: контекст разговора не заменяет основания отчёта."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from counterparty_agent.ai.briefing import safe_analysis_fallback
from counterparty_agent.ai.contracts import ApprovedFact, ReviewBlock, ReviewDraft
from counterparty_agent.ai.deal import DealContext
from counterparty_agent.ai.topics import needs_bank_assessment, needs_bank_reason

ResponseFocus = Literal["overview", "specific", "scenario"]


def supported_subset(
    draft: ReviewDraft, validate: Callable[[ReviewDraft], None]
) -> ReviewDraft | None:
    """Убрать локально ошибочный абзац без подстановки отчёта вместо ответа.

    Возвращается только кандидат: оставшийся текст ещё должен пройти проверку
    целиком на источники, смысловые зависимости и ответ именно на текущий вопрос.
    """
    kept = []
    for block in draft.blocks:
        try:
            validate(ReviewDraft(blocks=[block]))
        except ValueError:
            continue
        kept.append(block)
    if not kept or len(kept) == len(draft.blocks):
        return None
    return ReviewDraft(blocks=kept)


def focused_fallback(
    question: str,
    deal: DealContext,
    catalog: Mapping[str, ApprovedFact],
    focus: ResponseFocus,
    topics: Sequence[str],
) -> ReviewDraft | None:
    """Эталон прежнего тематического ответа для регрессий, не резерв онлайн-синтеза.

    Разделы выбирает проверенный план, а не совпадение с одной заученной фразой.
    Условные ситуации остаются задачей синтеза: готовая карточка не отвечает «что если».
    Любой запасной ответ всё равно проходит смысловую проверку вместе с вопросом.
    """
    if focus == "overview":
        return safe_analysis_fallback(question, deal, catalog)
    if focus == "scenario":
        return None
    if needs_bank_assessment(question) or needs_bank_reason(question):
        return safe_analysis_fallback(question, deal, catalog)
    relevant = set(topics) - {"data_quality", "company"}
    if relevant == {"enforcement"}:
        fact_topic = "enforcement_summary"
        boundary = (
            "Одна сумма взыскания не позволяет решить, стоит ли работать с компанией. "
            "Если производство есть, нужно уточнить его основание и текущий статус. "
            "Сумма записи сама по себе не подтверждает вероятность неисполнения сделки."
        )
        action = (
            "Если запись активна, запросите пояснение и подтверждение её текущего состояния. "
            "Не приравнивайте указанную сумму к полному долгу компании."
        )
    elif relevant == {"arbitration"}:
        fact_topic = "arbitration_summary"
        boundary = (
            "Одного наличия судебных дел недостаточно для решения об отказе от компании. "
            "Если дела есть, для оценки нужны предмет споров, роль компании "
            "и результаты дел. Сумма требований не равна подтверждённому долгу."
        )
        action = (
            "Если дела есть, уточните их предмет и результаты, отдельно — исполнение решений. "
            "Не переносите сведения о завершённых делах на текущие споры."
        )
    else:
        return None
    facts = [
        (key, fact)
        for key, fact in catalog.items()
        if fact.topic == fact_topic or fact.metric == fact_topic
    ]
    if not 1 <= len(facts) <= 4:
        return None
    ids = [key for key, _ in facts]
    return ReviewDraft(
        blocks=[
            ReviewBlock(kind="interpretation", text=boundary, fact_ids=ids),
            *[
                ReviewBlock(kind="fact", text=fact.claim.text, fact_ids=[key])
                for key, fact in facts
            ],
            ReviewBlock(kind="action", text=action, fact_ids=ids),
        ]
    )
