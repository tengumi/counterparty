"""Одно необязательное уточнение после анализа, с тем же лимитом и памятью проверки."""

from __future__ import annotations

from counterparty_agent.ai.contracts import ReviewBlock, ReviewDraft
from counterparty_agent.ai.deal import FIELDS, DealContext, DealField, counterparty_role

QUESTIONS: dict[DealField, str] = {
    "goal": "Для чего проверяете контрагента? Можно начать с общей проверки.",
    "role": "Кем будет контрагент в сделке: поставщиком, покупателем или другой стороной?",
    "subject": "Что планируется по сделке: какие товары, работы или услуги?",
    "amount": "Какова сумма сделки?",
    "advance": "Какие условия оплаты планируются: аванс, оплата после исполнения или поэтапно?",
    "deadline": "Какой срок исполнения планируется?",
}


def allowed_follow_ups(deal: DealContext) -> list[DealField]:
    if deal.general_check or len(deal.asked_fields) >= 2:
        return []
    return [
        key
        for key in FIELDS
        if not getattr(deal, key)
        and key not in deal.asked_fields
        and not (key == "role" and counterparty_role(deal) != "unknown")
        and not (key == "goal" and (deal.role or deal.advance))
    ]


def suggested_follow_up(deal: DealContext) -> DealField | None:
    """Для резервной сводки: одно условие, которое помогает продолжить проверку сделки."""

    allowed = allowed_follow_ups(deal)
    role = counterparty_role(deal)
    order: tuple[DealField, ...] = (
        ("subject", "role", "amount", "advance", "deadline")
        if role == "unknown"
        else ("amount", "advance", "subject", "deadline")
        if role == "buyer"
        else ("subject", "amount", "advance", "deadline")
    )
    # Если сторона уже понятна из цели, не переспрашиваем отдельное пустое поле role.
    return next((key for key in order if key in allowed), None)


def prepare_follow_up(draft: ReviewDraft, deal: DealContext) -> ReviewDraft:
    """Добавить нейтральный вопрос до проверки всего ответа; повторный вызов ничего не меняет."""

    field = draft.follow_up_field
    if field is None:
        return draft
    if field not in allowed_follow_ups(deal):
        raise ValueError("Нельзя повторять известное уточнение или превышать лимит вопросов")
    question = QUESTIONS[field]
    if draft.blocks[-1].text.endswith(question):
        return draft
    blocks = list(draft.blocks)
    if (blocks[-1].kind != "action" and len(blocks) == 8) or (
        blocks[-1].kind == "action" and len(blocks[-1].text) + len(question) + 2 > 1100
    ):
        # Необязательный вопрос не вытесняет основания большой группы и не ломает ответ.
        return draft.model_copy(update={"follow_up_field": None})
    if blocks[-1].kind == "action":
        blocks[-1] = ReviewBlock(
            kind="action", text=f"{blocks[-1].text}\n\n{question}", fact_ids=blocks[-1].fact_ids
        )
    else:
        blocks.append(ReviewBlock(kind="action", text=question, fact_ids=blocks[-1].fact_ids))
    # Повторно проверяем длины и число блоков: model_copy не валидирует изменения.
    return ReviewDraft(blocks=blocks, follow_up_field=field)
