"""Содержательность резервного анализа на реальных отчётах и граничных случаях."""

from __future__ import annotations

from datetime import timedelta

import pytest
from test_review_agent import ReviewModel
from test_review_agent import source as real_source

from counterparty_agent.ai.briefing import safe_analysis_fallback, select_issues
from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim, ReviewBlock, ReviewDraft
from counterparty_agent.ai.deal import DealContext, DealPatch, apply_deal
from counterparty_agent.ai.reasoning import GroundingVerdict, validate_draft
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.workflow.review import review_catalog, run_review, validate_review_run

source = real_source


def contractor(advance: str = "аванс") -> DealContext:
    return apply_deal(
        DealContext(),
        DealPatch(role="подрядчик", advance=advance),
        f"Нужен подрядчик, условия: {advance}",
    )


def april(source: JsonCounterpartySource):
    result = source.find_by_inn("7813664770")
    if not result.candidates:
        pytest.skip("Отчёт пользовательского сценария не подключён")
    return source.get_snapshot(result.candidates[0].snapshot_id)


def test_april_fallback_prioritizes_zero_revenue_before_minor_data_mismatch(source):
    snapshot = april(source)
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=35))
    catalog, _ = review_catalog((snapshot,), (analysis,), contractor())
    draft = safe_analysis_fallback("На что обратить внимание перед авансом?", contractor(), catalog)
    assert draft is not None
    validate_draft(draft, catalog)
    facts = [catalog[key] for block in draft.blocks for key in block.fact_ids]
    metrics = {fact.metric or fact.topic for fact in facts}
    assert {
        "enforcement_summary",
        "arbitration_summary",
        "financial_zero_revenue",
    } <= metrics
    text = "\n".join(block.text for block in draft.blocks)
    assert "2025" in text and "0 рублей" in text
    assert "29\u202f000" not in text
    assert any(f.metric == "financial_assets_components_mismatch" for f in catalog.values())
    assert "приёмки работ" in text
    assert "поставщик" not in text and "до поставки" not in text
    assert "состояния исполнительных производств" in text
    assert "результаты судебных дел" in text
    assert "Причина нулевого значения не указана" in text
    assert "не доказывает прекращение" in text
    assert all(
        "возраст отчёта" not in block.text for block in draft.blocks if block.kind == "limitation"
    )
    assert "Изменения после этой даты" in text
    assert not any(
        word in text for word in ("Отдельный сигнал", "Связанные финансовые", "snapshot")
    )
    assert "отмечено обстоятельство для проверки: арбитражные" not in text
    assert len(text.split()) <= 180


def test_group_gaps_cover_distinct_topics_instead_of_repeating_financial_years(source):
    snapshot = source.get_snapshot(source.find_by_inn("1684017097").candidates[0].snapshot_id)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )
    draft = safe_analysis_fallback(
        "Каких данных не хватает для нашей сделки?", contractor(), catalog
    )
    assert draft is not None
    validate_draft(draft, catalog)
    topics = {catalog[key].topic for block in draft.blocks for key in block.fact_ids}
    assert {"financial_fields_missing", "arbitration_summary"} <= topics
    text = "\n".join(block.text for block in draft.blocks)
    assert "2025" in text and "2024" not in text
    assert "Сводных данных о судебных делах нет" in text
    general = safe_analysis_fallback("На что обратить внимание?", contractor(), catalog)
    assert general is not None
    general_text = "\n".join(block.text for block in general.blocks)
    assert "сигналов внимания не выявлено" in general_text
    assert "60\u202f746\u202f000" in general_text
    assert "Годовая статистика судов отсутствует" not in general_text
    validate_draft(general, catalog)


def test_fallback_financial_difference_is_derived_and_cited(source):
    snapshot = april(source)
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    finding = next(f for f in analysis.findings if f.code == "financial_assets_components_mismatch")
    evidence = next(e for e in analysis.derived_evidence if e.evidence_id in finding.evidence_ids)
    values = evidence.typed_value
    assert values["difference"] == abs(values["total"] - values["parts_sum"])
    assert evidence.derived_from


def test_april_arbitration_distinguishes_roles_and_unknown_pending_cases(source):
    snapshot = april(source)
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    finding = next(f for f in analysis.findings if f.code == "arbitration_summary")
    assert "Судебных дел в отчёте: 3" in finding.statement
    assert "в роли истца: 1" in finding.statement
    assert "в роли ответчика: 2" in finding.statement
    assert "Незавершённых дел в роли ответчика: нет данных" in finding.statement


