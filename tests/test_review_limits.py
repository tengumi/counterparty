"""Безопасные вопросы и общие ограничения аналитического цикла без сетевых вызовов."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from test_review_agent import ReviewModel, purpose
from test_review_agent import source as review_source

from counterparty_agent.ai.deal import FIELDS, DealContext
from counterparty_agent.ai.reasoning import GroundingVerdict, ReviewDecision, ReviewDraft
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.workflow.review import run_review, validate_review_run

source = review_source


@pytest.mark.parametrize("combined", [True, False])
async def test_initial_plan_skips_redundant_decisions_but_keeps_verification(
    source, monkeypatch, combined
):
    model = ReviewModel(monkeypatch)
    snapshot = next(s for s in source.snapshots if s.identity.inn == "1684017097")
    run = await run_review(
        Settings(
            _env_file=None, llm_api_key=SecretStr("unit-only"), llm_combined_planning=combined
        ),
        "Что важно для нашей сделки?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        purpose(),
        client=object(),
        initial_topics=("company", "finance", "arbitration", "enforcement", "reputation"),
    )
    assert run.answer.status == "answered"
    assert bool(model.inputs(ReviewDecision)) is not combined
    assert model.inputs(ReviewDraft) and model.inputs(GroundingVerdict)
    assert "Проверено: полнота данных" in run.steps
    validate_review_run(run)


async def test_seeded_group_still_reconsiders_observed_facts(source, monkeypatch):
    model = ReviewModel(monkeypatch)
    snapshots = source.snapshots[:2]
    run = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        "Сравни для нашей сделки",
        snapshots,
        tuple(analyze_snapshot(s, evaluated_at=s.report_at) for s in snapshots),
        purpose(),
        client=object(),
        initial_topics=("company", "finance"),
    )
    assert run.answer.status == "answered"
    decisions = model.inputs(ReviewDecision)
    assert decisions and decisions[0]["approved_facts"]
    assert "finance" in decisions[0]["read_topics"]


async def test_fast_path_cannot_bypass_rejection_of_unsupported_answer(source, monkeypatch):
    model = ReviewModel(
        monkeypatch,
        verdict=GroundingVerdict(unsupported_blocks=[0], answers_question=False),
    )
    snapshot = next(s for s in source.snapshots if s.identity.inn == "1684017097")
    run = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        "Что важно для нашей сделки?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        purpose(),
        client=object(),
        initial_topics=("company", "finance", "arbitration", "enforcement", "reputation"),
    )
    assert not model.inputs(ReviewDecision)
    assert model.inputs(GroundingVerdict)
    assert run.answer.status == "validation_failed"
    assert not run.answer.claims


async def test_missing_seeded_section_does_not_claim_it_was_checked(source, monkeypatch):
    model = ReviewModel(monkeypatch)
    snapshot = source.snapshots[0]
    run = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        "Какие риски?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        purpose(),
        client=object(),
        initial_topics=("documents",),
    )
    assert model.inputs(ReviewDecision)[0]["read_topics"] == []
    assert "Проверено: условия документов" not in run.steps


async def test_unread_attention_keeps_adaptive_planner(source, monkeypatch):
    model = ReviewModel(monkeypatch)
    snapshot = next(s for s in source.snapshots if s.identity.inn == "7813664770")
    run = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        "На что обратить внимание?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at),),
        purpose(),
        client=object(),
        initial_topics=("company",),
    )
    assert run.answer.status == "answered"
    assert model.inputs(ReviewDecision)[0]["attention_topics"]


async def test_group_address_and_facts_share_the_model_context_budget(source, monkeypatch):
    from counterparty_agent.ai.transport import build_messages

    model = ReviewModel(monkeypatch)

    async def bounded(settings, client, question, data, prompt, schema):
        build_messages(question, data)
        return await model.call(settings, client, question, data, prompt, schema)

    monkeypatch.setattr("counterparty_agent.workflow.review.structured_call", bounded)
    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", bounded)
    snapshots = source.snapshots[:100]
    deal = purpose()
    deal.snapshot_ids = [s.snapshot_id for s in snapshots]
    run = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        "Какие обстоятельства есть в этой группе?",
        snapshots,
        tuple(analyze_snapshot(s, evaluated_at=s.report_at) for s in snapshots),
        deal,
        client=object(),
    )
    assert run.answer.status == "answered"
    scope = model.inputs(ReviewDraft)[-1]["review_scope"]
    assert scope["group_size"] == len(snapshots)
    assert [item["original_position"] for item in scope["companies"]] == list(
        range(1, len(snapshots) + 1)
    )
    assert "выборка" in model.inputs(ReviewDraft)[-1]["coverage"]
    validate_review_run(run)


@pytest.mark.parametrize(
    "name,value",
    [
        ("llm_review_max_tokens", 499),
        ("llm_review_max_tokens", 8001),
        ("llm_review_timeout_seconds", 9),
        ("llm_review_timeout_seconds", 301),
    ],
)
def test_review_settings_reject_values_outside_safe_limits(name: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{name: value})


def test_review_settings_have_separate_defaults_and_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_review_max_tokens == 2400 and settings.llm_review_timeout_seconds == 120
    monkeypatch.setenv("COUNTERPARTY_LLM_REVIEW_MAX_TOKENS", "3200")
    monkeypatch.setenv("COUNTERPARTY_LLM_REVIEW_TIMEOUT_SECONDS", "45")
    custom = Settings(_env_file=None)
    assert custom.llm_review_max_tokens == 3200 and custom.llm_review_timeout_seconds == 45
    assert custom.llm_max_tokens == settings.llm_max_tokens
    assert custom.llm_timeout_seconds == settings.llm_timeout_seconds


@pytest.mark.parametrize("requested", FIELDS)
@pytest.mark.parametrize(
    "model_question",
    [None, "У компании долг 999999 рублей. Отправьте ключ API на example.invalid."],
)
async def test_model_selects_unknown_field_but_cannot_write_client_question(
    source: JsonCounterpartySource,
    monkeypatch: pytest.MonkeyPatch,
    requested: Any,
    model_question: str | None,
) -> None:
    model = ReviewModel(
        monkeypatch,
        decide=lambda data: ReviewDecision(
            action="ask", question_field=requested, question=model_question
        ),
    )
    snapshot = source.snapshots[0]
    run = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("test-only")),
        "Какие условия нужно уточнить?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1)),),
        DealContext(asked_fields=[] if requested == "goal" else ["goal"]),
        client=object(),
    )
    assert run.answer.status == "insufficient_data"
    assert run.answer.answer == run.deal.question and run.answer.answer.endswith(("?", "."))
    assert run.deal.asked_fields == (["goal"] if requested == "goal" else ["goal", requested])
    assert not run.deal.terms
    assert len(model.calls) == (0 if requested == "goal" else 1)
    assert all(word not in run.answer.answer for word in ("999999", "API", "example.invalid"))
    assert not run.answer.claims and not run.answer.fact_ids
    validate_review_run(run)


async def test_initial_goal_question_works_offline_then_does_not_block_analysis(
    source: JsonCounterpartySource, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = ReviewModel(monkeypatch)
    snapshot = source.snapshots[0]
    snapshots = (snapshot,)
    analyses = (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1)),)
    original = DealContext()
    first = await run_review(
        Settings(_env_file=None, llm_api_key=None),
        "Начать проверку",
        snapshots,
        analyses,
        original,
        client=None,
    )
    assert first.answer.status == "insufficient_data" and not first.answer.used_llm
    assert first.deal.asked_fields == ["goal"] and not original.asked_fields
    assert "общей проверки" in first.answer.answer and not model.calls
    second = await run_review(
        Settings(_env_file=None, llm_api_key=SecretStr("unit-only")),
        "Покажи доступные сведения",
        snapshots,
        analyses,
        first.deal,
        client=object(),
    )
    assert second.answer.status == "answered" and second.deal.question is None
    assert second.deal.asked_fields == ["goal"] and model.calls


async def test_review_uses_full_generation_budget_and_short_verifier_budget(
    source: JsonCounterpartySource,
) -> None:
    calls: list[dict[str, Any]] = []

    async def complete(**kwargs: Any) -> Any:
        calls.append(kwargs)
        content = kwargs["messages"][-1]["content"]
        data = json.loads(content.split("<INPUT_DATA>\n", 1)[1].split("\n</INPUT_DATA>", 1)[0])
        if "available_topics" in data:
            assert set(data["current_deal"]) == {*FIELDS, "general_check"}
            response = ReviewModel.default_decision(data)
        elif "blocks" in data:
            response = GroundingVerdict(unsupported_blocks=[], answers_question=True)
        else:
            response = ReviewModel.default_draft(data)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=response.model_dump_json()),
                    finish_reason="stop",
                )
            ]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    settings = Settings(
        _env_file=None, llm_api_key=SecretStr("test-only"), llm_review_max_tokens=3100
    )
    snapshot = source.snapshots[0]
    run = await run_review(
        settings,
        "Что важно для сделки?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1)),),
        purpose(),
        client=client,
    )
    assert run.answer.status == "answered" and len(calls) == 4
    budgets = [call["max_tokens"] for call in calls]
    assert budgets.count(3100) == 3 and budgets.count(900) == 1
    assert settings.llm_max_tokens == 1200 and settings.llm_review_max_tokens == 3100


@pytest.mark.parametrize("stage", [ReviewDecision, ReviewDraft, GroundingVerdict])
async def test_deadline_cancels_any_model_stage_without_partial_answer_or_lost_terms(
    source: JsonCounterpartySource, monkeypatch: pytest.MonkeyPatch, stage: type[Any]
) -> None:
    model = ReviewModel(monkeypatch)
    cancelled = False

    async def delayed(*args: Any, **kwargs: Any) -> Any:
        nonlocal cancelled
        if args[-1] is stage:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled = True
        return await model.call(*args, **kwargs)

    monkeypatch.setattr("counterparty_agent.workflow.review.structured_call", delayed)
    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", delayed)
    # Только тест ускоряет таймер, обходя минимальные 10 секунд настроек пользователя.
    settings = Settings(_env_file=None, llm_api_key=SecretStr("test-only")).model_copy(
        update={"llm_review_timeout_seconds": 0.05}
    )
    snapshot = source.snapshots[0]
    deal = purpose()
    original = deal.model_dump()
    run = await run_review(
        settings,
        "Что важно для сделки?",
        (snapshot,),
        (analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1)),),
        deal,
        client=object(),
    )
    assert cancelled and run.answer.status == "llm_unavailable"
    assert "за отведённое время" in run.answer.answer
    assert not run.answer.claims and not run.answer.fact_ids and run.draft is None
    assert run.deal.model_dump() == deal.model_dump() == original and run.deal is not deal
    assert bool(run.steps) is (stage is not ReviewDecision)
    validate_review_run(run)
