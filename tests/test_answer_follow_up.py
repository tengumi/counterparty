"""Уточнение дополняет проверенный ответ и не превращается в повторную анкету."""

from __future__ import annotations

import pytest
from test_review_agent import ReviewModel, purpose
from test_review_agent import settings as review_settings
from test_review_agent import source as real_source

from counterparty_agent.ai.briefing import safe_analysis_fallback
from counterparty_agent.ai.contracts import ReviewBlock, ReviewDraft
from counterparty_agent.ai.deal import DealContext, DealPatch, apply_deal
from counterparty_agent.ai.follow_up import QUESTIONS, allowed_follow_ups, prepare_follow_up
from counterparty_agent.ai.reasoning import GroundingVerdict, validate_draft
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.workflow.review import review_catalog, run_review, validate_review_run

source = real_source
settings = review_settings


def sample_draft(field="subject"):
    return ReviewDraft(
        blocks=[ReviewBlock(kind="action", text="Уточните текущие показатели.", fact_ids=["f"])],
        follow_up_field=field,
    )


def test_question_preparation_is_immutable_and_idempotent():
    original = sample_draft()
    prepared = prepare_follow_up(original, purpose())
    assert original.blocks[0].text == "Уточните текущие показатели."
    assert prepared.blocks[0].text.endswith(QUESTIONS["subject"])
    assert prepared == prepare_follow_up(prepared, purpose())
    assert prepared.blocks[0].fact_ids == ["f"]


@pytest.mark.parametrize("state", ["known", "asked", "budget", "general"])
def test_known_questions_and_question_budget_are_enforced(state):
    deal = purpose()
    if state == "known":
        deal = apply_deal(deal, DealPatch(subject="ремонт"), "Нужен ремонт")
    elif state == "asked":
        deal.asked_fields = ["subject"]
    elif state == "budget":
        deal.asked_fields = ["goal", "amount"]
    else:
        deal.general_check = True
    with pytest.raises(ValueError, match="уточнение"):
        prepare_follow_up(sample_draft(), deal)


def test_inferred_role_and_known_payment_do_not_trigger_redundant_purpose_question():
    deal = apply_deal(
        DealContext(),
        DealPatch(goal="выбираю поставщика", advance="40% предоплаты"),
        "Я выбираю поставщика, 40% предоплаты",
    )
    assert "role" not in allowed_follow_ups(deal)
    assert "goal" not in allowed_follow_ups(deal)


@pytest.mark.parametrize("full", ["blocks", "text"])
def test_optional_question_never_displaces_evidence_at_output_limit(full):
    original = ReviewDraft(
        blocks=[ReviewBlock(kind="fact", text="Факт отчёта.", fact_ids=["f"])] * 8
        if full == "blocks"
        else [ReviewBlock(kind="action", text="А" * 1090, fact_ids=["f"])],
        follow_up_field="subject",
    )
    prepared = prepare_follow_up(original, purpose())
    assert prepared.blocks == original.blocks
    assert prepared.follow_up_field is None


async def test_answer_then_question_is_verified_saved_and_not_repeated(
    source, settings, monkeypatch
):
    snapshot = source.get_snapshot(source.find_by_inn("9714038662").candidates[0].snapshot_id)
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)

    def draft(data):
        fact = next(f for f in data["approved_facts"] if f["topic"] == "company_status")
        return ReviewDraft(
            blocks=[ReviewBlock(kind="fact", text=fact["text"], fact_ids=[fact["fact_id"]])],
            follow_up_field="subject" if "subject" in data["allowed_follow_up_fields"] else None,
        )

    model = ReviewModel(monkeypatch, draft=draft)
    first = await run_review(
        settings,
        "Что проверить перед авансом?",
        (snapshot,),
        (analysis,),
        purpose(),
        client=object(),
    )
    validate_review_run(first)
    assert first.answer.status == "answered"
    assert first.deal.asked_fields == ["subject"]
    assert first.deal.question == QUESTIONS["subject"]
    assert first.answer.answer.endswith(first.deal.question)
    assert model.inputs(GroundingVerdict)[0]["blocks"][-1]["text"] == first.deal.question
    second = await run_review(
        settings, "Пока продолжим", (snapshot,), (analysis,), first.deal, client=object()
    )
    assert second.answer.status == "answered"
    assert second.deal.asked_fields == ["subject"]
    assert second.deal.question is None
    assert QUESTIONS["subject"] not in second.answer.answer
    validate_review_run(second)