def test_report_date_uses_the_same_moscow_day_as_company_card(source):
    snapshot = april(source)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )
    date = next(f for f in catalog.values() if f.topic == "report_date")
    assert "02.08.2026" in date.claim.text
    assert "01.08.2026" not in date.claim.text


@pytest.mark.parametrize("kind", ["fact", "interpretation", "limitation", "action"])
@pytest.mark.parametrize(
    "text",
    [
        "В предоставленных данных отсутствует информация о второй компании.",
        "Данных по выбранной компании нет. Загрузите отчёт.",
        "Отчёт по контрагенту не предоставлен.",
        "Нет сведений об этой компании.",
    ],
)
def test_existing_report_cannot_be_declared_missing_even_with_valid_references(source, kind, text):
    snapshot = april(source)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )
    status = next(key for key, fact in catalog.items() if fact.topic == "company_status")
    with pytest.raises(ValueError, match="отчёт выбранной компании уже передан"):
        validate_draft(
            ReviewDraft(blocks=[ReviewBlock(kind=kind, text=text, fact_ids=[status])]), catalog
        )


@pytest.mark.parametrize(
    "text",
    [
        "Нет сведений о судебных делах компании. Это не означает, что дел не было.",
        "Нет данных для оценки опыта компании.",
        "Отчёт доступен, но не содержит сведений о качестве работ компании.",
    ],
)
def test_missing_topic_is_not_confused_with_missing_company_report(source, text):
    from counterparty_agent.ai.validation import validate_report_availability

    snapshot = april(source)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )
    validate_report_availability(
        ReviewDraft(
            blocks=[ReviewBlock(kind="limitation", text=text, fact_ids=[next(iter(catalog))])]
        ),
        catalog,
    )


async def test_false_missing_company_is_repaired_even_when_llm_verifier_accepts(
    source, monkeypatch
):
    from pydantic import SecretStr

    snapshot = april(source)

    def false_draft(data):
        fact = next(f for f in data["approved_facts"] if f["topic"] == "company_status")
        return ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind="limitation",
                    text="В предоставленных данных отсутствует информация о второй компании.",
                    fact_ids=[fact["fact_id"]],
                )
            ]
        )

    model = ReviewModel(monkeypatch, draft=false_draft)
    deal = contractor()
    deal.snapshot_ids = ["other-selected-company", snapshot.snapshot_id]
    run = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        "А что по второй компании именно для нашей сделки?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        deal,
        client=object(),
    )
    assert run.answer.status == "answered"
    assert "отсутствует информация о второй" not in run.answer.answer
    assert snapshot.identity.short_name in run.answer.answer
    assert len(model.inputs(ReviewDraft)) == 2
    validate_review_run(run)


@pytest.mark.parametrize("kind", ["fact", "interpretation", "action"])
@pytest.mark.parametrize(
    "text",
    [
        "Финансовая картина нестабильна.",
        "Выручка упала до 0 рублей.",
        "Финансовые проблемы компании теперь влияют только на сроки и качество ремонта.",
    ],
)
def test_financial_diagnosis_and_uncalculated_trend_are_not_allowed_in_any_block(kind, text):
    fact = ApprovedFact(
        "f",
        GroundedClaim(text="Выручка за 2025: 0 рублей.", evidence_ids=("e",)),
        "granular_metric",
        2025,
        "proceeds",
    )
    with pytest.raises(ValueError):
        validate_draft(
            ReviewDraft(blocks=[ReviewBlock(kind=kind, text=text, fact_ids=["f"])]), {"f": fact}
        )


@pytest.mark.parametrize(
    "text",
    [
        "Запросите данные, чтобы оценить финансовую устойчивость покупателя.",
        "Оценка не гарантирует финансовую устойчивость или рост бизнеса.",
    ],
)
def test_request_or_limit_is_not_mistaken_for_financial_diagnosis(text):
    fact = ApprovedFact(
        "f",
        GroundedClaim(text="Прибыль за 2025: -100 рублей.", evidence_ids=("e",)),
        "granular_metric",
        2025,
        "profit",
    )
    validate_draft(
        ReviewDraft(blocks=[ReviewBlock(kind="action", text=text, fact_ids=["f"])]), {"f": fact}
    )


