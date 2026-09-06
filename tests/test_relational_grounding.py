"""Числа из источника не разрешают новый денежный вывод или подмену судебной роли."""

import pytest

from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim, ReviewBlock, ReviewDraft
from counterparty_agent.ai.grounding import (
    validate_relational_grounding,
    validate_scenario_grounding,
)
from counterparty_agent.ai.reasoning import validate_draft


def fact(key, text, topic="granular_metric"):
    return ApprovedFact(key, GroundedClaim(text=text, evidence_ids=(key + "_e",)), topic)


FINANCE = (
    fact("assets", "Активы за 2025: 8 046 000 рублей."),
    fact("amount", "Со слов пользователя — сумма сделки: «300 000 рублей».", "deal_context"),
)
ARBITRATION = fact(
    "cases",
    "Судебных дел в отчёте: 3. Сумма требований: 390 000 рублей. "
    "Завершённых дел в роли истца: 1; в роли ответчика: 2. "
    "Незавершённых дел в роли ответчика: нет данных. "
    "Наличие дела не означает проигрыш или подтверждённый долг.",
    "arbitration_summary",
)


def check(text, facts=FINANCE, *, kind="interpretation"):
    block = ReviewBlock.model_validate(
        {"kind": kind, "text": text, "fact_ids": [item.fact_id for item in facts]}
    )
    validate_relational_grounding(block, facts)


@pytest.mark.parametrize("kind", ["fact", "interpretation", "action"])
@pytest.mark.parametrize(
    "text",
    [
        "Сумма небольшая по сравнению с активами компании (8 046 000 рублей на 2025 год).",
        "Сумма сделки 300 000 рублей меньше активов компании 8 046 000 рублей.",
        "Активы превышают сумму аванса.",
        "На фоне активов такой аванс невелик.",
        "Сумма предоплаты составляет небольшую долю активов.",
        "Аванс для компании посильный.",
        "Долг незначительный, поэтому его можно не учитывать.",
        "Выручка компании больше выручки другого участника.",
        "Уточните причины, по которым сумма аванса небольшая.",
        "300 000 ₽ — небольшая сумма для этого контрагента.",
        "Сделка небольшая для компании.",
    ],
)
def test_money_assertions_require_a_comparison_not_just_operands(kind, text):
    with pytest.raises(ValueError, match="денежное сравнение"):
        check(text, kind=kind)


@pytest.mark.parametrize(
    "text",
    [
        "Нельзя назвать аванс небольшим только по величине активов.",
        "Недостаточно данных, чтобы считать сумму аванса посильной для компании.",
        "Сравните сумму сделки с текущими обязательствами, когда получите актуальные данные.",
        "Сначала сопоставьте сумму договора и сведения о денежных средствах.",
        "Уточните, насколько сумма существенна для вашей компании.",
        "Насколько сумма аванса существенна для вас?",
        "Выручка не равна прибыли.",
        "Известная сумма не равна общему долгу компании.",
        "Убыток — существенное основание для дополнительной проверки.",
        "У компании больше активных производств, чем у другого участника.",
        "Активы за 2025: 8 046 000 рублей. По вашим условиям сумма сделки — 300 000 рублей.",
    ],
)
def test_requests_limits_and_separate_values_are_not_unapproved_comparisons(text):
    check(text, kind="action")


@pytest.mark.parametrize(
    ("text", "allowed"),
    [
        ("Для решения об авансе существенно выяснить статус производства.", True),
        ("Перед перечислением денег существенно сначала проверить сумму взыскания.", True),
        ("При предоплате существенно прежде всего уточнить основание производства.", True),
        (
            "Для решения об авансе существенно выяснить статус производства: "
            "сумма существенная и аванс крупный.",
            False,
        ),
        (
            "Перед авансом существенно проверить статус: "
            "сумма незначительна относительно активов.",
            False,
        ),
    ],
)
def test_check_priority_does_not_authorize_money_assessments(text, allowed):
    if allowed:
        check(text, kind="action")
    else:
        with pytest.raises(ValueError, match="денежное сравнение"):
            check(text, kind="action")


@pytest.mark.parametrize(
    "text",
    [
        "Сначала стоит запросить больше данных об исполнении работ до перечисления аванса.",
        "У компании меньше вопросов к документам перед перечислением аванса.",
        "Перед авансом нужна дополнительная проверка: запросите больше сведений об опыте.",
        "Для решения об авансе есть существенные неизвестные: опыт работ не подтверждён.",
        "Уточните существенные условия аванса до перечисления денег.",
    ],
)
def test_nonfinancial_operand_is_not_compared_to_a_distant_advance(text):
    check(text, kind="action")


