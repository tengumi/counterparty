"""Память ошибки и продолжения не заменяет условия сделки или доказательства отчёта."""

from __future__ import annotations

import json

import pytest
from pydantic import SecretStr, ValidationError
from test_intent_router import ScriptedClient, _context
from test_review_session import SessionHarness
from test_review_session import harness as session_harness
from test_review_session import source as review_source

from counterparty_agent.ai.contracts import ApprovedFact, GroundedAnswer, GroundedClaim
from counterparty_agent.ai.deal import DealContext, DealPatch, apply_deal
from counterparty_agent.ai.dialogue import dialogue_context, remember_dialogue
from counterparty_agent.ai.reasoning import ReviewBlock, ReviewDraft
from counterparty_agent.ai.router import IntentPlan, RouterResult, route_intent
from counterparty_agent.config import Settings
from counterparty_agent.workflow.review import ReviewRun

harness = session_harness
source = review_source


def remembered_deal() -> DealContext:
    deal = apply_deal(DealContext(), DealPatch(advance="аванс"), "Планируем аванс")
    fact = ApprovedFact(
        "known", GroundedClaim(text="Данные отчёта", evidence_ids=("source",)), "finance"
    )
    draft = ReviewDraft(
        blocks=[
            ReviewBlock(
                kind="action", text="Запросите пояснения к показателям.", fact_ids=["known"]
            )
        ]
    )
    remember_dialogue(
        deal,
        "На что обратить внимание?",
        "answered",
        ["company"],
        "source",
        topics=("finance",),
        draft=draft,
        catalog={"known": fact},
    )
    return deal


def test_error_preserves_only_verified_actions_and_records_unresolved_question():
    deal = remembered_deal()
    terms = deal.terms.copy()
    failed = ReviewDraft(
        blocks=[ReviewBlock(kind="action", text="Непроверенная рекомендация", fact_ids=["fake"])]
    )
    remember_dialogue(
        deal,
        "А если документы не предоставят?",
        "validation_failed",
        ["company"],
        "source",
        topics=("finance", "documents"),
        draft=failed,
        catalog={},
    )
    memory = dialogue_context(deal, ["company"], "source")
    assert memory is not None and memory["outcome"] == "validation_failed"
    assert memory["unresolved_question"] == "А если документы не предоставят?"
    assert memory["recommended_actions"][0]["text"] == "Запросите пояснения к показателям."
    assert "Непроверенная" not in json.dumps(memory, ensure_ascii=False)
    assert memory["usage"] == "untrusted_conversation_context_not_evidence"
    assert deal.terms == terms and deal.advance == "аванс"


@pytest.mark.parametrize(
    ("ids", "source"),
    [(["other"], "source"), (["company", "other"], "source"), ([], "source"), (["company"], "new")],
)
def test_previous_dialogue_is_not_shared_between_scope_or_sources(ids, source):
    assert dialogue_context(remembered_deal(), ids, source) is None


def test_changed_conditions_expire_previous_recommendations():
    deal = apply_deal(remembered_deal(), DealPatch(advance="после приёмки"), "Оплата после приёмки")
    assert dialogue_context(deal, ["company"], "source") is None


def test_dialogue_round_trip_is_bounded_and_does_not_store_failed_draft():
    deal = remembered_deal()
    remember_dialogue(deal, "Вопрос " * 1000, "validation_failed", ["company"], "source")
    restored = DealContext.model_validate_json(deal.model_dump_json())
    assert restored.dialogue is not None
    assert len(restored.dialogue.previous_question) == 1200
    assert restored.dialogue == deal.dialogue