def test_request_for_cause_still_requires_a_supported_trend():
    fact = ApprovedFact(
        "f", GroundedClaim(text="Выручка за 2025: 100 рублей.", evidence_ids=("e",)), "finance"
    )
    with pytest.raises(ValueError, match="динамика"):
        validate_draft(
            ReviewDraft(
                blocks=[
                    ReviewBlock(
                        kind="action", text="Уточните причины падения выручки.", fact_ids=["f"]
                    )
                ]
            ),
            {"f": fact},
        )


def test_assessment_boundary_is_not_a_report_quote():
    fact = ApprovedFact(
        "f",
        GroundedClaim(text="Оценка не гарантирует выполнение договора.", evidence_ids=("e",)),
        "bank_signal",
        metric="assessment_limits",
    )
    with pytest.raises(ValueError, match="не цитата"):
        validate_draft(
            ReviewDraft(
                blocks=[
                    ReviewBlock(
                        kind="interpretation",
                        text="Отчёт прямо указывает: оценка не гарантирует выполнение договора.",
                        fact_ids=["f"],
                    )
                ]
            ),
            {"f": fact},
        )
    validate_draft(
        ReviewDraft(blocks=[ReviewBlock(kind="limitation", text=fact.claim.text, fact_ids=["f"])]),
        {"f": fact},
    )


@pytest.mark.parametrize("question", ["Не задавай новых вопросов", "Продолжи без новых вопросов"])
def test_no_more_questions_is_an_explicit_general_check(question):
    deal = apply_deal(contractor(), DealPatch(general_check=True), question)
    assert deal.general_check and deal.advance == "аванс"


def test_bare_percentage_keeps_explicit_advance_meaning_from_user_quote():
    from counterparty_agent.ai.deal import deal_implication_facts, validate_deal

    deal = apply_deal(DealContext(), DealPatch(advance="50%"), "Ремонт помещения, аванс 50%")
    assert deal.advance == "аванс 50%"
    validate_deal(deal)
    assert "Вы планируете аванс" in deal_implication_facts(deal)[0].claim.text
    unrelated = apply_deal(DealContext(), DealPatch(advance="50%"), "Обсуждаем 50%")
    assert not deal_implication_facts(unrelated)


def test_split_payment_is_not_mistaken_for_full_postpayment():
    from counterparty_agent.ai.deal import deal_implication_facts

    payment = "аванс 50%, остальная оплата после приёмки"
    deal = apply_deal(DealContext(), DealPatch(advance=payment), payment)
    text = deal_implication_facts(deal)[0].claim.text
    assert "Вы планируете аванс" in text and "без аванса" not in text
    zero = apply_deal(deal, DealPatch(advance="аванс 0%"), "аванс 0%")
    assert "без аванса" in deal_implication_facts(zero)[0].claim.text


@pytest.mark.parametrize(
    "question",
    [
        "Но у компании зелёный статус. Разве этого недостаточно?",
        "Можно доверять компании с зелёной оценкой?",
        "Разве зелёный светофор не гарантирует выполнение сделки?",
    ],
)
def test_bank_sufficiency_is_not_replaced_by_missing_data(source, question):
    snapshot = april(source)
    deal = contractor()
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback(question, deal, catalog)
    assert draft is not None
    validate_draft(draft, catalog)
    text = "\n".join(block.text for block in draft.blocks)
    assert "недостаточно для подтверждения безопасности" in text
    assert "не гарантирует" in text
    assert "Сведения о лицензиях" not in text
    assert "аванс" in text
    assert any(
        catalog[key].metric == "assessment_limits"
        for block in draft.blocks
        for key in block.fact_ids
    )


def test_buyer_deferral_keeps_direction_term_and_does_not_diagnose_solvency(source):
    from counterparty_agent.ai.deal import (
        counterparty_role,
        deal_implication_facts,
        literal_deal_patch,
    )

    question = (
        "ООО «ТЕТРАДОМ» просит поставить товар с оплатой через 60 дней. "
        "Проверь ИНН 9714038662 и объясни, что важно именно для решения об отсрочке."
    )
    deal = apply_deal(DealContext(), literal_deal_patch(question), question)
    assert deal.advance == "оплатой через 60 дней" and deal.subject == "товар"
    assert counterparty_role(deal) == "buyer" and deal.deadline is None
    effect = deal_implication_facts(deal)[0]
    assert "неполучения оплаты" in effect.claim.text and "60 дней" in effect.claim.text
    assert deal.terms["role"].evidence_id in effect.claim.evidence_ids
    snapshot = source.get_snapshot(source.find_by_inn("9714038662").candidates[0].snapshot_id)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback(question, deal, catalog)
    assert draft is not None
    validate_draft(draft, catalog)
    text = "\n".join(block.text for block in draft.blocks)
    assert "60 дней" in text and "не доказательство" in text
    assert "сумма поставки" in text
    assert "критерии приёмки" not in text and "какие разрешения" not in text
    changed = apply_deal(deal, DealPatch(advance="отсрочка 30 дней"), "Теперь отсрочка 30 дней")
    effect = deal_implication_facts(changed)[0]
    assert "30 дней" in effect.claim.text and "60 дней" not in effect.claim.text
    assert "неполучения оплаты" in effect.claim.text
    with pytest.raises(ValueError, match="роль пользователя"):
        apply_deal(changed, DealPatch(role="продавца"), "Что меняется для нас как продавца?")


