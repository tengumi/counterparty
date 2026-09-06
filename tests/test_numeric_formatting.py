"""Сокращённая денежная запись меняет формат, но не величину или единицу источника."""

import pytest

from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim, ReviewBlock, ReviewDraft
from counterparty_agent.ai.reasoning import _number_tokens, validate_draft


def check_amount(source: str, answer: str) -> None:
    fact = ApprovedFact("amount", GroundedClaim(text=source, evidence_ids=("e",)), "financial")
    validate_draft(
        ReviewDraft(blocks=[ReviewBlock(kind="fact", text=answer, fact_ids=["amount"])]),
        {"amount": fact},
    )


@pytest.mark.parametrize(
    ("source", "answer"),
    [
        ("Сумма: 6 750 000 рублей.", "Сумма: 6,75 млн рублей."),
        ("Сумма: 390000 рублей.", "Сумма: 390 тыс. руб."),
        ("Сумма: 390 тысяч рублей.", "Сумма: 390 000 ₽."),
        ("Сумма: 1 250 000 000 рублей.", "Сумма: 1,25 миллиарда рублей."),
        ("Сумма: 6750000.00 руб.", "Сумма: 6,750 миллионов рублей."),
        (
            "Сумма: 1234567890123456789012345678901 рублей.",
            "Сумма: 1234567890123456789012,345678901 млрд ₽.",
        ),
    ],
)
def test_exact_ruble_scale_is_only_a_format(source, answer):
    check_amount(source, answer)


@pytest.mark.parametrize(
    ("source", "answer"),
    [
        ("Активы: 8 046 000 рублей.", "Активы: 8 млн рублей."),
        ("Сумма: 24,63 рубля.", "Сумма: 24 рубля."),
        ("Количество: 2000 дел.", "Сумма: 2 тысячи рублей."),
        ("Доля: 2000%.", "Сумма: 2 тыс. рублей."),
    ],
)
def test_scale_never_authorizes_rounding_or_different_units(source, answer):
    with pytest.raises(ValueError, match="числа"):
        check_amount(source, answer)


def test_scale_keeps_the_sign_and_does_not_round_cents():
    check_amount("Прибыль: -6 750 000 рублей.", "Прибыль: минус 6,75 млн рублей.")
    check_amount("Сумма: 24,63 рубля.", "Сумма: 0,02463 тысячи рублей.")
    with pytest.raises(ValueError, match="числа"):
        check_amount("Прибыль: -6 750 000 рублей.", "Прибыль: 6,75 млн рублей.")


def test_only_explicit_rubles_expand_scale_and_iso_dates_keep_their_signs():
    check_amount("Сумма: 100 рублей.", "Сумма: 100.")
    assert _number_tokens("2 тысячи дел и 2 тыс. процентов") == {"2"}
    assert _number_tokens("2 тыс. руб. %") == {"2"}
    assert _number_tokens("2026-09-06 и минус 24,63") == {"2026", "09", "06", "-24.63"}