@pytest.mark.parametrize(
    "text",
    [
        "Запросите больше данных, долг небольшой относительно активов.",
        "Перед авансом нужно больше данных: сумма сделки незначительна.",
        "У компании меньше вопросов к документам, аванс для компании посильный.",
        "Запросите больше данных об опыте; выручка компании А выше выручки компании Б.",
        "Долг компании ТЕХПРОФ является небольшим.",
        "Активы за 2025 год выше суммы аванса.",
    ],
)
def test_check_request_does_not_hide_a_separate_monetary_operand(text):
    with pytest.raises(ValueError, match="денежное сравнение"):
        check(text, kind="action")


def test_explicit_approved_comparison_can_be_quoted():
    comparison = fact(
        "comparison",
        "Сумма сделки 300 000 рублей меньше активов компании 8 046 000 рублей.",
        "comparison_financial",
    )
    check(comparison.claim.text, (*FINANCE, comparison))


def test_comparison_table_with_no_calculated_relation_is_not_permission_to_compare():
    comparison = fact(
        "comparison",
        "Выручка. Компания 1: 300 000 рублей. Компания 2: 8 046 000 рублей.",
        "comparison_financial",
    )
    with pytest.raises(ValueError, match="денежное сравнение"):
        check("Выручка компании 1 меньше выручки компании 2.", (comparison,))


def test_negative_source_boundary_does_not_authorize_the_opposite_money_claim():
    boundary = fact("limit", "Нельзя сказать, что сумма аванса небольшая по сравнению с активами.")
    with pytest.raises(ValueError, match="денежное сравнение"):
        check("Сумма аванса небольшая по сравнению с активами.", (*FINANCE, boundary))


@pytest.mark.parametrize(
    "text",
    [
        "Компания была ответчиком в 2 делах.",
        "В роли ответчика: 2 дела.",
        "Всего ответчик — 2 дела.",
        "В отчёте 2 дела в роли ответчика.",
        "Незавершённых дел в роли ответчика: 2.",
    ],
)
def test_finished_count_cannot_become_total_or_pending_count(text):
    with pytest.raises(ValueError, match="завершённых дел ответчика"):
        check(text, (ARBITRATION,))


@pytest.mark.parametrize(
    "text",
    [
        ARBITRATION.claim.text,
        "Компания была ответчиком в 2 завершённых делах.",
        "Завершённых дел в роли ответчика: 2. Незавершённые дела неизвестны.",
        "В отчёте есть дела с участием компании в роли ответчика.",
        "Нельзя утверждать, что всего компания была ответчиком в 2 делах.",
        "Судебных дел в отчёте: 3. Сумма требований: 390 000 рублей.",
    ],
)
def test_qualified_counts_and_legal_limits_remain_available(text):
    check(text, (ARBITRATION,))


def test_explicit_total_defendant_count_is_not_rejected():
    known_total = fact("total", "Всего дел в роли ответчика: 2.", "arbitration_summary")
    check("Компания была ответчиком в 2 делах.", (known_total,))


@pytest.mark.parametrize(
    "text",
    [
        "В отчёте 3 арбитражных дела, где компания выступает ответчиком.",
        "3 судебных дела, в которых компания выступала в роли ответчика.",
        "Компания была ответчиком в 3 делах.",
        "В отчёте три дела с компанией в роли ответчика.",
        "Есть два завершённых дела; компания была ответчиком в 3 делах.",
        "3 завершённых дела в роли ответчика.",
    ],
)
def test_all_roles_total_cannot_become_a_defendant_count(text):
    with pytest.raises(ValueError, match="общий итог судебных дел"):
        check(text, (ARBITRATION,))


def test_all_roles_total_is_not_a_role_total_even_when_pending_count_is_known():
    source = fact(
        "cases",
        ARBITRATION.claim.text.replace("ответчика: нет данных", "ответчика: 0"),
        "arbitration_summary",
    )
    with pytest.raises(ValueError, match="общий итог судебных дел"):
        check("3 арбитражных дела, где компания является ответчиком.", (source,))


