"""Регрессии для ограничений ответа о причинах банковской оценки."""

import pytest

from counterparty_agent.ai.topics import needs_attention_explanation


@pytest.mark.parametrize(
    "question",
    [
        "Из-за чего этот контрагент надежен?",
        "Из-за чего этот контрагент надёжен?",
        "Почему этот контрагент надёжен?",
        "Из-за чего у него зелёная оценка?",
        "Почему компания надёжная?",
    ],
)
def test_bank_reason_question_requires_closed_scoring_boundary(question: str) -> None:
    assert needs_attention_explanation(question)


@pytest.mark.parametrize(
    "question",
    [
        "Из-за чего упала выручка?",
        "А каккие есть судебные дела?",
        "Какой цвет светофора?",
        "Этот контрагент надёжен?",
        "Из-за чего?",
    ],
)
def test_unrelated_or_noncausal_question_does_not_trigger_bank_explanation(question: str) -> None:
    assert not needs_attention_explanation(question)
