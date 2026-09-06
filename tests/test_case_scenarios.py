"""Регрессии сценариев пользователя; ожидания сверены с подключённым JSON, не с LLM-файлом."""

from decimal import Decimal

import pytest
from test_analysis import source as real_source

from counterparty_agent.ai.briefing import company_rows, safe_analysis_fallback
from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.comparison_catalog import build_enforcement_focus
from counterparty_agent.ai.contracts import ReviewBlock, ReviewDraft
from counterparty_agent.ai.deal import DealContext, DealPatch, apply_deal
from counterparty_agent.ai.reasoning import validate_draft
from counterparty_agent.ai.router import IntentPlan
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.config import Settings
from counterparty_agent.workflow.review import ReviewContext, _topic_queue, review_catalog
from counterparty_agent.workflow.semantic import _target_plan

source = real_source


def company(source, inn):
    candidates = source.find_by_inn(inn).candidates
    if len(candidates) != 1:
        pytest.skip("Отчёт сценария не подключён")
    return source.get_snapshot(candidates[0].snapshot_id)


@pytest.mark.parametrize("question,year", [("Сравни компании", 2025), ("Выручка за 2024", 2024)])
def test_finance_reading_prioritizes_latest_or_requested_year(source, question, year):
    snapshots = [company(source, inn) for inn in ("1684017097", "7813664770")]
    deal = DealContext()
    facts, topics = review_catalog(
        snapshots, [analyze_snapshot(s, evaluated_at=s.report_at) for s in snapshots], deal
    )
    context = ReviewContext(
        settings=Settings(_env_file=None),
        client=None,
        question=question,
        deal=deal,
        catalog=facts,
        topics=topics,
    )
    revenue = [fact for _, fact in _topic_queue(context, "finance") if fact.metric == "proceeds"]
    assert [f.period for f in revenue[:2]] == [year, year]
    assert "1684017097" in revenue[0].claim.text and "7813664770" in revenue[1].claim.text


@pytest.mark.parametrize(
    "inn,active,known,amount",
    [("8622002583", 28, 24, "31650625.18"), ("5029069967", 45, 12, "1571230.52")],
)
def test_known_enforcement_sum_is_explicitly_partial(source, inn, active, known, amount):
    snapshot = company(source, inn)
    records = [r for r in snapshot.enforcement_proceedings if r.is_active]
    amounts = [r.amount for r in records if r.amount is not None]
    assert len(records) == active and len(amounts) == known
    assert sum(amounts, Decimal(0)) == Decimal(amount)
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    summary = next(f for f in analysis.findings if f.code == "enforcement_summary")
    assert f"Сумма указана у {known} из {active}" in summary.statement
    assert f"без суммы: {active - known}" in summary.statement
    boundary = next(f for f in analysis.findings if f.code == "debt_total_unavailable")
    assert "нельзя складывать" in boundary.statement


def test_samza_full_legal_name_is_not_reduced_to_inner_quoted_word(source):
    company(source, "8622002583")
    question = (
        "Мы хотим перечислить существенный аванс ООО ЛПК «САМЗА», ИНН 8622002583. "
        "Назови три главных основания для дополнительной проверки."
    )
    plan = _target_plan(IntentPlan(action="ask", targets=("8622002583",)), question, source)
    assert len(plan.mentions) == 1
    with pytest.raises(ValueError):
        _target_plan(
            IntentPlan(action="ask", targets=("8622002583",)),
            question.replace("САМЗА", "ДРУГАЯ КОМПАНИЯ"),
            source,
        )


def test_zero_revenue_signal_uses_only_latest_completed_year(source):
    for inn, expected in (("7813664770", True), ("1684017097", False)):
        snapshot = company(source, inn)
        facts = build_fact_catalog(
            snapshot, analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
        )
        zeros = [f for f in facts if f.metric == "financial_zero_revenue"]
        assert bool(zeros) is expected
        if zeros:
            assert zeros[0].period == 2025 and "не доказывает прекращение" in zeros[0].claim.text


def test_first_check_question_gets_a_priority_instead_of_general_digest(source):
    snapshot = company(source, "7813664770")
    deal = apply_deal(
        DealContext(), DealPatch(role="подрядчик", advance="аванс"), "Подрядчик, аванс"
    )
    facts, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback(
        "Какой факт здесь важнее всего для решения об авансе?", deal, facts
    )
    assert draft is not None
    validate_draft(draft, facts)
    assert "первоочередной проверки" in draft.blocks[0].text
    assert any(facts[k].metric == "financial_zero_revenue" for k in draft.blocks[0].fact_ids)
    assert "доказательство срыва" in draft.blocks[0].text