def test_model_projection_has_fixed_budget_and_drops_old_evidence_ids():
    from counterparty_agent.ai.dialogue import RememberedAction

    deal = remembered_deal()
    deal.dialogue.previous_question = '"' * 1200
    deal.dialogue.unresolved_question = "\\" * 1200
    deal.dialogue.recommended_actions = [
        RememberedAction(text='"' * 500, fact_ids=["long-id-" * 20] * 32),
        RememberedAction(text="\\" * 500, fact_ids=["another-id-" * 20] * 32),
    ]
    projected = dialogue_context(deal, ["company"], "source")
    encoded = json.dumps(projected, ensure_ascii=False)
    assert len(encoded) <= 4000 and projected["questions_truncated"]
    assert len(projected["previous_question"]) <= 600
    assert len(projected["unresolved_question"]) <= 600
    assert "fact_ids" not in encoded and "long-id" not in encoded
    assert len(deal.dialogue.previous_question) == 1200


def test_canonical_enforcement_fact_survives_courts_scenario_error_and_conversation(source):
    from counterparty_agent.ai.catalog import build_fact_catalog
    from counterparty_agent.analytics.core import analyze_snapshot

    found = source.find_by_inn("7813664770")
    snapshot = source.get_snapshot(found.candidates[0].snapshot_id)
    facts = build_fact_catalog(
        snapshot, analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    )
    enforcement = next(fact for fact in facts if fact.metric == "enforcement_summary")
    court = next(fact for fact in facts if fact.topic == "arbitration_summary")
    finance = next(fact for fact in facts if fact.topic == "granular_metric")
    catalog = {fact.fact_id: fact for fact in (enforcement, court, finance)}
    deal = DealContext()
    scope, source_hash = [snapshot.snapshot_id], source.source_hash

    def record(question, selected, *, topics, kind="fact"):
        draft = ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind=kind,
                    text="Объяснение модели не является каноническим фактом.",
                    fact_ids=[fact.fact_id for fact in selected],
                )
            ]
        )
        remember_dialogue(
            deal,
            question,
            "answered",
            scope,
            source_hash,
            topics=topics,
            draft=draft,
            catalog=catalog,
        )

    record(
        "Какие обстоятельства проверить?", (enforcement, finance), topics=("enforcement", "finance")
    )
    record("Следует отказаться из-за судебных дел?", (court,), topics=("arbitration",))
    record("А если не дадут документы?", (court,), topics=("documents",), kind="action")
    remember_dialogue(deal, "Объясни подробнее", "validation_failed", scope, source_hash)
    previous = deal.dialogue.model_copy(deep=True)
    remember_dialogue(deal, "Ты не помогаешь?", "conversation", scope, source_hash)
    assert deal.dialogue == previous
    retained = next(
        fact for fact in deal.dialogue.recent_facts if fact.fact_id == enforcement.fact_id
    )
    assert retained.text == enforcement.claim.text and "24.63" in retained.text
    assert retained.topic == "enforcement"
    assert len({fact.fact_id for fact in deal.dialogue.recent_facts}) == len(
        deal.dialogue.recent_facts
    )
    projected = dialogue_context(deal, scope, source_hash)
    assert any(
        fact["topic"] == "enforcement" and "24.63" in fact["text"]
        for fact in projected["recent_facts"]
    )
    assert all("Объяснение модели" not in fact["text"] for fact in projected["recent_facts"])
    assert all("fact_id" not in fact for fact in projected["recent_facts"])
    assert dialogue_context(deal, ["another-scope"], source_hash) is None
    assert dialogue_context(deal, scope, "new-source") is None
    remember_dialogue(deal, "Новая проверка", "answered", ["another-scope"], source_hash)
    assert deal.dialogue.recent_facts == []


def test_eight_long_canonical_topics_fit_projection_without_cutting_fact_text():
    from counterparty_agent.ai.dialogue import RememberedFact

    deal = remembered_deal()
    topics = [
        "company",
        "finance",
        "arbitration",
        "enforcement",
        "reputation",
        "licenses",
        "data_quality",
        "documents",
    ]
    deal.dialogue.recent_facts = [
        RememberedFact(fact_id=f"id-{index}", topic=topic, metric="\\" * 80, text='"' * 600)
        for index, topic in enumerate(topics)
    ]
    deal.dialogue.previous_question = "\\" * 1200
    deal.dialogue.unresolved_question = '"' * 1200
    projected = dialogue_context(deal, ["company"], "source")
    assert len(json.dumps(projected, ensure_ascii=False)) <= 4000
    assert 1 <= len(projected["recent_facts"]) <= 4
    assert all(fact["text"] == '"' * 600 for fact in projected["recent_facts"])
    assert all("fact_id" not in fact for fact in projected["recent_facts"])