def test_explicit_defendant_total_and_qualified_relative_clause_remain_available():
    known_total = fact("total", "Всего дел в роли ответчика: 3.", "arbitration_summary")
    check("3 арбитражных дела, где компания выступает ответчиком.", (known_total,))
    check("2 завершённых дела, в которых компания выступала ответчиком.", (ARBITRATION,))
    source = fact(
        "cases",
        ARBITRATION.claim.text.replace("в отчёте: 3", "в отчёте: 2")
        .replace("ответчика: нет данных", "ответчика: 0"),
        "arbitration_summary",
    )
    check("2 завершённых дела, где компания выступала ответчиком.", (source,))


@pytest.mark.parametrize(
    "text",
    [
        "Всего 3 дела, из которых два — в роли ответчика.",
        "В отчёте 3 дела, из них два в роли ответчика.",
        "Компания была ответчиком в двух делах.",
    ],
)
def test_spelled_defendant_count_keeps_the_finished_qualifier(text):
    with pytest.raises(ValueError, match="завершённых дел ответчика"):
        check(text, (ARBITRATION,))


def test_small_spelled_counts_work_beyond_two_and_in_different_cases():
    words = "одному двум трём четырём пяти шести семи восьми девяти десяти".split()
    for number, word in enumerate(words, start=1):
        source = fact(
            "cases",
            ARBITRATION.claim.text.replace("в роли ответчика: 2", f"в роли ответчика: {number}")
            .replace("в отчёте: 3", f"в отчёте: {number + 1}"),
            "arbitration_summary",
        )
        with pytest.raises(ValueError, match="завершённых дел ответчика"):
            noun = "делу" if number == 1 else "делам"
            check(f"Компания была ответчиком по {word} {noun}.", (source,))


def test_spelled_qualified_counts_do_not_become_a_new_number_normalization():
    check("Два завершённых дела с компанией в роли ответчика.", (ARBITRATION,))
    check("Из них два завершённых дела в роли ответчика.", (ARBITRATION,))
    known_total = fact("total", "Всего дел в роли ответчика: 2.", "arbitration_summary")
    check("Из них два — в роли ответчика.", (known_total,))


@pytest.mark.parametrize(
    "text,facts,error",
    [
        (
            "Сумма 300 000 рублей небольшая по сравнению с активами 8 046 000 рублей за 2025 год.",
            FINANCE,
            "денежное сравнение",
        ),
        ("Компания была ответчиком в 2 делах.", (ARBITRATION,), "завершённых дел ответчика"),
        (
            "3 арбитражных дела, где компания выступает ответчиком.",
            (ARBITRATION,),
            "общий итог судебных дел",
        ),
    ],
)
def test_full_draft_validation_checks_relations_even_when_every_number_exists(text, facts, error):
    block = ReviewBlock(kind="interpretation", text=text, fact_ids=[item.fact_id for item in facts])
    with pytest.raises(ValueError, match=error):
        validate_draft(ReviewDraft(blocks=[block]), {item.fact_id: item for item in facts})


def check_scenario(text, facts=(ARBITRATION,)):
    block = ReviewBlock(kind="interpretation", text=text, fact_ids=[item.fact_id for item in facts])
    validate_scenario_grounding(ReviewDraft(blocks=[block]), {item.fact_id: item for item in facts})


@pytest.mark.parametrize(
    "text",
    [
        "Сейчас компания не отказывала вам в проверке.",
        "Компания отказалась предоставлять документы.",
        "Отказа пока не было.",
        "Отказ в документах уже получен.",
        "Компания предоставила документы.",
        "Компания не предоставила документы.",
        "Документы не предоставлены.",
        "Подтверждения уже получены.",
        "Они скрывают сведения.",
        "Они ничего не скрывают.",
        "Если компания откажется, значит она скрывает документы.",
        "Неизвестно, почему они отказались предоставить документы.",
    ],
)
def test_scenario_does_not_prove_positive_or_negative_company_events(text):
    with pytest.raises(ValueError, match="гипотеза не подтверждает"):
        check_scenario(text)


@pytest.mark.parametrize(
    "text",
    [
        "Если компания откажется, уточните причину и обсудите альтернативное подтверждение.",
        "Если документы не предоставлены, не считайте вопрос проверенным.",
        "При отказе запросите объяснение и обсудите изменение условий оплаты.",
        "Попросите предоставить пояснения к сведениям отчёта.",
        "Неизвестно, отказалась ли компания предоставлять документы.",
        "Отказывалась ли компания предоставить документы?",
        "Нет сведений, что компания отказалась предоставить документы.",
        "Нельзя утверждать, что компания ничего не скрывает.",
        "Вы описали возможный отказ, а не подтверждённое действие компании.",
        "Вопрос об отказе пока гипотетический. Если откажут, обсудите другое подтверждение.",
    ],
)
def test_conditional_actions_and_limits_do_not_invent_an_event(text):
    check_scenario(text)