@pytest.mark.parametrize(
    "question",
    [
        "Почему зелёный статус?",
        "Отрицательный капитал означает банкротство?",
        "Каких данных не хватает?",
    ],
)
def test_narrow_fallback_does_not_ask_for_unrelated_deal_parameters(source, question):
    snapshot = source.get_snapshot(source.find_by_inn("9714038662").candidates[0].snapshot_id)
    deal = purpose("40% предоплаты")
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback(question, deal, catalog)
    assert draft is not None and draft.follow_up_field is None
    validate_draft(draft, catalog)


def test_fallback_keeps_precise_advance_readable_loss_and_prioritized_actions(source):
    snapshot = source.get_snapshot(source.find_by_inn("9714038662").candidates[0].snapshot_id)
    deal = purpose("40% предоплаты")
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback("Что учесть до оплаты?", deal, catalog)
    assert draft is not None
    validate_draft(draft, catalog)
    text = "\n\n".join(block.text for block in draft.blocks)
    assert "40% предоплаты" in text
    assert "Убыток за 2025: 28\u202f568\u202f000 рублей" in text
    assert "-29\u202f564\u202f000" in text
    assert "прибыль: -" not in text
    assert "Сначала запросите актуальную отчётность" in text
    assert "Без предмета сделки нельзя" not in text
    assert draft.follow_up_field == "subject"
    assert text.count("?") == 1


def test_fallback_current_amount_keeps_source_and_does_not_compute_advance(source):
    snapshot = source.get_snapshot(source.find_by_inn("9714038662").candidates[0].snapshot_id)
    deal = apply_deal(
        purpose("40% предоплаты"), DealPatch(amount="2 млн рублей"), "Сумма 2 млн рублей"
    )
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), deal
    )
    draft = safe_analysis_fallback("Что учесть до оплаты?", deal, catalog)
    assert draft is not None
    validate_draft(draft, catalog)
    assert "2 млн рублей" in draft.blocks[0].text
    assert any(catalog[key].metric == "amount" for key in draft.blocks[0].fact_ids)
    assert "800" not in draft.blocks[0].text


async def test_planner_does_not_reask_role_inferred_from_goal(source, settings, monkeypatch):
    from counterparty_agent.ai.reasoning import ReviewDecision

    snapshot = source.get_snapshot(source.find_by_inn("9714038662").candidates[0].snapshot_id)
    deal = apply_deal(DealContext(), DealPatch(goal="выбираю поставщика"), "выбираю поставщика")

    def decide(data):
        assert "role" not in data["missing_fields"]
        return (
            ReviewDecision(action="finish")
            if data["read_topics"]
            else ReviewDecision(action="read", topics=["finance"])
        )

    ReviewModel(monkeypatch, decide=decide)
    run = await run_review(
        settings,
        "Что проверить?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        deal,
        client=object(),
    )
    assert run.answer.status == "answered"
    assert "role" not in run.deal.asked_fields


@pytest.mark.parametrize(
    "question", ["Кого выбрать из этих поставщиков?", "Кого проверить особенно внимательно?"]
)
def test_six_companies_keep_their_evidence_when_optional_question_does_not_fit(source, question):
    inns = ("1684017097", "7813664770", "9714038662", "8622002583", "5029069967", "9705152496")
    snapshots = tuple(
        source.get_snapshot(source.find_by_inn(inn).candidates[0].snapshot_id) for inn in inns
    )
    deal = purpose("40% предоплаты")
    catalog, _ = review_catalog(
        snapshots, tuple(analyze_snapshot(s, evaluated_at=s.report_at) for s in snapshots), deal
    )
    draft = safe_analysis_fallback(question, deal, catalog)
    assert draft is not None and len(draft.blocks) <= 8
    validate_draft(draft, catalog)
    for inn in inns:
        assert any(
            inn in catalog[key].claim.text for block in draft.blocks for key in block.fact_ids
        )


def test_comparison_actions_follow_stated_priority_not_company_order(source):
    inns = ("1684017097", "7813664770", "8622002583")
    snapshots = tuple(
        source.get_snapshot(source.find_by_inn(inn).candidates[0].snapshot_id) for inn in inns
    )
    deal = purpose()
    catalog, _ = review_catalog(
        snapshots, tuple(analyze_snapshot(s, evaluated_at=s.report_at) for s in snapshots), deal
    )
    draft = safe_analysis_fallback("Кого проверить особенно внимательно?", deal, catalog)
    assert draft is not None
    validate_draft(draft, catalog)
    action = next(block for block in draft.blocks if block.kind == "action")
    assert action.text.startswith(
        "Сначала запросите подтверждение текущего состояния исполнительных производств"
    )
