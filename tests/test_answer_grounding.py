"""Языковые границы анализа: ясность не разрешает придумывать диагноз или причину."""

import pytest

from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim, ReviewBlock, ReviewDraft
from counterparty_agent.ai.deal import DealContext, DealPatch, apply_deal
from counterparty_agent.ai.follow_up import QUESTIONS, allowed_follow_ups
from counterparty_agent.ai.reasoning import (
    GroundingVerdict,
    synthesize,
    validate_draft,
)
from counterparty_agent.config import Settings


def check(text: str, source: str, *, kind: str = "interpretation") -> None:
    fact = ApprovedFact("f", GroundedClaim(text=source, evidence_ids=("e",)), "financial")
    draft = ReviewDraft.model_validate(
        {"blocks": [{"kind": kind, "text": text, "fact_ids": ["f"]}]}
    )
    validate_draft(draft, {"f": fact})


@pytest.mark.parametrize("kind", ["fact", "interpretation", "action"])
@pytest.mark.parametrize(
    "text",
    [
        "Финансовое положение ООО «ТЕТРАДОМ» нестабильно.",
        'Финансовое состояние ООО "ПРИМЕР" устойчивое.',
        "Финансы выбранного вами подрядчика ООО «ПРИМЕР» нестабильны.",
        "ООО «ПРИМЕР» финансово неустойчиво.",
        "Отрицательный капитал указывает на финансовую напряжённость.",
        "Финансовое положение ухудшается.",
    ],
)
def test_quoted_company_name_does_not_hide_financial_diagnosis(kind, text):
    with pytest.raises(ValueError, match="финансовая устойчивость"):
        check(text, "Прибыль за 2025: -100 рублей.", kind=kind)


@pytest.mark.parametrize(
    "source",
    [
        "Прибыль не гарантирует финансовую устойчивость компании.",
        "По значению прибыли нельзя оценить финансовую устойчивость.",
        "Финансовая устойчивость не подтверждена.",
        "Запросите данные, чтобы оценить финансовую устойчивость.",
    ],
)
def test_source_boundary_or_request_does_not_prove_a_financial_diagnosis(source):
    with pytest.raises(ValueError, match="финансовая устойчивость"):
        check("Финансовое положение компании нестабильно.", source)


@pytest.mark.parametrize(
    "text",
    [
        "Это может означать паузу в деятельности или особенности учёта.",
        "Вероятно, дело в особенностях бухгалтерского учёта.",
        "У компании перерыв в продажах.",
        "Возможно, работа приостановлена.",
        "Запросите объяснение прекращения деятельности.",
    ],
)
def test_zero_revenue_does_not_authorize_speculative_causes(text):
    with pytest.raises(ValueError, match="причина финансового значения"):
        check(
            text,
            "Выручка за 2025: 0 рублей. Нулевое значение не доказывает прекращение деятельности.",
        )


@pytest.mark.parametrize(
    "text",
    [
        "Финансовая устойчивость не подтверждена этими сведениями.",
        "Убыток не доказывает финансовую неустойчивость.",
        "Запросите данные, чтобы оценить финансовую устойчивость покупателя.",
        "Нулевая выручка не доказывает прекращение деятельности.",
        "Сверьте значение выручки с отчётностью и запросите объяснение его причины.",
    ],
)
def test_supported_limits_and_next_checks_are_not_diagnoses(text):
    check(text, "Выручка за 2025: 0 рублей.", kind="action")


def test_negation_in_previous_clause_does_not_mask_positive_diagnosis():
    with pytest.raises(ValueError, match="финансовая устойчивость"):
        check(
            "Прибыль не гарантирует финансовую устойчивость, но финансовое положение нестабильно.",
            "Прибыль не гарантирует финансовую устойчивость.",
        )


def test_known_zero_and_exact_numbers_remain_valid():
    fact = ApprovedFact(
        "f", GroundedClaim(text="Выручка за 2025: 0 рублей.", evidence_ids=("e",)), "financial"
    )
    validate_draft(
        ReviewDraft(
            blocks=[ReviewBlock(kind="fact", text=fact.claim.text, fact_ids=[fact.fact_id])]
        ),
        {fact.fact_id: fact},
    )


