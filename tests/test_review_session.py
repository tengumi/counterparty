"""Полный workflow сохраняет условия вне checkpoint и ограничивает анализ адресатом."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from test_review_agent import ReviewModel
from test_review_agent import source as review_source

from counterparty_agent.ai.deal import DealContext, DealPatch
from counterparty_agent.ai.reasoning import (
    GroundingVerdict,
    ReviewBlock,
    ReviewDecision,
    ReviewDraft,
)
from counterparty_agent.ai.router import IntentPlan, RouterResult
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.workflow.builder import build_graph
from counterparty_agent.workflow.contracts import WorkflowContext, WorkflowResult

source = review_source


class SessionHarness:
    """Настоящий checkpointer; отдельная память условий имитирует границу HTTP/SQLite."""

    def __init__(self, source: JsonCounterpartySource, monkeypatch: pytest.MonkeyPatch) -> None:
        self.source = source
        self.graph = build_graph(InMemorySaver())
        self.settings = Settings(_env_file=None, llm_api_key=SecretStr("test-only"))
        self.deals: dict[str, DealContext] = {}
        self.route_inputs: list[dict[str, Any]] = []
        self.plan = IntentPlan(action="ask", answer_mode="analysis")
        self.model = ReviewModel(monkeypatch)
        monkeypatch.setattr("counterparty_agent.workflow.semantic.route_intent", self.route)

    async def route(
        self, settings: Any, question: str, session: dict[str, Any], **kwargs: Any
    ) -> RouterResult:
        self.route_inputs.append(json.loads(json.dumps(session)))
        return RouterResult(self.plan, "routed", True, "test-only")

    async def run(
        self, question: str = "", *, thread: str = "one", restore: bool = False
    ) -> WorkflowResult:
        context = WorkflowContext(
            self.source,
            max(s.report_at for s in self.source.snapshots) + timedelta(days=1),
            question=question,
            settings=self.settings,
            llm_client=object(),
            deal=self.deals.get(thread, DealContext()).model_copy(deep=True),
            restore=restore,
        )
        await self.graph.ainvoke({}, {"configurable": {"thread_id": thread}}, context=context)
        assert context.result is not None and context.deal is not None
        self.deals[thread] = context.deal.model_copy(deep=True)
        return context.result

    async def state(self, thread: str = "one") -> dict[str, Any]:
        return dict((await self.graph.aget_state({"configurable": {"thread_id": thread}})).values)


@pytest.fixture
def harness(source: JsonCounterpartySource, monkeypatch: pytest.MonkeyPatch) -> SessionHarness:
    return SessionHarness(source, monkeypatch)


async def test_identification_opens_purpose_question_once_and_restore_does_not_run_model(
    harness: SessionHarness,
) -> None:
    snapshot = harness.source.snapshots[0]
    result = await harness.run(snapshot.identity.inn)
    assert result.snapshot is snapshot and result.status == "analyzed"
    assert result.review is not None and result.review.question
    assert result.review.asked_fields == ["goal"]
    assert not harness.route_inputs and not harness.model.calls
    restored = await harness.run(restore=True)
    assert restored.answer == result.answer
    assert restored.review.asked_fields == ["goal"]
    assert not harness.model.calls and not harness.route_inputs


@pytest.mark.parametrize("review_topics", [(), ("company", "finance", "enforcement")])
async def test_goal_and_payment_change_reach_analysis_without_stale_terms_or_new_search(
    harness: SessionHarness,
    review_topics,
) -> None:
    snapshot = harness.source.snapshots[0]
    await harness.run(snapshot.identity.inn)
    harness.plan = IntentPlan(
        action="ask",
        answer_mode="analysis",
        deal_patch=DealPatch(goal="выбираю поставщика", role="поставщика", advance="аванс 80%"),
        review_topics=review_topics,
    )
    first = await harness.run("Я выбираю поставщика, аванс 80%")
    assert first.status == "answered" and first.snapshot is snapshot
    assert first.review is not None and first.review.question is None
    assert first.review.asked_fields == ["goal"]
    old_evidence = first.review.terms["advance"].evidence_id
    revision = first.review.context_revision
    harness.plan = IntentPlan(
        action="ask", answer_mode="analysis", deal_patch=DealPatch(advance="оплата после поставки")
    )
    changed = await harness.run("Теперь оплата после поставки, что меняется?")
    assert changed.status == "answered" and changed.snapshot is snapshot
    assert changed.review.context_revision == revision + 1
    assert changed.review.goal == first.review.goal
    latest = harness.model.inputs(ReviewDraft)[-1]
    assert latest["current_deal"]["advance"] == "оплата после поставки"
    assert all("аванс 80%" not in fact["text"] for fact in latest["approved_facts"])
    assert all(old_evidence not in claim.evidence_ids for claim in changed.answer_claims)
    assert harness.route_inputs[-1]["review_context"]["advance"] == "аванс 80%"
    state = json.dumps(await harness.state(), ensure_ascii=False)
    assert "deal" not in state and "аванс 80%" not in state and "оплата после поставки" not in state
    assert "выбираю поставщика" not in state
    assert "review_topics" not in state


async def test_explicit_advance_is_enough_to_start_without_repeating_purpose(harness):
    snapshot = harness.source.snapshots[0]
    harness.plan = IntentPlan(
        action="ask",
        targets=(snapshot.identity.inn,),
        answer_mode="analysis",
        deal_patch=DealPatch(advance="существенный аванс"),
    )
    result = await harness.run(
        f"Хотим перечислить существенный аванс, ИНН {snapshot.identity.inn}. "
        "На что обратить внимание?"
    )
    assert result.status == "answered"
    assert result.review is not None and result.review.advance == "существенный аванс"
    assert "goal" not in result.review.asked_fields


async def test_first_free_request_with_purpose_does_not_ask_for_it_again(
    harness: SessionHarness,
) -> None:
    snapshot = harness.source.snapshots[0]
    harness.plan = IntentPlan(
        action="lookup",
        targets=(snapshot.identity.inn,),
        answer_mode="analysis",
        deal_patch=DealPatch(goal="выбираю поставщика", role="поставщика"),
    )
    result = await harness.run(f"Я выбираю поставщика, проверь ИНН {snapshot.identity.inn}")
    assert result.status == "answered" and result.snapshot is snapshot
    assert result.review is not None and not result.review.question
    assert result.review.goal == "выбираю поставщика"
    assert not result.review.asked_fields


@pytest.mark.parametrize("identifier_kind", ["inn", "ogrn"])
async def test_first_request_combines_name_identifier_and_advance(
    harness: SessionHarness, identifier_kind: str
) -> None:
    snapshot = harness.source.snapshots[0]
    identifier = getattr(snapshot.identity, identifier_kind)
    question = (
        f"Я рассматриваю {snapshot.identity.short_name} как подрядчика и планирую аванс. "
        f"Проверь компанию по {identifier_kind.upper()} {identifier}. На что обратить внимание?"
    )
    harness.plan = IntentPlan(
        action="lookup",
        targets=(identifier,),
        answer_mode="analysis",
        deal_patch=DealPatch(role="подрядчика", advance="аванс"),
    )
    result = await harness.run(question)
    assert result.status == "answered" and result.snapshot is snapshot
    assert result.review is not None
    assert result.review.role == "подрядчика" and result.review.advance == "аванс"
    assert not result.review.question and not result.review.asked_fields
    assert result.answer_claims and harness.model.inputs(ReviewDraft)
    restored = await harness.run(restore=True)
    assert restored.snapshot is snapshot and restored.review is not None
    assert restored.review.advance == "аванс" and restored.review.role == "подрядчика"


async def test_conflicting_name_and_identifier_preserve_selection_and_terms(
    harness: SessionHarness,
) -> None:
    previous, target = harness.source.snapshots[:2]
    await harness.run(previous.identity.inn)
    before = harness.deals["one"].model_dump()
    harness.plan = IntentPlan(
        action="ask",
        targets=(target.identity.inn,),
        answer_mode="analysis",
        deal_patch=DealPatch(advance="аванс"),
    )
    result = await harness.run(
        f"Проверь ООО «Другое-название-для-проверки» по ИНН {target.identity.inn}. Планирую аванс."
    )
    assert result.status == "needs_clarification"
    assert "Название в запросе не совпадает" in result.answer
    assert target.identity.short_name in result.answer
    assert result.snapshot is previous and not result.answer_claims
    assert not harness.model.calls
    assert harness.deals["one"].model_dump() == before


async def test_focused_analysis_uses_one_company_and_keeps_group_deal_memory(
    harness: SessionHarness,
) -> None:
    first, second = harness.source.snapshots[:2]
    await harness.run(f"{first.identity.inn}; {second.identity.inn}")
    harness.plan = IntentPlan(
        action="ask",
        scope="group",
        answer_mode="analysis",
        deal_patch=DealPatch(goal="выбираю поставщика", advance="аванс 80%"),
    )
    group = await harness.run("Я выбираю поставщика, аванс 80%")
    assert group.status == "answered" and group.snapshots == (first, second)
    group_ids = list(group.review.snapshot_ids)
    harness.plan = IntentPlan(action="ask", position=2, answer_mode="analysis")
    focused = await harness.run("А какие риски у второго?")
    assert focused.status == "answered" and focused.focus_snapshot_id == second.snapshot_id
    assert focused.snapshot is second and focused.snapshots == (first, second)
    assert focused.review.snapshot_ids == group_ids
    assert focused.review.advance == "аванс 80%"
    for schema in (ReviewDecision, ReviewDraft, GroundingVerdict):
        scope = harness.model.inputs(schema)[-1]["review_scope"]
        assert scope == {
            "mode": "focused",
            "group_size": 2,
            "companies": [
                {
                    "name": second.identity.short_name,
                    "inn": second.identity.inn,
                    "original_position": 2,
                    "report_available": True,
                }
            ],
        }
    catalog_text = json.dumps(
        harness.model.inputs(ReviewDraft)[-1]["approved_facts"], ensure_ascii=False
    )
    assert second.identity.inn in catalog_text and first.identity.inn not in catalog_text
    for claim in focused.answer_claims:
        assert all(eid not in {e.evidence_id for e in first.evidence} for eid in claim.evidence_ids)
    harness.plan = IntentPlan(action="ask", scope="group", answer_mode="analysis")
    restored = await harness.run("Каков итог по всей группе?")
    assert restored.status == "answered" and restored.focus_snapshot_id is None
    assert restored.review.snapshot_ids == group_ids and restored.review.advance == "аванс 80%"
    scope = harness.model.inputs(ReviewDraft)[-1]["review_scope"]
    assert scope["mode"] == "group"
    assert [company["original_position"] for company in scope["companies"]] == [1, 2]
    group_text = json.dumps(
        harness.model.inputs(ReviewDraft)[-1]["approved_facts"], ensure_ascii=False
    )
    assert first.identity.inn in group_text and second.identity.inn in group_text


async def test_new_company_and_new_thread_do_not_inherit_purpose_or_payment(
    harness: SessionHarness,
) -> None:
    first, second = harness.source.snapshots[:2]
    await harness.run(first.identity.inn)
    harness.plan = IntentPlan(
        action="ask",
        answer_mode="analysis",
        deal_patch=DealPatch(goal="проверяю покупателя", advance="аванс 80%"),
    )
    await harness.run("Я проверяю покупателя, аванс 80%")
    other = await harness.run(second.identity.inn)
    assert other.snapshot is second and other.review.question
    assert other.review.goal is None and other.review.advance is None and not other.review.terms
    new = await harness.run(first.identity.inn, thread="two")
    assert new.review.goal is None and new.review.advance is None
    assert new.review.asked_fields == ["goal"] and new.review.question


async def test_group_extension_keeps_purpose_and_applies_analysis_to_new_member(
    harness: SessionHarness,
) -> None:
    first, second, third = harness.source.snapshots[:3]
    await harness.run(f"{first.identity.inn}; {second.identity.inn}")
    harness.plan = IntentPlan(
        action="ask",
        scope="group",
        answer_mode="analysis",
        deal_patch=DealPatch(goal="выбираю поставщика"),
    )
    await harness.run("Я выбираю поставщика")
    harness.plan = IntentPlan(
        action="add_to_comparison", targets=(third.identity.inn,), answer_mode="analysis"
    )
    result = await harness.run(f"Добавь ИНН {third.identity.inn}")
    assert result.status == "answered" and result.snapshots == (first, second, third)
    assert result.review.goal == "выбираю поставщика"
    assert result.review.snapshot_ids == [s.snapshot_id for s in (first, second, third)]
    data = json.dumps(harness.model.inputs(ReviewDraft)[-1]["approved_facts"], ensure_ascii=False)
    assert all(s.identity.inn in data for s in (first, second, third))


async def test_general_check_offline_keeps_selected_card_and_never_reasks_purpose(
    harness: SessionHarness,
) -> None:
    harness.settings = Settings(_env_file=None, llm_api_key=None)
    snapshot = harness.source.snapshots[0]
    await harness.run(snapshot.identity.inn)
    general = await harness.run("Общая проверка")
    assert general.status == "llm_unavailable" and general.snapshot is snapshot
    assert general.review.general_check and general.review.question is None
    assert general.review.asked_fields == ["goal"]
    assert not harness.model.calls and not harness.route_inputs


async def test_answered_question_cannot_be_repeated_by_review_planner(
    harness: SessionHarness,
) -> None:
    snapshot = harness.source.snapshots[0]
    await harness.run(snapshot.identity.inn)
    harness.plan = IntentPlan(
        action="ask", answer_mode="analysis", deal_patch=DealPatch(goal="выбираю поставщика")
    )
    harness.model.decide = lambda data: ReviewDecision(
        action="ask", question_field="goal", question="Для чего проверка?"
    )
    result = await harness.run("Я выбираю поставщика")
    assert result.status == "validation_failed" and result.review.question is None
    assert result.review.goal == "выбираю поставщика" and result.review.asked_fields == ["goal"]
    assert "goal" not in harness.model.inputs(ReviewDecision)[-1]["missing_fields"]


def _financial_draft(year: int, metrics: set[str]):
    def draft(data):
        facts = [
            fact
            for fact in data["approved_facts"]
            if fact["topic"] == "granular_metric"
            and fact["metric"] in metrics
            and f"за {year}:" in fact["text"]
        ]
        assert facts
        return ReviewDraft(
            blocks=[
                ReviewBlock(kind="fact", text=fact["text"], fact_ids=[fact["fact_id"]])
                for fact in facts[:8]
            ]
        )

    return draft


async def test_analysis_ids_support_single_company_previous_year_and_router_topics(
    harness: SessionHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = next(s for s in harness.source.snapshots if len(s.financial_statements or ()) >= 2)
    year = max(statement.year for statement in snapshot.financial_statements)
    await harness.run(snapshot.identity.inn)
    harness.plan = IntentPlan(
        action="ask", answer_mode="analysis", deal_patch=DealPatch(goal="выбираю поставщика")
    )
    harness.model.draft = _financial_draft(year, {"proceeds"})
    analyzed = await harness.run("Я выбираю поставщика, расскажи о выручке")
    assert analyzed.status == "answered"
    assert (await harness.state())["last_fact_ids"]
    review_calls = len(harness.model.calls)
    selected_periods = []

    async def select(settings, messages, client, **kwargs):
        payload = next(m["content"] for m in messages if m["role"] == "user")
        data = json.loads(payload.split("<INPUT_DATA>\n")[1].split("\n</INPUT_DATA>")[0])
        selected_periods.append(data["resolved_period"])
        assert all(fact["period"] == year - 1 for fact in data["approved_facts"])
        assert all(fact["metric"] == "proceeds" for fact in data["approved_facts"])
        return SimpleNamespace(
            answer=json.dumps(
                {
                    "status": "answered",
                    "fact_ids": [data["approved_facts"][0]["fact_id"]],
                }
            )
        )

    monkeypatch.setattr("counterparty_agent.ai.selector._request_completion", select)
    harness.plan = IntentPlan(action="ask", answer_mode="analysis")
    previous = await harness.run("А за предыдущий год?")
    assert previous.status == "answered" and previous.snapshot is snapshot
    assert selected_periods == [year - 1]
    assert len(harness.model.calls) == review_calls
    assert any(
        "proceeds" in topic and str(year) in topic
        for topic in harness.route_inputs[-1]["last_topics"]
    )
    state = json.dumps(await harness.state(), ensure_ascii=False)
    assert "выбираю поставщика" not in state and "Выручка" not in state


async def test_group_analysis_maps_financial_memory_without_enabling_another_matrix_year(
    harness: SessionHarness,
) -> None:
    first, second = harness.source.snapshots[:2]
    compared = await harness.run(f"{first.identity.inn}; {second.identity.inn}")
    year = compared.comparison.financial_year
    assert year is not None
    harness.plan = IntentPlan(
        action="ask",
        scope="group",
        answer_mode="analysis",
        deal_patch=DealPatch(goal="выбираю поставщика"),
    )
    harness.model.draft = _financial_draft(year, {"proceeds"})
    analyzed = await harness.run("Я выбираю поставщика, сравни выручку по группе")
    assert analyzed.status == "answered"
    state = await harness.state()
    # Для участника без выбранного финансового значения сохраняется ещё один
    # grounded-якорь покрытия, но новый финансовый год не открывается.
    assert 1 <= len(state["last_comparison_fact_ids"]) <= 2
    calls = len(harness.model.calls)
    harness.plan = IntentPlan(action="ask", scope="group", answer_mode="analysis")
    previous = await harness.run("А за предыдущий год?")
    assert previous.status == "insufficient_data" and not previous.answer_claims
    assert previous.comparison.financial_year == year
    assert len(harness.model.calls) == calls
    assert any(
        "comparison_financial:proceeds" in topic
        for topic in harness.route_inputs[-1]["last_topics"]
    )


async def test_ambiguous_previous_metric_and_complex_relative_analysis_are_not_guessed(
    harness: SessionHarness,
) -> None:
    snapshot = next(s for s in harness.source.snapshots if len(s.financial_statements or ()) >= 2)
    year = max(statement.year for statement in snapshot.financial_statements)
    await harness.run(snapshot.identity.inn)
    harness.plan = IntentPlan(
        action="ask", answer_mode="analysis", deal_patch=DealPatch(goal="выбираю поставщика")
    )
    harness.model.draft = _financial_draft(year, {"proceeds", "profit"})
    assert (
        await harness.run("Я выбираю поставщика, сравни выручку и прибыль")
    ).status == "answered"
    calls = len(harness.model.calls)
    harness.plan = IntentPlan(action="ask", answer_mode="analysis")
    assert (await harness.run("А за предыдущий год?")).status == "insufficient_data"
    complex_result = await harness.run("Проанализируй риски исполнения в предыдущем году")
    assert complex_result.status == "insufficient_data" and not complex_result.answer_claims
    assert len(harness.model.calls) == calls


async def test_card_number_control_keeps_original_group_position_without_routing(
    harness: SessionHarness,
) -> None:
    first, second = harness.source.snapshots[:2]
    await harness.run(f"{first.identity.inn}; {second.identity.inn}")
    result = await harness.run("Покажи карточку №2")
    assert result.focus_snapshot_id == second.snapshot_id
    assert result.snapshot is second and not harness.route_inputs