@pytest.mark.parametrize(
    "question",
    [
        "Если будет аванс 50%, проверь компанию",
        "В договоре указан аванс 50%. Проверь компанию",
        "А если покупатель просит поставить товар с оплатой через 60 дней?",
    ],
)
def test_literal_recovery_does_not_save_hypotheses_or_document_terms(question):
    from counterparty_agent.ai.deal import literal_deal_patch

    assert literal_deal_patch(question) == DealPatch()


def test_literal_recovery_skips_user_role_without_losing_payment():
    from counterparty_agent.ai.deal import literal_deal_patch

    patch = literal_deal_patch(
        "Мы как поставщик согласуем отсрочку 30 дней. Проверь ИНН 9714038662."
    )
    assert patch.role is None
    assert patch.advance == "отсрочку 30 дней"


def test_experience_question_has_specific_boundary_and_next_step(source):
    snapshot = april(source)
    deal = contractor()
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback(
        "Подтверждён ли опыт ремонта? Каких подтверждений не хватает?", deal, catalog
    )
    assert draft is not None
    validate_draft(draft, catalog)
    text = "\n".join(block.text for block in draft.blocks)
    assert "не подтверждает опыт" in text
    assert "нельзя заключить, что у компании нет опыта" in text
    assert "примеры похожих выполненных проектов" in text
    assert "итог активов" not in text and "Вы планируете аванс" not in text


def test_fallback_handles_every_real_company_and_six_member_groups(source):
    for offset in range(len(source.snapshots)):
        snapshots = source.snapshots[offset : offset + (6 if offset % 2 else 1)]
        analyses = tuple(analyze_snapshot(s, evaluated_at=s.report_at) for s in snapshots)
        catalog, _ = review_catalog(snapshots, analyses, contractor())
        draft = safe_analysis_fallback("Сравни обстоятельства для сделки", contractor(), catalog)
        assert draft is not None and len(draft.blocks) <= 8
        validate_draft(draft, catalog)
        cited = {key for block in draft.blocks for key in block.fact_ids}
        for snapshot in snapshots:
            assert any(snapshot.identity.inn in catalog[key].claim.text for key in cited)


def test_postpayment_and_known_work_are_not_replaced_by_supplier_template(source):
    snapshot = april(source)
    deal = apply_deal(
        contractor(),
        DealPatch(subject="ремонт помещения", amount="300000 рублей", advance="без аванса"),
        "ремонт помещения, 300000 рублей, без аванса",
    )
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback("Что изменилось при постоплате?", deal, catalog)
    assert draft is not None
    validate_draft(draft, catalog)
    text = "\n".join(block.text for block in draft.blocks)
    assert "Вы планируете аванс" not in text and "без аванса" in text
    assert "Какие товары" not in text and "Какова сумма" not in text
    assert "приёмки работ" in text


def test_historical_loss_keeps_later_profit_even_in_fallback():
    def fact(key, text, topic, period, metric):
        return ApprovedFact(
            key, GroundedClaim(text=text, evidence_ids=(key,)), topic, period, metric
        )

    catalog = {
        "loss": fact(
            "loss", "Убыток за 2023: -10 рублей", "attention_signal", 2023, "financial_loss"
        ),
        "profit": fact("profit", "Прибыль за 2025: 40 рублей", "granular_metric", 2025, "profit"),
    }
    assert select_issues(list(catalog), catalog, 1) == ["loss", "profit"]