@pytest.mark.asyncio
async def test_follow_up_is_grounded_as_part_of_the_returned_answer(monkeypatch):
    deal = apply_deal(
        DealContext(),
        DealPatch(role="поставщик", advance="40% предоплаты"),
        "Нужен поставщик, 40% предоплаты",
    )
    fact = ApprovedFact(
        "f", GroundedClaim(text="Прибыль за 2025: -100 рублей.", evidence_ids=("e",)), "financial"
    )
    checked_texts = []

    async def fake_call(settings, client, question, data, prompt, schema):
        if schema is ReviewDraft:
            assert data["current_deal"]["advance"] == "40% предоплаты"
            assert data["allowed_follow_up_fields"] == allowed_follow_ups(deal)
            return ReviewDraft(
                blocks=[ReviewBlock(kind="fact", text=fact.claim.text, fact_ids=["F1"])],
                follow_up_field="subject",
            )
        assert schema is GroundingVerdict
        assert data["follow_up_field"] == "subject"
        checked_texts.append("\n\n".join(block["text"] for block in data["blocks"]))
        return GroundingVerdict(unsupported_blocks=[], answers_question=True)

    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", fake_call)
    answer, draft = await synthesize(
        Settings(_env_file=None),
        object(),
        "На что обратить внимание перед авансом?",
        deal,
        {fact.fact_id: fact},
        "Доступны финансовые показатели.",
    )
    assert draft.follow_up_field == "subject"
    assert answer.answer.endswith(QUESTIONS["subject"])
    assert answer.answer.count(QUESTIONS["subject"]) == 1
    assert checked_texts == [answer.answer]
    assert deal.asked_fields == []  # Память меняет workflow только после успешного ответа.


async def test_model_repair_preserves_requested_follow_up_without_literal_substitution(monkeypatch):
    fact = ApprovedFact(
        "f", GroundedClaim(text="Прибыль за 2025: -100 рублей.", evidence_ids=("e",)), "financial"
    )
    deal = apply_deal(
        DealContext(), DealPatch(role="поставщик", advance="аванс"), "Поставщик просит аванс"
    )
    generated = []

    async def complete(settings, client, question, data, prompt, schema):
        if schema is GroundingVerdict:
            return GroundingVerdict(unsupported_blocks=[], answers_question=True)
        text = (
            "Прибыль за 2025: -999 рублей."
            if not generated
            else "За 2025 в отчёте указана прибыль -100 рублей."
        )
        generated.append(text)
        return ReviewDraft(
            blocks=[ReviewBlock(kind="fact", text=text, fact_ids=["F1"])],
            follow_up_field="subject",
        )

    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", complete)
    answer, repaired = await synthesize(
        Settings(_env_file=None), object(), "Что учесть до аванса?", deal, {"f": fact}, "Финансы"
    )
    assert len(generated) == 2
    assert repaired.follow_up_field == "subject"
    assert answer.answer == f"{generated[-1]}\n\n{QUESTIONS['subject']}"
    assert repaired.blocks[0].text != fact.claim.text


@pytest.mark.parametrize("kind", ["fact", "interpretation", "action"])
@pytest.mark.parametrize(
    "text",
    [
        "Нельзя утверждать, что риск высокий.",
        "Я не могу назвать одну компанию более предпочтительной без подтверждённого критерия.",
        "Эти сведения не подтверждают способность компании исполнить обязательства.",
    ],
)
def test_risk_preference_and_capability_boundaries_are_not_positive_claims(kind, text):
    check(text, "Прибыль за 2025: -100 рублей.", kind=kind)


@pytest.mark.parametrize("kind", ["fact", "interpretation", "action"])
@pytest.mark.parametrize(
    "source",
    [
        "Нельзя утверждать, что риск высокий.",
        "Высокий риск не подтверждён этими сведениями.",
        "Нет оснований утверждать, что риск высокий.",
    ],
)
def test_negated_risk_in_a_source_does_not_support_positive_risk(kind, source):
    with pytest.raises(ValueError, match="уровень риска"):
        check("У компании высокий риск.", source, kind=kind)