def test_loss_magnitude_has_separate_fact_and_original_profit_stays_negative(source):
    snapshot = company(source, "9714038662")
    facts = build_fact_catalog(
        snapshot, analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    )
    for statement in snapshot.financial_statements:
        if statement.profit is None or statement.profit >= 0:
            continue
        loss = next(f for f in facts if f.metric == "loss_amount" and f.period == statement.year)
        profit = next(f for f in facts if f.metric == "profit" and f.period == statement.year)
        assert loss.claim.evidence_ids == profit.claim.evidence_ids
        assert "не положительная прибыль" in loss.claim.text
        assert "-" not in loss.claim.text
        assert "-" in profit.claim.text


def test_buyer_brief_keeps_both_loss_and_equity(source):
    snapshot = company(source, "9714038662")
    deal = apply_deal(
        DealContext(),
        DealPatch(role="покупатель", advance="отсрочка 60 дней"),
        "Наш покупатель, отсрочка 60 дней",
    )
    facts, _ = review_catalog(
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        deal,
    )
    draft = safe_analysis_fallback("Что важно для отсрочки?", deal, facts)
    assert draft is not None
    validate_draft(draft, facts)
    used = {facts[k].metric for b in draft.blocks for k in b.fact_ids}
    assert {"negative_equity", "financial_loss"} <= used


@pytest.mark.parametrize("inn", ["8622002583", "5029069967"])
def test_total_debt_fallback_answers_the_question_and_keeps_missing_sums(source, inn):
    snapshot = company(source, inn)
    deal = apply_deal(DealContext(), DealPatch(role="поставщик"), "Новый поставщик")
    facts, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback(
        "Это полная сумма долга? Можно ли сложить арбитраж и исполнительные производства?",
        deal,
        facts,
    )
    assert draft is not None
    validate_draft(draft, facts)
    text = "\n".join(b.text for b in draft.blocks)
    assert "нельзя складывать" in text and "без суммы:" in text
    assert "Сумма указана у" in text


def test_revenue_does_not_answer_profitability_when_profit_is_missing(source):
    snapshot = company(source, "1684017097")
    deal = apply_deal(DealContext(), DealPatch(role="подрядчик"), "Новый подрядчик")
    facts, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback("Рост выручки означает, что компания прибыльна?", deal, facts)
    assert draft is not None
    validate_draft(draft, facts)
    text = "\n".join(b.text for b in draft.blocks)
    assert "Выручка не равна прибыли" in text and "2025" in text
    assert "лицензи" not in text and "суд" not in text


def test_quick_check_does_not_hide_no_signals_and_latest_revenue_behind_gaps(source):
    snapshot = company(source, "1684017097")
    deal = apply_deal(DealContext(), DealPatch(role="подрядчик"), "Новый подрядчик")
    facts, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback("Нужна быстрая проверка без лишней перестраховки", deal, facts)
    assert draft is not None
    validate_draft(draft, facts)
    selected = [facts[k] for b in draft.blocks for k in b.fact_ids]
    assert any(f.metric == "none" for f in selected)
    assert any(f.metric == "proceeds" and f.period == 2025 for f in selected)
    assert not any(f.topic == "license_coverage" for f in selected)


def test_winner_question_gets_explicit_limit_not_automatic_ranking(source):
    snapshots = [company(source, inn) for inn in ("1684017097", "7813664770", "8622002583")]
    deal = apply_deal(DealContext(), DealPatch(role="исполнители"), "Нужны исполнители")
    facts, _ = review_catalog(
        snapshots,
        [analyze_snapshot(s, evaluated_at=s.report_at) for s in snapshots],
        deal,
    )
    draft = safe_analysis_fallback("Кого считаешь победителем сравнения?", deal, facts)
    assert draft is not None
    validate_draft(draft, facts)
    assert "нельзя обоснованно назвать победителя" in draft.blocks[0].text


def test_comparison_priority_is_only_an_explicit_count_criterion(source):
    snapshots = [company(source, inn) for inn in ("1684017097", "7813664770", "8622002583")]
    analyses = [analyze_snapshot(s, evaluated_at=s.report_at) for s in snapshots]
    contrast = build_enforcement_focus(snapshots, analyses)
    assert contrast is not None
    assert "8622002583): 28" in contrast.claim.text
    assert "не вероятность неоплаты" in contrast.claim.text
    assert not build_enforcement_focus([snapshots[0], snapshots[0]], [analyses[0], analyses[0]])
    assert not build_enforcement_focus(snapshots * 3, analyses * 3)
    deal = apply_deal(DealContext(), DealPatch(advance="аванс"), "Аванс")
    facts, _ = review_catalog(snapshots, analyses, deal)
    assert contrast.fact_id not in {key for row in company_rows(facts).values() for key in row}
    draft = safe_analysis_fallback("Кого нужно проверить особенно внимательно?", deal, facts)
    assert draft is not None
    validate_draft(draft, facts)
    assert "первоочередной проверки взысканий" in draft.blocks[0].text


