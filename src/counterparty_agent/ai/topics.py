"""Узкие тематические ограничения для явно названных показателей группы."""

import re
from collections.abc import Sequence

from counterparty_agent.ai.contracts import ApprovedFact


def topic_key(fact: ApprovedFact) -> str:
    if fact.topic == "comparison_financial" or fact.metric == "reason_unavailable":
        return f"{fact.topic}:{fact.metric}"
    return fact.topic


def needs_bank_reason(question: str, previous_facts: Sequence[ApprovedFact] = ()) -> bool:
    """Причину оценки сообщать только при прямом вопросе или адресном продолжении."""

    text = question.casefold().replace("ё", "е")
    causal = re.search(
        r"\b(?:почему|отчего|из[\s-]+за\s+чего|причин\w*|объясни\w*|поясни\w*)\b", text
    )
    bank = re.search(
        r"\b(?:светофор\w*|цвет\w*|оценк\w*|желт\w*|красн\w*|зелен\w*|сер\w*|"
        r"надеж(?:н\w*|ен)|yellow|red|green|grey)\b|\bтребует\s+внимани\w*\b",
        text,
    )
    if causal and bank:
        return True
    short_followup = re.fullmatch(
        r"(?:а\s+)?(?:почему|отчего|поясни(?:\s+подробнее)?|объясни)[?!.\s]*", text
    )
    return bool(short_followup) and any(
        item.topic in {"bank_signal", "comparison_bank_signal"} for item in previous_facts
    )


def needs_bank_assessment(question: str) -> bool:
    """Достаточность оценки для решения — не вопрос о причине её цвета."""

    text = question.casefold().replace("ё", "е")
    bank = re.search(
        r"\b(?:зелен\w*|желт\w*|красн\w*|светофор\w*|статус\w*|оценк\w*|green|yellow|red)\b", text
    )
    decision = re.search(
        r"достаточ\w*|гарант\w*|можно\s+(?:довер\w*|работать|платить|перечисл\w*)|"
        r"зачем\s+(?:еще|провер\w*)|разве\s+не\s+надеж\w*",
        text,
    )
    return bool(bank and decision)


def required_group_topics(question: str) -> set[str]:
    text = question.casefold()
    required: set[str] = set()
    if re.search(r"\bубыт\w*", text):
        required.add("comparison_loss")
    elif re.search(r"\bприбыл\w*", text):
        required.add("comparison_financial:profit")
    if re.search(r"\bвыруч\w*", text):
        required.add("comparison_financial:proceeds")
    if re.search(r"\bсветофор\w*", text):
        required.add("comparison_bank_signal")
    return required


def needs_attention_explanation(question: str, previous_facts: Sequence[ApprovedFact] = ()) -> bool:
    """Отделить просьбу разобрать сигналы от обычного чтения цвета или показателя."""

    text = question.casefold().replace("ё", "е")
    if re.search(r"\b(?:внимани\w*|насторажива\w*)\b|\bчто\s+не\s+так\b", text):
        return True
    causal = re.search(
        r"\b(?:почему|отчего|из[\s-]+за\s+чего|причин\w*|объясни\w*|поясни\w*)\b", text
    )
    bank = re.search(
        r"\b(?:светофор\w*|цвет\w*|оценк\w*|желт\w*|красн\w*|зелен\w*|сер\w*|"
        r"риск\w*|надеж(?:н\w*|ен)|yellow|red|green|grey)\b",
        text,
    )
    if causal and bank:
        return True
    # Короткое уточнение наследует только подтверждённую тему той же компании.
    short_followup = re.fullmatch(
        r"(?:а\s+)?(?:почему|отчего|подробнее|поясни(?:\s+подробнее)?|объясни)[?!.\s]*", text
    )
    return bool(short_followup) and any(item.topic == "bank_signal" for item in previous_facts)