async def test_reading_source_flags_opens_their_details_and_fallback_remains_grounded(
    source,
    monkeypatch,
):
    from pydantic import SecretStr

    from counterparty_agent.ai.reasoning import ReviewDecision

    model = ReviewModel(
        monkeypatch,
        decide=lambda data: (
            ReviewDecision(action="read", topics=["reputation", "finance"])
            if not data["read_topics"]
            else ReviewDecision(action="finish")
        ),
        draft=lambda data: ReviewDraft(
            blocks=[ReviewBlock(kind="fact", text="Выдуманное", fact_ids=["bad"])]
        ),
        verdict=GroundingVerdict(unsupported_blocks=[], answers_question=True),
    )
    snapshot = april(source)
    run = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        "На что обратить внимание?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        contractor(),
        client=object(),
    )
    assert run.answer.status == "answered"
    assert {"Проверено: суды", "Проверено: взыскания"} <= set(run.steps)
    assert "Выдуманное" not in run.answer.answer
    assert not run.answer.answer.startswith(("Факт:", "Вывод:"))
    assert model.inputs(ReviewDecision)[0]["attention_topics"]
    validate_review_run(run)


async def test_repeated_read_finishes_on_existing_facts_instead_of_losing_answer(
    source, monkeypatch
):
    from pydantic import SecretStr

    from counterparty_agent.ai.reasoning import ReviewDecision

    model = ReviewModel(
        monkeypatch, decide=lambda data: ReviewDecision(action="read", topics=["finance"])
    )
    snapshot = april(source)
    run = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        "Что известно о финансах?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        contractor(),
        client=object(),
    )
    assert run.answer.status == "answered"
    assert run.steps.count("Проверено: финансы") == 1
    assert len(model.inputs(ReviewDecision)) == 2
    validate_review_run(run)


async def test_partial_failure_keeps_verified_paragraph_after_one_repair(source, monkeypatch):
    from pydantic import SecretStr

    from counterparty_agent.ai.reasoning import synthesize

    snapshot = april(source)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )

    def draft(data):
        fact = next(f for f in data["approved_facts"] if f["topic"] == "company_status")
        return ReviewDraft(
            blocks=[
                ReviewBlock(kind="fact", text=fact["text"], fact_ids=[fact["fact_id"]]),
                ReviewBlock(
                    kind="interpretation",
                    text="Этот отчёт гарантирует исполнение договора.",
                    fact_ids=[fact["fact_id"]],
                ),
            ]
        )

    model = ReviewModel(
        monkeypatch,
        draft=draft,
        verdict=lambda data: GroundingVerdict(
            unsupported_blocks=[
                b["index"] for b in data["blocks"] if "гарантирует исполнение" in b["text"]
            ],
            answers_question=True,
        ),
    )
    answer, verified = await synthesize(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        object(),
        "Проверь компанию",
        contractor(),
        catalog,
        "Проверены разделы отчёта",
    )
    assert len(model.inputs(ReviewDraft)) == 2
    assert len(verified.blocks) == 2
    assert verified.blocks[0].text == next(
        f.claim.text for f in catalog.values() if f.topic == "company_status"
    )
    assert "гарантирует исполнение" not in answer.answer
    validate_draft(verified, catalog)


async def test_numeric_error_replaces_only_bad_paragraph_then_verifies_entire_answer(
    source, monkeypatch
):
    from pydantic import SecretStr

    from counterparty_agent.ai.reasoning import synthesize

    snapshot = april(source)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )

    def draft(data):
        status = next(f for f in data["approved_facts"] if f["topic"] == "company_status")
        payment = next(f for f in data["approved_facts"] if f["metric"] == "payment_effect")
        return ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind="fact",
                    text="У компании 12345678 судебных дел.",
                    fact_ids=[status["fact_id"]],
                ),
                ReviewBlock(kind="action", text=payment["text"], fact_ids=[payment["fact_id"]]),
            ]
        )

    model = ReviewModel(monkeypatch, draft=draft)
    answer, verified = await synthesize(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        object(),
        "Что учесть до оплаты?",
        contractor(),
        catalog,
        "Проверенные разделы",
    )
    assert len(model.inputs(ReviewDraft)) == 2
    assert len(model.inputs(GroundingVerdict)) == 1
    checked = model.inputs(GroundingVerdict)[0]
    assert len(verified.blocks) == len(checked["blocks"]) == 2
    assert "12345678" not in answer.answer
    assert verified.blocks[1].text == next(
        f.claim.text for f in catalog.values() if f.metric == "payment_effect"
    )
    validate_draft(verified, catalog)