@pytest.mark.parametrize("focus", ["specific", "scenario"])
async def test_router_preserves_general_focus_contract(focus):
    settings = Settings(_env_file=None, llm_api_key=SecretStr("test-only"))
    client = ScriptedClient(
        json.dumps(
            {
                "action": "ask",
                "answer_mode": "analysis",
                "response_focus": focus,
                "review_topics": ["enforcement"],
            }
        )
    )
    result = await route_intent(settings, "Как это влияет на сделку?", {}, client=client)
    assert result.plan is not None and result.plan.response_focus == focus
    assert result.plan.review_topics == ("enforcement",)


@pytest.mark.parametrize(
    "values",
    [
        {"action": "conversation", "targets": ["Компания"]},
        {"action": "conversation", "deal_patch": {"advance": "аванс"}},
        {"action": "ask", "response_focus": "scenario", "deal_patch": {"advance": "аванс"}},
    ],
)
def test_service_or_hypothetical_messages_cannot_change_confirmed_conditions(values):
    with pytest.raises(ValidationError):
        IntentPlan.model_validate(values)


async def test_router_gets_previous_outcome_but_not_snapshot_or_unchecked_extra_fields():
    settings = Settings(_env_file=None, llm_api_key=SecretStr("test-only"))
    deal = remembered_deal()
    remember_dialogue(deal, "А если откажут?", "validation_failed", ["company"], "source")
    client = ScriptedClient('{"action":"conversation"}')
    result = await route_intent(
        settings,
        "Ты отказываешься помочь?",
        {
            "review_context": deal.model_dump(mode="json"),
            "dialogue_snapshot_ids": ["company"],
            "dialogue_source_hash": "source",
            "snapshot": "RAW_SNAPSHOT",
            "previous_dialogue": "FORGED_MEMORY",
        },
        client=client,
    )
    assert result.plan is not None and result.plan.action == "conversation"
    data = _context(client.calls[0])["session"]
    assert data["previous_dialogue"]["outcome"] == "validation_failed"
    assert data["previous_dialogue"]["unresolved_question"] == "А если откажут?"
    assert "RAW_SNAPSHOT" not in json.dumps(client.calls)
    assert "FORGED_MEMORY" not in json.dumps(client.calls)


async def test_failure_then_service_reply_keeps_selection_terms_and_unresolved_question(
    harness: SessionHarness,
    monkeypatch,
):
    snapshot = harness.source.snapshots[0]
    await harness.run(snapshot.identity.inn)
    harness.deals["one"] = apply_deal(
        harness.deals["one"], DealPatch(advance="аванс 40%"), "Планируем аванс 40%"
    )
    harness.plan = IntentPlan(
        action="ask",
        answer_mode="analysis",
        response_focus="scenario",
        review_topics=("arbitration",),
    )

    async def fail(settings, question, snapshots, analyses, deal, **kwargs):
        assert kwargs["response_focus"] == "scenario"
        return ReviewRun(
            GroundedAnswer(
                "validation_failed", "Непроверенный ответ не показан", (), (), "test", True
            ),
            deal,
            [],
        )

    monkeypatch.setattr("counterparty_agent.workflow.review_session.run_review", fail)
    result = await harness.run("А если они не предоставят документы?")
    assert result.status == "validation_failed"
    remembered = harness.deals["one"].dialogue.model_copy(deep=True)
    harness.plan = IntentPlan(action="conversation")
    reply = await harness.run("Ты мне отказываешься помогать?")
    assert reply.status == "conversation" and reply.snapshot is snapshot
    assert reply.review is not None
    assert reply.review.context_revision == harness.deals["one"].context_revision
    assert reply.review.advance == "аванс 40%"
    assert "не удалось подтвердить" in reply.answer and "повторять не нужно" in reply.answer
    assert "Уточните компанию" not in reply.answer and not reply.answer_claims
    assert harness.deals["one"].dialogue == remembered
    state = json.dumps(await harness.state(), ensure_ascii=False)
    assert "документы" not in state and "dialogue" not in state
    restored = await harness.run(restore=True)
    assert restored.snapshot is snapshot and harness.deals["one"].dialogue == remembered
    other = await harness.run("Ты мне отказываешься помогать?", thread="other")
    assert "не удалось подтвердить" not in other.answer
    assert harness.route_inputs[-1]["review_context"]["dialogue"] is None