def test_missing_fields_do_not_prove_increased_default_probability(source):
    snapshot = company(source, "5029069967")
    facts = build_fact_catalog(
        snapshot, analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    )
    missing = next(f for f in facts if f.topic in {"financial_missing", "financial_empty"})
    with pytest.raises(ValueError, match="уровень риска"):
        validate_draft(
            ReviewDraft(
                blocks=[
                    ReviewBlock(
                        kind="interpretation",
                        text="Отсутствие финансовых данных повышает риск невозврата аванса.",
                        fact_ids=[missing.fact_id],
                    )
                ]
            ),
            {missing.fact_id: missing},
        )


def test_generic_profit_cannot_be_renamed_to_operating_profit(source):
    snapshot = company(source, "9714038662")
    facts = build_fact_catalog(
        snapshot, analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    )
    profit = next(f for f in facts if f.metric == "profit" and f.period == 2025)
    with pytest.raises(ValueError, match="вид прибыли"):
        validate_draft(
            ReviewDraft(
                blocks=[
                    ReviewBlock(
                        kind="action",
                        text="Уточните источник средств, так как операционная прибыль отсутствует.",
                        fact_ids=[profit.fact_id],
                    )
                ]
            ),
            {profit.fact_id: profit},
        )


def test_negative_capital_question_gets_a_status_boundary(source):
    snapshot = company(source, "9714038662")
    deal = apply_deal(DealContext(), DealPatch(role="покупатель"), "Наш покупатель")
    facts, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback(
        "Отрицательный капитал означает, что компания банкрот?", deal, facts
    )
    assert draft is not None
    validate_draft(draft, facts)
    assert "сам по себе не подтверждает банкротство" in draft.blocks[0].text
    assert "массовость" not in " ".join(b.text for b in draft.blocks)


@pytest.mark.parametrize(
    "text",
    [
        "Отрицательный капитал означает, что обязательства превышают активы.",
        "Юридический статус банкрота устанавливает только суд.",
    ],
)
def test_capital_boundary_does_not_support_external_definitions(source, text):
    snapshot = company(source, "9714038662")
    facts = build_fact_catalog(
        snapshot, analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    )
    boundary = next(f for f in facts if f.metric == "capital_status_boundary")
    with pytest.raises(ValueError, match="юридическое правило"):
        validate_draft(
            ReviewDraft(
                blocks=[ReviewBlock(kind="interpretation", text=text, fact_ids=[boundary.fact_id])]
            ),
            {boundary.fact_id: boundary},
        )


@pytest.mark.parametrize(
    "text",
    [
        "Финансы компании нестабильны.",
        "Без этих данных отгрузка в долг крайне рискованна.",
        "При отсутствии отчётности риск невозврата предоплаты повышен.",
        "Эти обстоятельства указывают на возможные проблемы с исполнением обязательств.",
    ],
)
def test_financial_circumstances_are_not_an_unsupported_diagnosis(source, text):
    snapshot = company(source, "9714038662")
    facts = build_fact_catalog(
        snapshot, analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    )
    loss = next(f for f in facts if f.metric == "financial_loss")
    with pytest.raises(ValueError):
        validate_draft(
            ReviewDraft(
                blocks=[ReviewBlock(kind="interpretation", text=text, fact_ids=[loss.fact_id])]
            ),
            {loss.fact_id: loss},
        )


@pytest.mark.parametrize(
    "text",
    [
        "Зафиксировано резкое снижение выручки.",
        "Компания не зафиксировала продаж.",
        "Запросите пояснение об отсутствии продаж.",
    ],
)
def test_zero_revenue_alone_does_not_prove_trend_or_no_sales(source, text):
    snapshot = company(source, "7813664770")
    facts = build_fact_catalog(
        snapshot, analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    )
    zero = next(f for f in facts if f.metric == "financial_zero_revenue")
    with pytest.raises(ValueError):
        validate_draft(
            ReviewDraft(
                blocks=[ReviewBlock(kind="interpretation", text=text, fact_ids=[zero.fact_id])]
            ),
            {zero.fact_id: zero},
        )
