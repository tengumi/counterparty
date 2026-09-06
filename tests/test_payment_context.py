"""Точные условия оплаты, направление сделки и происхождение краткого пояснения."""

import pytest

from counterparty_agent.ai.deal import (
    DealContext,
    DealPatch,
    apply_deal,
    deal_facts,
    deal_implication_facts,
    literal_deal_patch,
    validate_deal,
)


@pytest.mark.parametrize(
    "payment",
    ["40% предоплаты", "предоплата 40%", "аванс: 40%", "40,5% аванса", "аванс 40.5%"],
)
def test_literal_payment_keeps_percentage_on_either_side(payment: str) -> None:
    question = f"Проверь поставщика по ИНН 9714038662. Они хотят {payment}."
    patch = literal_deal_patch(question)
    deal = apply_deal(DealContext(), patch, question)
    assert deal.advance == payment
    validate_deal(deal)
    effect = deal_implication_facts(deal)[0]
    assert f"«{payment}»" in effect.claim.text
    assert deal.terms["advance"].evidence_id in effect.claim.evidence_ids


@pytest.mark.parametrize(
    ("payment", "partial"),
    [
        ("40% предоплаты", "40%"),
        ("предоплата 40%", "40%"),
        ("аванс: 40%", "40%"),
        ("предоплата 40%", "предоплата"),
        ("40% предоплаты", "предоплаты"),
    ],
)
def test_partial_model_quote_can_only_expand_to_one_literal_payment(
    payment: str, partial: str
) -> None:
    question = f"Для поставщика обсуждаем {payment}."
    deal = apply_deal(DealContext(), DealPatch(advance=partial), question)
    assert deal.advance == payment
    assert deal.terms["advance"].text == payment
    validate_deal(deal)


@pytest.mark.parametrize("payment", ["0% предоплаты", "аванс 0%", "предоплата 0,0%", "без аванса"])
def test_no_advance_does_not_invent_payment_after_delivery(payment: str) -> None:
    question = f"Проверь поставщика. Условия: {payment}."
    deal = apply_deal(DealContext(), literal_deal_patch(question), question)
    text = deal_implication_facts(deal)[0].claim.text
    assert f"«{payment}»" in text and "без аванса" in text
    assert "окончательного расчёта не уточнён" in text
    assert "после исполнения" not in text and "Вы планируете аванс" not in text


@pytest.mark.parametrize(
    "payment",
    [
        "40% предоплаты, остальная оплата после приёмки",
        "аванс 40%, остальное после приёмки",
        "40% аванса и остаток после поставки",
    ],
)
def test_split_payment_keeps_both_parts_in_literal_fact(payment: str) -> None:
    question = f"Проверь подрядчика. Условия: {payment}."
    deal = apply_deal(DealContext(), literal_deal_patch(question), question)
    assert deal.advance == payment
    text = deal_implication_facts(deal)[0].claim.text
    assert f"«{payment}»" in text and "до перечисления денег" in text
    assert "полный аванс" not in text and "без аванса" not in text


@pytest.mark.parametrize(
    ("role", "required", "forbidden"),
    [
        ("покупатель", "Авансовая часть поступает вам", "вы перечисляете"),
        ("поставщик", "до перечисления денег", "Авансовая часть поступает вам"),
        (None, "До перевода денег стоит уточнить", "Авансовая часть поступает вам"),
    ],
)
def test_payment_direction_is_not_guessed(role: str | None, required: str, forbidden: str) -> None:
    payment = "40% предоплаты"
    question = f"{role or 'Компания'}, {payment}"
    deal = apply_deal(DealContext(), DealPatch(role=role, advance=payment), question)
    effect = deal_implication_facts(deal)[0]
    assert required in effect.claim.text and forbidden not in effect.claim.text
    assert f"«{payment}»" in effect.claim.text
    assert set(effect.claim.evidence_ids) == {term.evidence_id for term in deal.terms.values()}


def test_changing_deferral_replaces_old_payment_and_its_evidence() -> None:
    deal = apply_deal(
        DealContext(),
        DealPatch(role="покупатель", advance="оплата через 60 дней"),
        "покупатель, оплата через 60 дней",
    )
    old_id = deal.terms["advance"].evidence_id
    updated = apply_deal(deal, DealPatch(advance="отсрочка 30 дней"), "Теперь отсрочка 30 дней")
    validate_deal(updated)
    assert updated.context_revision == deal.context_revision + 1
    assert updated.role == deal.role
    facts = (*deal_facts(updated), *deal_implication_facts(updated))
    assert all("60 дней" not in fact.claim.text for fact in facts)
    assert all(old_id not in fact.claim.evidence_ids for fact in facts)
    effect = deal_implication_facts(updated)[0]
    assert "30 дней" in effect.claim.text and "неполучения оплаты" in effect.claim.text
    assert "аванс" not in effect.claim.text


def test_payment_effect_refuses_tampered_provenance() -> None:
    deal = apply_deal(DealContext(), DealPatch(advance="аванс 40%"), "аванс 40%")
    deal.terms["advance"].evidence_id = "подменённый-источник"
    with pytest.raises(ValueError, match="происхождение"):
        deal_implication_facts(deal)


def test_percentage_without_payment_is_not_expanded_or_interpreted() -> None:
    deal = apply_deal(DealContext(), DealPatch(advance="40%"), "Обсуждаем 40%")
    assert deal.advance == "40%" and not deal_implication_facts(deal)


def test_literal_recovery_does_not_combine_different_payment_sentences() -> None:
    patch = literal_deal_patch("Проверь поставщика. Аванс 40%. Предоплата 20%.")
    assert patch.advance is None