async def test_service_route_cannot_swallow_new_explicit_company(harness: SessionHarness):
    previous, new = harness.source.snapshots[:2]
    await harness.run(previous.identity.inn)
    harness.plan = IntentPlan(action="conversation")
    result = await harness.run(f"А что с ИНН {new.identity.inn}?")
    assert result.status == "routing_failed" and result.snapshot is previous
    assert "повторять не нужно" not in result.answer


async def test_router_separates_specific_focus_from_additional_reading():
    settings = Settings(_env_file=None, llm_api_key=SecretStr("test-only"))
    client = ScriptedClient(
        json.dumps(
            {
                "action": "ask",
                "answer_mode": "analysis",
                "response_focus": "specific",
                "focus_topic": "enforcement",
                "review_topics": ["company", "finance", "enforcement"],
            }
        )
    )
    result = await route_intent(settings, "Насколько важно это взыскание?", {}, client=client)
    assert result.plan is not None and result.plan.focus_topic == "enforcement"
    assert result.plan.review_topics == ("company", "finance", "enforcement")
    with pytest.raises(ValidationError):
        IntentPlan(action="ask", focus_topic="external_search")


async def test_specific_focus_reaches_review_separately_from_reading_sections(
    harness: SessionHarness,
    monkeypatch,
):
    snapshot = harness.source.snapshots[0]
    await harness.run(snapshot.identity.inn)
    harness.plan = IntentPlan(
        action="ask",
        answer_mode="analysis",
        response_focus="specific",
        focus_topic="enforcement",
        review_topics=("company", "finance", "enforcement"),
    )

    async def capture(settings, question, snapshots, analyses, deal, **kwargs):
        assert kwargs["focus_topic"] == "enforcement"
        assert kwargs["initial_topics"] == ("company", "finance", "enforcement")
        return ReviewRun(
            GroundedAnswer("insufficient_data", "Нужны сведения", (), (), "test", True),
            deal,
            [],
        )

    monkeypatch.setattr("counterparty_agent.workflow.review_session.run_review", capture)
    result = await harness.run("Насколько важно это взыскание?")
    assert result.status == "insufficient_data" and result.snapshot is snapshot


async def test_routing_failure_keeps_review_and_can_be_discussed_without_new_search(
    harness: SessionHarness,
    monkeypatch,
):
    snapshot = harness.source.snapshots[0]
    await harness.run(snapshot.identity.inn)
    harness.deals["one"] = apply_deal(
        harness.deals["one"], DealPatch(advance="аванс"), "Хотим аванс"
    )

    async def failed_route(*args, **kwargs):
        return RouterResult(None, "routing_failed", True, "test")

    monkeypatch.setattr("counterparty_agent.workflow.semantic.route_intent", failed_route)
    question = "А если они мне откажут в предоставление документах"
    result = await harness.run(question)
    assert result.status == "routing_failed" and result.snapshot is snapshot
    assert result.review is not None and result.review.advance == "аванс"
    assert "повторять реквизиты не нужно" in result.answer
    assert "Уточните компанию" not in result.answer
    assert result.review.dialogue.outcome == "routing_failed"
    assert result.review.dialogue.unresolved_question == question
    monkeypatch.setattr("counterparty_agent.workflow.semantic.route_intent", harness.route)
    harness.plan = IntentPlan(action="conversation")
    continued = await harness.run("Ты мне отказываешься помогать?")
    assert continued.review is not None and continued.review.advance == "аванс"
    assert "ошибка обработки запроса" in continued.answer
    assert continued.review.dialogue.unresolved_question == question


