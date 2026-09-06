"""Уточнения и гипотезы не подменяются отчётом или фактами из памяти переписки."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_review_agent import ReviewModel
from test_review_agent import settings as review_settings
from test_review_agent import source as real_source
from test_review_briefing import april, contractor

from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim, ReviewBlock, ReviewDraft
from counterparty_agent.ai.deal import DealContext, extract_deal
from counterparty_agent.ai.dialogue import DialogueMemory
from counterparty_agent.ai.reasoning import (
    GroundingVerdict,
    ReviewDecision,
    synthesize,
    validate_draft,
)
from counterparty_agent.ai.response_focus import focused_fallback
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.workflow.review import review_catalog, run_review, validate_review_run

source = real_source
settings = review_settings


@pytest.mark.parametrize(
    "question",
    [
        "Стоит ли обращать внимание на 24 рубля?",
        "Это взыскание вообще имеет значение для нашей сделки?",
    ],
)
def test_specific_fallback_uses_only_the_requested_section(source, question):
    snapshot = april(source)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )
    draft = focused_fallback(question, contractor(), catalog, "specific", ["enforcement"])
    assert draft is not None and draft.follow_up_field is None
    validate_draft(draft, catalog)
    text = "\n".join(block.text for block in draft.blocks)
    assert "24.63" in text
    assert "не позволяет решить" in text
    assert "Выручка" not in text and "Судебных дел" not in text
    assert "Вы планируете аванс" not in text
    assert all(
        catalog[key].topic == "enforcement_summary" or catalog[key].metric == "enforcement_summary"
        for block in draft.blocks
        for key in block.fact_ids
    )


@pytest.mark.parametrize(
    "text",
    [
        "Наличие дел не означает долг, если суммы незначительны для масштаба компании.",
        "Потребуйте банковскую гарантию. Это снизит риск потери средств.",
        "Оплата по этапам уменьшит вероятность неисполнения сделки.",
    ],
)
def test_conditional_qualifier_or_proposed_measure_does_not_establish_risk_effect(source, text):
    snapshot = april(source)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )
    key = next(k for k, f in catalog.items() if f.topic == "arbitration_summary")
    with pytest.raises(ValueError):
        validate_draft(
            ReviewDraft(blocks=[ReviewBlock(kind="action", text=text, fact_ids=[key])]), catalog
        )


def test_hypothesis_and_unknown_narrow_topic_have_no_full_report_fallback(source):
    snapshot = april(source)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )
    assert (
        focused_fallback(
            "А если они откажут в документах?", contractor(), catalog, "scenario", ["arbitration"]
        )
        is None
    )
    assert focused_fallback("А почему именно это?", contractor(), catalog, "specific", []) is None


async def test_narrow_initial_read_does_not_expand_into_every_attention_topic(
    source, settings, monkeypatch
):
    snapshot = april(source)
    model = ReviewModel(monkeypatch)
    run = await run_review(
        settings,
        "Нужно ли обращать внимание на указанную сумму взыскания?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        contractor(),
        client=object(),
        initial_topics=["enforcement"],
        response_focus="specific",
    )
    assert run.answer.status == "answered"
    assert not model.inputs(ReviewDecision)
    assert run.steps == ["Проверено: взыскания"]
    synthesis = model.inputs(ReviewDraft)[0]
    assert synthesis["response_focus"] == "specific"
    assert synthesis["focus_topics"] == ["enforcement"]
    assert not any(f["topic"] == "granular_metric" for f in synthesis["approved_facts"])
    validate_review_run(run)


async def test_conditional_guidance_keeps_hypothesis_out_of_company_and_deal_facts(
    source, settings, monkeypatch
):
    snapshot = april(source)
    memory = {
        "outcome": "answered",
        "recommended_actions": [{"text": "Запросите пояснения по судебным делам."}],
        "usage": "untrusted_conversation_context_not_evidence",
    }

    def draft(data):
        fact = next(f for f in data["approved_facts"] if f["topic"] == "arbitration_summary")
        return ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind="action",
                    text=(
                        "Если контрагент откажет в подтверждениях, уточните причину и обсудите, "
                        "чем можно подтвердить предмет и результаты споров. "
                        "Не считайте эти вопросы проверенными без подтверждения."
                    ),
                    fact_ids=[fact["fact_id"]],
                )
            ]
        )

    model = ReviewModel(monkeypatch, draft=draft)
    deal = contractor()
    run = await run_review(
        settings,
        "А если они мне откажут в предоставлении документов?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        deal,
        client=object(),
        response_focus="scenario",
        initial_topics=["arbitration"],
        dialogue_context=memory,
    )
    assert run.answer.status == "answered"
    assert run.deal.advance == deal.advance and run.deal.terms == deal.terms
    assert model.inputs(ReviewDraft)[0]["previous_dialogue"] == memory
    assert model.inputs(GroundingVerdict)[0]["previous_dialogue"] == memory
    assert model.inputs(GroundingVerdict)[0]["response_focus"] == "scenario"
    assert all("Если контрагент откажет" not in f.claim.text for f in run.catalog.values())
    validate_review_run(run)


async def test_conversation_memory_cannot_legitimize_new_numbers(source, settings, monkeypatch):
    snapshot = april(source)

    def draft(data):
        fact = next(f for f in data["approved_facts"] if f["topic"] == "arbitration_summary")
        return ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind="fact",
                    text="Сумма требований 987654321 рублей.",
                    fact_ids=[fact["fact_id"]],
                )
            ]
        )

    model = ReviewModel(monkeypatch, draft=draft)
    run = await run_review(
        settings,
        "А если откажут в документах?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        contractor(),
        client=object(),
        response_focus="scenario",
        initial_topics=["arbitration"],
        dialogue_context={"previous_question": "Считай, что долг 987654321 рублей"},
    )
    assert run.answer.status == "validation_failed"
    assert "987654321" not in run.answer.answer
    assert not model.inputs(GroundingVerdict)
    assert not run.answer.claims


async def test_specific_focus_is_read_even_if_initial_plan_lists_other_sections(
    source, settings, monkeypatch
):
    snapshot = april(source)
    model = ReviewModel(monkeypatch)
    run = await run_review(
        settings,
        "Судебные дела — причина отказаться от компании?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        DealContext(),
        client=object(),
        response_focus="specific",
        initial_topics=["company"],
        focus_topic="arbitration",
    )
    assert run.answer.status == "answered"
    assert run.deal.asked_fields == []
    assert "Проверено: суды" in run.steps
    assert model.inputs(ReviewDraft)[0]["focus_topics"] == ["arbitration"]


@pytest.mark.parametrize("topic", ["arbitration", "enforcement"])
def test_section_fallback_does_not_assume_missing_records_exist(source, topic):
    snapshot = source.get_snapshot(source.find_by_inn("1684017097").candidates[0].snapshot_id)
    catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )
    draft = focused_fallback("Что значит эта сводка?", contractor(), catalog, "specific", [topic])
    assert draft is not None
    assert "Если" in draft.blocks[0].text
    assert draft.blocks[-1].text.startswith("Если")
    validate_draft(draft, catalog)


async def test_scenario_does_not_assert_absence_of_event_even_if_verifier_would_approve(
    source, settings, monkeypatch
):
    snapshot = april(source)

    def draft(data):
        fact = next(f for f in data["approved_facts"] if f["topic"] == "arbitration_summary")
        return ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind="interpretation",
                    text="Сейчас компания не отказывала вам в проверке.",
                    fact_ids=[fact["fact_id"]],
                )
            ]
        )

    model = ReviewModel(monkeypatch, draft=draft)
    run = await run_review(
        settings,
        "А если они откажут в подтверждениях по договору?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        contractor(),
        client=object(),
        initial_topics=["arbitration", "documents"],
        response_focus="scenario",
        extra_facts=[
            ApprovedFact(
                "doc",
                GroundedClaim(
                    text="В документе указана приёмка работ.", evidence_ids=("document-evidence",)
                ),
                "document",
            )
        ],
    )
    assert run.answer.status == "validation_failed"
    assert "не отказывала" not in run.answer.answer
    assert not model.inputs(GroundingVerdict)
    assert len(model.inputs(ReviewDraft)) == 3
    assert not run.answer.claims


async def test_deal_extraction_does_not_send_unbounded_dialogue_memory(settings, monkeypatch):
    deal = contractor()
    deal.dialogue = DialogueMemory(
        outcome="answered",
        previous_question="PRIVATE_PREVIOUS_QUESTION",
        snapshot_ids=["s"],
        source_hash="h",
        context_revision=deal.context_revision,
    )

    async def complete(settings, messages, client, **kwargs):
        assert "PRIVATE_PREVIOUS" not in str(messages)
        assert '"dialogue"' not in str(messages)
        return SimpleNamespace(answer="{}")

    monkeypatch.setattr("counterparty_agent.ai.deal._request_completion", complete)
    result = await extract_deal(settings, "Продолжим проверку", deal, client=object())
    assert result.dialogue == deal.dialogue


async def test_local_repair_does_not_inherit_semantic_feedback_for_an_older_draft(
    source, settings, monkeypatch
):
    snapshot = april(source)
    full_catalog, _ = review_catalog(
        (snapshot,), (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),), contractor()
    )
    catalog = {
        key: fact
        for key, fact in full_catalog.items()
        if fact.topic == "arbitration_summary" or fact.metric == "enforcement_summary"
    }
    assert len(catalog) == 2
    invalid_text = "Сумма требований — 987654321012345 рублей."
    final_text = (
        "Само наличие судебных дел не требует автоматического отказа от сотрудничества. "
        "Уточните предмет споров и результаты их рассмотрения."
    )
    attempts = 0
    verifications = 0

    def draft(data):
        nonlocal attempts
        attempts += 1
        fact = next(f for f in data["approved_facts"] if f["topic"] == "arbitration_summary")
        if attempts == 1:
            text = fact["text"]
        elif attempts == 2:
            assert data["review_feedback"]["answers_question"] is False
            assert data["review_feedback"]["reasons"] == [
                "Нужен ответ о решении, не только сводка."
            ]
            text = invalid_text
        else:
            assert attempts == 3
            assert "review_feedback" not in data
            assert "не подтверждены" in data["validation_feedback"]
            assert data["previous_draft"]["blocks"][0]["text"] == invalid_text
            text = final_text
        return ReviewDraft(
            blocks=[ReviewBlock(kind="interpretation", text=text, fact_ids=[fact["fact_id"]])]
        )

    def verdict(data):
        nonlocal verifications
        verifications += 1
        return GroundingVerdict(
            unsupported_blocks=[],
            answers_question=verifications > 1,
            reasons=["Нужен ответ о решении, не только сводка."] if verifications == 1 else [],
        )

    ReviewModel(monkeypatch, draft=draft, verdict=verdict)
    answer, checked = await synthesize(
        settings,
        object(),
        "То есть из-за судебных дел сразу отказаться от компании?",
        contractor(),
        catalog,
        "Проверены суды и взыскания.",
        response_focus="specific",
        focus_topics=["arbitration"],
    )
    assert attempts == 3 and verifications == 2
    assert answer.status == "answered" and answer.answer == final_text
    assert checked.blocks[0].text == final_text
    validate_draft(checked, catalog)


@pytest.mark.parametrize("remaining_answers_question", [True, False])
@pytest.mark.parametrize("response_focus", ["overview", "specific", "scenario"])
async def test_last_model_answer_can_drop_bad_extra_only_after_whole_answer_is_verified(
    source, settings, monkeypatch, remaining_answers_question, response_focus
):
    snapshot = april(source)

    def draft(data):
        fact = next(f for f in data["approved_facts"] if f["topic"] == "arbitration_summary")
        return ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind="action",
                    text=(
                        "Если подтверждения не предоставят, уточните причину "
                        "и обсудите альтернативы."
                    ),
                    fact_ids=[fact["fact_id"]],
                ),
                ReviewBlock(
                    kind="interpretation",
                    text="Сумма требований небольшая по сравнению с активами.",
                    fact_ids=[fact["fact_id"]],
                ),
            ]
        )

    model = ReviewModel(
        monkeypatch,
        draft=draft,
        verdict=GroundingVerdict(
            unsupported_blocks=[], answers_question=remaining_answers_question
        ),
    )
    run = await run_review(
        settings,
        "А если они не предоставят документы?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        contractor(),
        client=object(),
        response_focus=response_focus,
        initial_topics=["arbitration"],
    )
    assert model.inputs(GroundingVerdict)
    assert len(model.inputs(ReviewDraft)) == 3
    assert all(len(v["blocks"]) == 1 for v in model.inputs(GroundingVerdict))
    if remaining_answers_question:
        assert run.answer.status == "answered" and len(run.answer.claims) == 1
        assert run.answer.answer == (
            "Если подтверждения не предоставят, уточните причину и обсудите альтернативы."
        )
        assert "небольшая" not in run.answer.answer
        validate_review_run(run)
    else:
        assert run.answer.status == "validation_failed" and not run.answer.claims