@pytest.mark.parametrize("kind", ["fact", "interpretation", "action"])
@pytest.mark.parametrize(
    ("text", "error"),
    [
        (
            "Нельзя утверждать, что риск высокий, но у компании низкий риск.",
            "уровень риска",
        ),
        (
            "Эти сведения не подтверждают способность компании исполнить обязательства, "
            "но компания способна исполнить договор.",
            "способность исполнить",
        ),
    ],
)
def test_boundary_does_not_hide_an_unbacked_claim_in_the_next_clause(kind, text, error):
    with pytest.raises(ValueError, match=error):
        check(text, "Прибыль за 2025: -100 рублей.", kind=kind)


@pytest.mark.parametrize("kind", ["fact", "interpretation", "action"])
@pytest.mark.parametrize(
    ("text", "error"),
    [
        (
            "У компании высокий риск, и это не означает неизбежного отказа от сделки.",
            "уровень риска",
        ),
        (
            "Компания способна исполнить договор, хотя это не гарантирует отсутствие проблем.",
            "способность исполнить",
        ),
        (
            "Не могу подтвердить данные отчёта, поэтому компания имеет высокий риск.",
            "уровень риска",
        ),
        (
            "У компании высокий риск, что не означает неизбежного отказа от сделки.",
            "уровень риска",
        ),
        (
            "Нельзя утверждать, что риск высокий, и у компании низкий риск.",
            "уровень риска",
        ),
    ],
)
def test_negation_applies_to_its_claim_not_an_independent_risk_or_capability(kind, text, error):
    with pytest.raises(ValueError, match=error):
        check(text, "Прибыль за 2025: -100 рублей.", kind=kind)


@pytest.fixture
def comparison_case():
    catalog = {
        "a": ApprovedFact(
            "a",
            GroundedClaim(
                text="Компания А (ИНН 0000000000): Сведения о лицензиях отсутствуют. "
                "Это не доказывает отсутствие лицензии.",
                evidence_ids=("a-license",),
            ),
            "licenses",
        ),
        "b": ApprovedFact(
            "b",
            GroundedClaim(
                text="Компания Б (ИНН 1111111111): В отчёте указана лицензия на перевозки.",
                evidence_ids=("b-license",),
            ),
            "licenses",
        ),
    }
    text = (
        "Если выбирать по наличию сведений о разрешениях, Компания Б выглядит более "
        "предпочтительной: в её отчёте указана лицензия на перевозки. У Компании А "
        "сведений о лицензиях нет; это основание запросить подтверждение, а не считать "
        "работу незаконной. Этот критерий сам по себе не решает, кому перечислять аванс."
    )
    return catalog, text


def test_new_preference_cannot_be_presented_as_a_report_fact(comparison_case):
    catalog, text = comparison_case
    draft = ReviewDraft(blocks=[ReviewBlock(kind="fact", text=text, fact_ids=["a", "b"])])
    with pytest.raises(ValueError, match="предпочтение или ранжирование"):
        validate_draft(draft, catalog)


@pytest.mark.parametrize("kind", ["interpretation", "action"])
@pytest.mark.asyncio
async def test_criterion_based_comparison_preserves_model_text_after_semantic_approval(
    monkeypatch, comparison_case, kind
):
    catalog, text = comparison_case
    calls = []

    async def complete(settings, client, question, data, prompt, schema):
        calls.append(schema)
        if schema is ReviewDraft:
            return ReviewDraft(
                blocks=[ReviewBlock(kind=kind, text=text, fact_ids=["F1", "F2"])]
            )
        assert schema is GroundingVerdict
        assert data["blocks"] == [
            {"index": 0, "kind": kind, "text": text, "fact_ids": ["F1", "F2"]}
        ]
        assert {fact["fact_id"] for fact in data["approved_facts"]} == {"F1", "F2"}
        return GroundingVerdict(unsupported_blocks=[], answers_question=True)

    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", complete)
    answer, draft = await synthesize(
        Settings(_env_file=None),
        object(),
        "Сравни компании перед авансом по сведениям о разрешениях.",
        DealContext(),
        catalog,
        "Прочитаны сведения о лицензиях обеих компаний; другие разделы не проверены.",
    )
    assert calls == [ReviewDraft, GroundingVerdict]
    assert answer.status == "answered"
    assert answer.answer == text == draft.blocks[0].text
    assert answer.claims[0].evidence_ids == ("a-license", "b-license")