async def test_routing_failure_of_unknown_address_does_not_attach_it_to_old_report(
    harness: SessionHarness,
    monkeypatch,
):
    first, second = harness.source.snapshots[:2]
    await harness.run(first.identity.inn)

    async def failed_route(*args, **kwargs):
        return RouterResult(None, "routing_failed", True, "test")

    monkeypatch.setattr("counterparty_agent.workflow.semantic.route_intent", failed_route)
    result = await harness.run(f"А что с ИНН {second.identity.inn}?")
    assert result.snapshot is first and result.review is not None
    assert result.review.dialogue is None
    assert "Уточните компанию" in result.answer


async def test_focused_memory_is_available_only_for_same_company_not_whole_group(
    harness: SessionHarness,
    monkeypatch,
):
    first, second = harness.source.snapshots[:2]
    await harness.run(f"{first.identity.inn}; {second.identity.inn}")
    captured = []

    async def fail(settings, question, snapshots, analyses, deal, **kwargs):
        captured.append(kwargs["dialogue_context"])
        return ReviewRun(
            GroundedAnswer("validation_failed", "Ответ не подтверждён", (), (), "test", True),
            deal,
            [],
        )

    monkeypatch.setattr("counterparty_agent.workflow.review_session.run_review", fail)
    harness.plan = IntentPlan(
        action="ask", position=2, answer_mode="analysis", response_focus="specific"
    )
    await harness.run("Что важно у второй?")
    assert harness.deals["one"].dialogue.snapshot_ids == [second.snapshot_id]
    harness.plan = IntentPlan(action="ask", answer_mode="analysis", response_focus="scenario")
    await harness.run("А если откажется отвечать?")
    assert captured[-1]["previous_question"] == "Что важно у второй?"
    harness.plan = IntentPlan(action="ask", scope="group", answer_mode="analysis")
    await harness.run("Теперь сравни всю группу")
    assert captured[-1] is None


async def test_project_failure_can_be_discussed_without_new_analysis(source, monkeypatch):
    from datetime import timedelta

    from counterparty_agent.ai.router import RouterResult
    from counterparty_agent.projects.dialogue import ask_project
    from counterparty_agent.projects.models import Project

    snapshot = source.snapshots[0]
    project = Project(
        project_id="dialogue-test",
        title="Проверка",
        session_id="project-session",
        source_hash=source.source_hash,
        snapshot_ids=[snapshot.snapshot_id],
        deal=apply_deal(DealContext(), DealPatch(advance="аванс"), "Планируем аванс"),
    )
    project.deal.snapshot_ids = [snapshot.snapshot_id]
    project.deal.source_hash = source.source_hash
    remember_dialogue(
        project.deal,
        "А если не предоставят документы?",
        "validation_failed",
        [snapshot.snapshot_id],
        source.source_hash,
    )
    previous = project.deal.dialogue.model_copy(deep=True)

    async def route(*args, **kwargs):
        return RouterResult(IntentPlan(action="conversation"), "routed", True, "test")

    async def forbidden(*args, **kwargs):
        pytest.fail("Служебный ответ не должен запускать повторный анализ")

    monkeypatch.setattr("counterparty_agent.projects.dialogue.route_intent", route)
    monkeypatch.setattr("counterparty_agent.projects.dialogue.run_review", forbidden)
    answer = await ask_project(
        project,
        source,
        Settings(_env_file=None, llm_api_key=SecretStr("test")),
        object(),
        "Ты отказываешься помочь?",
        snapshot.report_at + timedelta(days=1),
    )
    assert "не удалось подтвердить" in answer.answer and "повторять не нужно" in answer.answer
    assert not answer.claims and project.deal.dialogue == previous
    assert project.deal.advance == "аванс" and project.focused_snapshot_id is None