def test_explicit_document_event_is_allowed_with_its_source():
    document = fact(
        "letter",
        "В письме указано: компания отказалась предоставить документы.",
        "document",
    )
    check_scenario(document.claim.text, (document,))


def test_hypothesis_in_a_document_is_not_proof_of_actual_refusal():
    document = fact(
        "letter",
        "Если компания отказалась предоставить документы, запросите объяснение.",
        "document",
    )
    with pytest.raises(ValueError, match="гипотеза не подтверждает"):
        check_scenario("Компания отказалась предоставить документы.", (document,))


@pytest.mark.parametrize(
    "text",
    [
        "Обсудите меньший аванс или оплату по этапам.",
        "Если подтверждения не дадут, рассмотрите меньшую предоплату.",
        "Предложите небольшой аванс и оплату остатка после приёмки.",
        "Обсудите вариант с небольшим авансом.",
        "Можно рассмотреть минимальную предоплату и согласовать этапы приёмки.",
        "Согласуйте размер аванса ниже и оплату оставшейся суммы после исполнения.",
        "Если нет подтверждений, обсудите аванс меньше или постоплату.",
    ],
)
def test_proposing_payment_options_is_not_assessing_company_finances(text):
    check(text, kind="action")


@pytest.mark.parametrize(
    "text",
    [
        "Сумма долга небольшая относительно активов.",
        "Обсудите, почему сумма долга небольшая относительно активов.",
        "Обсудите небольшую сумму долга относительно активов.",
        "Обсудите небольшой аванс по сравнению с активами компании.",
        "Обсудите аванс меньше активов компании.",
        "Обсудите меньший аванс: сумма долга небольшая относительно активов.",
        "Рассмотрите меньшую предоплату, ведь долг компании незначительный.",
        "Предложите небольшой аванс, это посильная сумма для компании.",
    ],
)
def test_action_or_payment_proposal_does_not_mask_an_unapproved_financial_assessment(text):
    with pytest.raises(ValueError, match="денежное сравнение"):
        check(text, kind="action")


@pytest.mark.parametrize(
    "text",
    [
        "Оплата по этапам снизит риск потери денег, но не гарантирует исполнение договора.",
        "Гарантия уменьшит риск потери денег; нельзя считать её одобрением сделки.",
        "Обсудите аванс: он снизит риск потери денег.",
        "Обсудите, какие меры могли бы помочь, а гарантия снизит риск неоплаты.",
    ],
)
def test_risk_promise_is_not_hidden_by_an_independent_boundary_or_discussion(text):
    with pytest.raises(ValueError, match="результат меры"):
        check(text, kind="action")


@pytest.mark.parametrize(
    "text",
    [
        "Обсудите, какие меры могли бы снизить риск неисполнения.",
        "Попросите специалиста оценить, снижает ли обеспечение риск неоплаты.",
        "Снизит ли изменение оплаты риск неоплаты?",
        "Нельзя подтвердить, что эта мера снизит риск потери денег.",
        "Обсудите меньший аванс, если компания не даст подтверждения.",
    ],
)
def test_discussion_of_possible_risk_effect_is_not_a_promised_result(text):
    check(text, kind="action")


@pytest.mark.parametrize(
    ("text", "allowed"),
    [
        ("Обсудите постоплату: она защитит ваши средства и защищает аванс.", False),
        ("Это перенесёт финансовые риски на исполнителя.", False),
        (
            "Защитит ли это ваши деньги? Переносит ли он риски на исполнителя? "
            "Обсудите варианты защиты средств и переноса рисков.",
            True,
        ),
        (
            "Нельзя подтвердить, что этот вариант защитит ваши средства. "
            "Недостаточно данных, чтобы сказать, что он перенесёт финансовые риски.",
            True,
        ),
    ],
)
def test_money_protection_and_risk_transfer_need_an_explicit_source(text, allowed):
    if allowed:
        check(text, kind="action")
    else:
        with pytest.raises(ValueError, match="результат меры"):
            check(text, kind="action")


def test_money_protection_and_risk_transfer_can_repeat_an_existing_source():
    source = fact(
        "effect",
        "Этот вариант защитит средства и перенесёт финансовые риски на исполнителя.",
    )
    check(source.claim.text, (source,), kind="fact")
