"""Узкие тематические ограничения для явно названных показателей группы."""

import re
from collections.abc import Sequence

from counterparty_agent.ai.contracts import ApprovedFact


def topic_key(fact: ApprovedFact) -> str:
    return f"{fact.topic}:{fact.metric}" if fact.topic == "comparison_financial" else fact.topic


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