@pytest.mark.parametrize("kind", ["interpretation", "action"])
@pytest.mark.parametrize("answers_question", [True, False])
@pytest.mark.asyncio
async def test_unapproved_comparison_is_not_published_or_replaced_with_a_template(
    monkeypatch, comparison_case, kind, answers_question
):
    catalog, text = comparison_case
    calls = []

    async def complete(settings, client, question, data, prompt, schema):
        calls.append(schema)
        if schema is ReviewDraft:
            return ReviewDraft(
                blocks=[ReviewBlock(kind=kind, text=text, fact_ids=["F1", "F2"])]
            )
        assert schema is GroundingVerdict
        assert data["blocks"][0]["text"] == text
        return GroundingVerdict(
            unsupported_blocks=[0] if answers_question else [],
            answers_question=answers_question,
            reasons=["Выбранный критерий не обосновывает этот вывод для текущего вопроса."],
        )

    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", complete)
    with pytest.raises(ValueError, match="Не удалось подтвердить аналитический ответ"):
        await synthesize(
            Settings(_env_file=None),
            object(),
            "Кому перечислить аванс?",
            DealContext(),
            catalog,
            "Прочитаны только сведения о лицензиях обеих компаний.",
        )
    assert calls.count(ReviewDraft) == 3
    # Повторяющийся черновик не получает новый вердикт и не обходит прежний отказ.
    assert calls.count(GroundingVerdict) == 1


@pytest.mark.parametrize(
    ("second_error", "expected_feedback"),
    [
        ("Компания способна исполнить договор.", "способность исполнить"),
        ("Сделка гарантированно безопасна.", "обещание безопасности"),
    ],
)
@pytest.mark.asyncio
async def test_repair_receives_all_block_errors_and_exact_cited_amounts(
    monkeypatch, second_error, expected_feedback
):
    catalog = {
        "profit": ApprovedFact(
            "profit",
            GroundedClaim(text="Прибыль за 2025: 1234500 рублей.", evidence_ids=("e-profit",)),
            "financial",
        ),
        "revenue": ApprovedFact(
            "revenue",
            GroundedClaim(text="Выручка за 2025: 0 рублей.", evidence_ids=("e-revenue",)),
            "financial",
        ),
    }
    repaired_texts = [
        "За 2025 в отчёте указана прибыль 1,2345 млн рублей.",
        "Выручка за 2025 указана как 0 рублей; причину этого значения стоит уточнить.",
    ]
    calls = []

    async def complete(settings, client, question, data, prompt, schema):
        calls.append(schema)
        if schema is GroundingVerdict:
            assert [block["text"] for block in data["blocks"]] == repaired_texts
            return GroundingVerdict(unsupported_blocks=[], answers_question=True)
        assert schema is ReviewDraft
        if calls.count(ReviewDraft) == 1:
            return ReviewDraft(
                blocks=[
                    ReviewBlock(kind="fact", text="Прибыль: 1,2 млн рублей.", fact_ids=["F1"]),
                    ReviewBlock(kind="interpretation", text=second_error, fact_ids=["F2"]),
                ]
            )
        feedback = data["validation_feedback"]
        assert "Блок 0" in feedback and "Блок 1" in feedback
        assert "сумма" in feedback and expected_feedback in feedback
        assert data["cited_numeric_values"] == [
            {"fact_id": "F1", "numbers": ["1234500", "2025"], "rubles": ["1234500"]},
            {"fact_id": "F2", "numbers": ["0", "2025"], "rubles": ["0"]},
        ]
        return ReviewDraft(
            blocks=[
                ReviewBlock(kind="fact", text=repaired_texts[0], fact_ids=["F1"]),
                ReviewBlock(kind="interpretation", text=repaired_texts[1], fact_ids=["F2"]),
            ]
        )

    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", complete)
    answer, draft = await synthesize(
        Settings(_env_file=None),
        object(),
        "Что показывают финансовые данные?",
        DealContext(),
        catalog,
        "Доступны прибыль и выручка.",
    )
    assert calls == [ReviewDraft, ReviewDraft, GroundingVerdict]
    assert answer.answer == "\n\n".join(repaired_texts)
    assert [block.text for block in draft.blocks] == repaired_texts
