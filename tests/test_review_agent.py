"""Условия сделки, адаптивный цикл и проверка связного ответа без сетевой модели."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim
from counterparty_agent.ai.deal import (
    DealContext,
    DealPatch,
    apply_deal,
    deal_facts,
    extract_deal,
    validate_deal,
)
from counterparty_agent.ai.reasoning import (
    GroundingVerdict,
    ReviewBlock,
    ReviewDecision,
    ReviewDraft,
    structured_call,
    synthesize,
    validate_draft,
)
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.workflow.review import review_catalog, run_review, validate_review_run


@pytest.fixture(scope="module")
def source() -> JsonCounterpartySource:
    path = Path(Settings().snapshot_json_path)
    if not path.is_file():
        pytest.skip("Реальный snapshot не настроен")
    return JsonCounterpartySource.from_path(path)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, llm_api_key=SecretStr("test-only"))


def purpose(advance: str = "аванс 80%") -> DealContext:
    return apply_deal(
        DealContext(),
        DealPatch(goal="выбираю поставщика", role="поставщика", advance=advance),
        f"Я выбираю поставщика, условия: {advance}.",
    )


class ReviewModel:
    """Подменяются лишь решения LLM; граф, каталог, расчёты и сборка ответа настоящие."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        decide: Callable[[dict[str, Any]], ReviewDecision] | None = None,
        draft: Callable[[dict[str, Any]], ReviewDraft] | None = None,
        verdict: GroundingVerdict | None = None,
    ) -> None:
        self.calls: list[tuple[type[Any], dict[str, Any]]] = []
        self.decide = decide or self.default_decision
        self.draft = draft or self.default_draft
        self.verdict = verdict or GroundingVerdict(unsupported_blocks=[], answers_question=True)
        monkeypatch.setattr("counterparty_agent.workflow.review.structured_call", self.call)
        monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", self.call)

    @staticmethod
    def default_decision(data: dict[str, Any]) -> ReviewDecision:
        return (
            ReviewDecision(
                action="read",
                topics=[
                    topic
                    for topic in ("company", "finance", "documents")
                    if topic in data["available_topics"]
                ],
            )
            if not data["read_topics"]
            else ReviewDecision(action="finish")
        )

    @staticmethod
    def default_draft(data: dict[str, Any]) -> ReviewDraft:
        fact = next(f for f in data["approved_facts"] if f["topic"] != "deal_context")
        return ReviewDraft(
            blocks=[ReviewBlock(kind="fact", text=fact["text"], fact_ids=[fact["fact_id"]])]
        )

    async def call(
        self,
        settings: Any,
        client: Any,
        question: str,
        data: dict[str, Any],
        prompt: str,
        schema: type[Any],
    ) -> Any:
        self.calls.append((schema, json.loads(json.dumps(data))))
        if schema is ReviewDecision:
            return self.decide(data)
        if schema is ReviewDraft:
            return self.draft(data)
        if schema is GroundingVerdict:
            return self.verdict
        raise AssertionError("Неожиданный дополнительный вызов модели")

    def inputs(self, schema: type[Any]) -> list[dict[str, Any]]:
        return [data for kind, data in self.calls if kind is schema]


def test_deal_update_is_literal_revisioned_and_replaces_payment_origin() -> None:
    original = purpose()
    old_id = original.terms["advance"].evidence_id
    unchanged = apply_deal(original, DealPatch(), "Какие риски?")
    assert unchanged == original and unchanged is not original
    updated = apply_deal(
        original, DealPatch(advance="оплата после поставки"), "оплата после поставки"
    )
    assert original.advance == "аванс 80%"
    assert (
        updated.goal == original.goal and updated.context_revision == original.context_revision + 1
    )
    assert updated.terms["advance"].evidence_id != old_id
    facts = deal_facts(updated)
    assert all(old_id not in fact.claim.evidence_ids for fact in facts)
    assert all("аванс 80%" not in fact.claim.text for fact in facts)
    assert all("Со слов пользователя" in fact.claim.text for fact in facts)
    assert apply_deal(updated, DealPatch(advance=updated.advance), updated.advance) == updated


@pytest.mark.parametrize("value", ["аванс 20%", " ", "сумма неизвестна"])
def test_deal_rejects_invented_or_empty_quote(value: str) -> None:
    with pytest.raises(ValueError, match="цитат"):
        apply_deal(purpose(), DealPatch(advance=value), "Какие риски при авансе 80%?")


def test_deal_rejects_tampered_provenance_and_orphaned_fact() -> None:
    tampered = purpose()
    tampered.terms["advance"].evidence_id = "deal_wrong"
    with pytest.raises(ValueError):
        validate_deal(tampered)
    orphaned = purpose()
    orphaned.advance = None
    with pytest.raises(ValueError):
        deal_facts(orphaned)


def test_general_check_is_not_inferred_from_a_substring_of_an_unrelated_word() -> None:
    with pytest.raises(ValueError):
        apply_deal(purpose(), DealPatch(general_check=True), "Сообщите риски компании")


async def test_deal_extractor_repairs_unquoted_terms_and_keeps_prior_data_on_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = [DealPatch(advance="аванс 50%"), DealPatch(advance="оплата после поставки")]
    calls: list[Any] = []

    async def completion(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return SimpleNamespace(answer=replies[min(len(calls) - 1, 1)].model_dump_json())

    monkeypatch.setattr("counterparty_agent.ai.deal._request_completion", completion)
    original = purpose()
    updated = await extract_deal(
        settings, "Теперь оплата после поставки", original, client=object()
    )
    assert len(calls) == 2 and updated.advance == "оплата после поставки"
    assert original.advance == "аванс 80%"
    calls.clear()
    replies[:] = [DealPatch(advance="аванс 50%"), DealPatch(advance="аванс 50%")]
    refused = await extract_deal(settings, "Какие сведения нужны?", original, client=object())
    assert refused == original and len(calls) == 2


async def test_general_check_works_offline_without_erasing_terms() -> None:
    original = purpose()
    updated = await extract_deal(
        Settings(_env_file=None, llm_api_key=None), "Общая проверка", original, client=None
    )
    assert updated.general_check and updated.advance == original.advance
    assert updated.context_revision == original.context_revision + 1
    assert not original.general_check


async def test_structured_call_repairs_schema_but_not_by_executing_model_text(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = ['{"action":"run_shell","command":"whoami"}', '{"action":"finish"}']
    calls: list[Any] = []

    async def completion(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return SimpleNamespace(answer=payloads[len(calls) - 1])

    monkeypatch.setattr("counterparty_agent.ai.reasoning._request_completion", completion)
    result = await structured_call(settings, object(), "Проверить", {}, "JSON", ReviewDecision)
    assert result.action == "finish" and len(calls) == 2
    schema_text = calls[0][1][0]["content"].split("Точная JSON-схема ответа: ", 1)[1]
    assert json.loads(schema_text) == ReviewDecision.model_json_schema()


@pytest.mark.parametrize(
    "text,ids", [("Число 999999", ["known"]), ("Факт", ["foreign"]), ("Без риска", ["known"])]
)
def test_draft_rejects_unknown_evidence_new_numbers_and_guarantees(
    text: str, ids: list[str]
) -> None:
    catalog = {
        "known": ApprovedFact(
            "known", GroundedClaim(text="Аванс 80%.", evidence_ids=("e",)), "deal_context"
        )
    }
    draft = ReviewDraft(blocks=[ReviewBlock(kind="fact", text=text, fact_ids=ids)])
    with pytest.raises(ValueError):
        validate_draft(draft, catalog)


def test_safe_disclaimer_is_not_mistaken_for_a_guarantee() -> None:
    text = "Оценка не гарантирует безопасность сделки."
    fact = ApprovedFact("known", GroundedClaim(text=text, evidence_ids=("e",)), "bank_signal")
    validate_draft(
        ReviewDraft(blocks=[ReviewBlock(kind="limitation", text=text, fact_ids=["known"])]),
        {"known": fact},
    )


async def test_read_findings_change_next_step_and_stop_with_grounded_answer(
    source: JsonCounterpartySource, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = next(
        s
        for s in source.snapshots
        if any((f.profit or 0) < 0 for f in s.financial_statements or ())
    )
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))

    def decide(data: dict[str, Any]) -> ReviewDecision:
        if not data["read_topics"]:
            assert all(f["topic"] == "deal_context" for f in data["approved_facts"])
            return ReviewDecision(action="read", topics=["finance"])
        if "enforcement" not in data["read_topics"]:
            assert any(f["metric"] == "financial_loss" for f in data["approved_facts"])
            return ReviewDecision(action="read", topics=["enforcement"])
        return ReviewDecision(action="finish")

    model = ReviewModel(monkeypatch, decide=decide)
    run = await run_review(
        settings, "Какие риски предоплаты?", (snapshot,), (analysis,), purpose(), client=object()
    )
    assert run.answer.status == "answered"
    assert run.steps == ["Проверено: финансы", "Проверено: взыскания"]
    assert len(model.inputs(ReviewDecision)) == 3
    assert len(model.inputs(GroundingVerdict)) == 1
    validate_review_run(run)


@pytest.mark.parametrize("stop_early", [False, True])
async def test_review_reads_before_finishing_and_stops_after_four_decisions(
    source: JsonCounterpartySource,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    stop_early: bool,
) -> None:
    snapshot = source.snapshots[0]
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))

    def decide(data: dict[str, Any]) -> ReviewDecision:
        if stop_early:
            return ReviewDecision(action="finish")
        return ReviewDecision(action="read", topics=[data["available_topics"][0]])

    model = ReviewModel(monkeypatch, decide=decide)
    run = await run_review(
        settings, "Общая проверка", (snapshot,), (analysis,), purpose(), client=object()
    )
    assert run.answer.status == "answered" and run.steps
    assert len(model.inputs(ReviewDecision)) == (2 if stop_early else 4)
    assert len(model.inputs(ReviewDraft)) == 1


async def test_payment_change_replans_and_regenerates_the_conclusion(
    source: JsonCounterpartySource, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = source.snapshots[0]
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))

    def decide(data: dict[str, Any]) -> ReviewDecision:
        if data["read_topics"]:
            return ReviewDecision(action="finish")
        return ReviewDecision(
            action="read",
            topics=["finance"] if data["current_deal"]["advance"] == "аванс 80%" else ["company"],
        )

    def draft(data: dict[str, Any]) -> ReviewDraft:
        payment = next(
            f
            for f in data["approved_facts"]
            if f["topic"] == "deal_context" and f["metric"] == "advance"
        )
        report = next(f for f in data["approved_facts"] if f["topic"] != "deal_context")
        action = (
            "При авансе 80% запросите подтверждение исполнения до перечисления денег."
            if data["current_deal"]["advance"] == "аванс 80%"
            else "По вашим условиям оплата после поставки: подтвердите порядок приёмки до оплаты."
        )
        return ReviewDraft(
            blocks=[
                ReviewBlock(kind="fact", text=report["text"], fact_ids=[report["fact_id"]]),
                ReviewBlock(kind="action", text=action, fact_ids=[payment["fact_id"]]),
            ]
        )

    model = ReviewModel(monkeypatch, decide=decide, draft=draft)
    first = await run_review(
        settings, "Проверь условия", (snapshot,), (analysis,), purpose(), client=object()
    )
    changed = apply_deal(
        first.deal, DealPatch(advance="оплата после поставки"), "Теперь оплата после поставки"
    )
    second = await run_review(
        settings, "Что меняется?", (snapshot,), (analysis,), changed, client=object()
    )
    assert first.answer.status == second.answer.status == "answered"
    assert first.steps == ["Проверено: финансы"]
    assert second.steps == ["Проверено: статус компании"]
    assert "авансе 80%" in first.answer.answer and "порядок приёмки" in second.answer.answer
    assert "80%" not in second.answer.answer
    assert len(model.inputs(ReviewDraft)) == len(model.inputs(GroundingVerdict)) == 2


async def test_two_questions_max_and_answered_fields_are_not_asked_again(
    source: JsonCounterpartySource, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = source.snapshots[0]
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))
    deal = purpose()
    requested = ["amount"]
    model = ReviewModel(
        monkeypatch,
        decide=lambda data: ReviewDecision(
            action="ask", question_field=requested[0], question="Уточните условие?"
        ),
    )
    first = await run_review(settings, "Начать", (snapshot,), (analysis,), deal, client=object())
    assert first.deal.asked_fields == ["amount"] and first.deal.question
    assert not deal.asked_fields
    answered = apply_deal(first.deal, DealPatch(amount="2 млн рублей"), "2 млн рублей")
    requested[0] = "deadline"
    second = await run_review(
        settings, "Дальше", (snapshot,), (analysis,), answered, client=object()
    )
    assert second.deal.asked_fields == ["amount", "deadline"]
    data = model.inputs(ReviewDecision)[-1]
    assert "amount" not in data["missing_fields"] and "advance" not in data["missing_fields"]
    assert data["questions_left"] == 1
    answered = apply_deal(second.deal, DealPatch(deadline="30 дней"), "30 дней")
    requested[0] = "subject"
    third = await run_review(settings, "Ещё", (snapshot,), (analysis,), answered, client=object())
    assert model.inputs(ReviewDecision)[-1]["questions_left"] == 0
    assert third.answer.status == "validation_failed" and third.deal.question is None
    assert third.deal.asked_fields == ["amount", "deadline"]


async def test_general_check_rejects_followup_question_and_offline_never_calls_model(
    source: JsonCounterpartySource, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = source.snapshots[0]
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))
    deal = apply_deal(purpose(), DealPatch(general_check=True), "Общая проверка")
    model = ReviewModel(
        monkeypatch,
        decide=lambda data: ReviewDecision(
            action="ask", question_field="amount", question="Сумма?"
        ),
    )
    rejected = await run_review(settings, "Начать", (snapshot,), (analysis,), deal, client=object())
    assert rejected.answer.status == "validation_failed" and not rejected.deal.question
    assert not rejected.deal.asked_fields
    model.calls.clear()
    offline = await run_review(
        Settings(_env_file=None, llm_api_key=None),
        "Начать",
        (snapshot,),
        (analysis,),
        deal,
        client=None,
    )
    assert offline.answer.status == "llm_unavailable" and not offline.answer.used_llm
    assert not model.calls and offline.deal == deal


async def test_document_read_is_forbidden_without_an_uploaded_document(
    source: JsonCounterpartySource, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = source.snapshots[0]
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))
    model = ReviewModel(
        monkeypatch, decide=lambda data: ReviewDecision(action="read", topics=["documents"])
    )
    run = await run_review(
        settings, "Что в договоре?", (snapshot,), (analysis,), purpose(), client=object()
    )
    assert "documents" not in model.inputs(ReviewDecision)[0]["available_topics"]
    assert run.answer.status == "validation_failed" and not run.answer.claims
    assert not model.inputs(ReviewDraft) and not run.steps


async def test_report_and_contract_synthesis_preserves_both_sources_and_user_conditions(
    source: JsonCounterpartySource, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = source.snapshots[0]
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))
    doc = ApprovedFact(
        "contract_1",
        GroundedClaim(
            text="В документе указано: аванс 50%.", evidence_ids=("document_fragment_1",)
        ),
        "document",
    )

    def draft(data: dict[str, Any]) -> ReviewDraft:
        report = next(
            f for f in data["approved_facts"] if f["topic"] == "bank_signal" and f["metric"] is None
        )
        term = next(
            f
            for f in data["approved_facts"]
            if f["topic"] == "deal_context" and f["metric"] == "advance"
        )
        document = next(f for f in data["approved_facts"] if f["topic"] == "document")
        return ReviewDraft(
            blocks=[
                ReviewBlock(kind="fact", text=report["text"], fact_ids=[report["fact_id"]]),
                ReviewBlock(
                    kind="interpretation",
                    text="В документе аванс 50%, по вашим условиям — 80%. "
                    "Условия расходятся; уточните актуальную версию.",
                    fact_ids=[document["fact_id"], term["fact_id"]],
                ),
            ]
        )

    model = ReviewModel(monkeypatch, draft=draft)
    run = await run_review(
        settings,
        "Сопоставь отчёт и договор с моими условиями",
        (snapshot,),
        (analysis,),
        purpose(),
        client=object(),
        extra_facts=(doc,),
    )
    assert run.answer.status == "answered"
    assert "document_fragment_1" in run.answer.claims[1].evidence_ids
    assert run.deal.terms["advance"].evidence_id in run.answer.claims[1].evidence_ids
    assert analysis.bank_evidence_id in run.answer.claims[0].evidence_ids
    assert "contract_1" in run.answer.fact_ids
    checked = model.inputs(GroundingVerdict)[0]
    assert checked["current_deal"]["advance"] == "аванс 80%"
    assert len(checked["blocks"][1]["fact_ids"]) == 2
    assert checked["approved_facts"]
    validate_review_run(run)


@pytest.mark.parametrize(
    "verdict",
    [
        GroundingVerdict(unsupported_blocks=[0], answers_question=True),
        GroundingVerdict(unsupported_blocks=[], answers_question=False),
    ],
)
async def test_unsupported_or_irrelevant_synthesis_never_reaches_user(
    source: JsonCounterpartySource,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    verdict: GroundingVerdict,
) -> None:
    snapshot = source.snapshots[0]
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))
    model = ReviewModel(monkeypatch, verdict=verdict)
    run = await run_review(
        settings, "Проанализируй", (snapshot,), (analysis,), purpose(), client=object()
    )
    assert run.answer.status == "validation_failed" and not run.answer.claims
    assert len(model.inputs(ReviewDraft)) == len(model.inputs(GroundingVerdict)) == 2


async def test_unknown_fact_or_number_is_rejected_before_semantic_verifier(
    source: JsonCounterpartySource, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = source.snapshots[0]
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))
    model = ReviewModel(
        monkeypatch,
        draft=lambda data: ReviewDraft(
            blocks=[ReviewBlock(kind="fact", text="Неизвестный факт", fact_ids=["invented"])]
        ),
    )
    catalog, _ = review_catalog((snapshot,), (analysis,), purpose())
    with pytest.raises(ValueError):
        await synthesize(settings, object(), "Проверить", purpose(), catalog, "Выборка")
    assert len(model.inputs(ReviewDraft)) == 2
    assert not model.inputs(GroundingVerdict)


@pytest.mark.parametrize("field", ["answer", "text", "evidence"])
async def test_review_projection_rejects_text_or_citation_substitution(
    source: JsonCounterpartySource,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    snapshot = source.snapshots[0]
    analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=1))
    ReviewModel(monkeypatch)
    run = await run_review(
        settings, "Проверь компанию", (snapshot,), (analysis,), purpose(), client=object()
    )
    assert run.answer.status == "answered"
    if field == "answer":
        run.answer = replace(run.answer, answer=run.answer.answer + " Непроверенное дополнение.")
    else:
        claim = run.answer.claims[0]
        changed = claim.model_copy(
            update={
                "text" if field == "text" else "evidence_ids": "Факт: Подменённый вывод"
                if field == "text"
                else ("foreign_evidence",)
            }
        )
        run.answer = replace(run.answer, claims=(changed, *run.answer.claims[1:]))
    with pytest.raises(ValueError):
        validate_review_run(run)


def scoring_facts() -> dict[str, ApprovedFact]:
    return {
        "canonical_bank": ApprovedFact(
            "canonical_bank",
            GroundedClaim(
                text="Оценка в отчёте: YELLOW — требует внимания.", evidence_ids=("bank_evidence",)
            ),
            "bank_signal",
        ),
        "canonical_loss": ApprovedFact(
            "canonical_loss",
            GroundedClaim(text="В отчёте указан убыток.", evidence_ids=("loss_evidence",)),
            "attention_signal",
        ),
    }


@pytest.mark.parametrize("citation", ["[F1]", "(F1)", "[F1, F2]", "F1", "F1 F2"])
async def test_short_aliases_are_remapped_and_not_rendered_as_inline_technical_ids(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, citation: str
) -> None:
    catalog = scoring_facts()

    def draft(data: dict[str, Any]) -> ReviewDraft:
        assert [fact["fact_id"] for fact in data["approved_facts"]] == ["F1", "F2"]
        return ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind="fact", text=f"Оценка в отчёте: YELLOW {citation}.", fact_ids=["F1"]
                )
            ]
        )

    model = ReviewModel(monkeypatch, draft=draft)
    answer, verified = await synthesize(
        settings, object(), "Какая оценка?", purpose(), catalog, "Оценка"
    )
    assert answer.fact_ids == ("canonical_bank",)
    assert answer.claims[0].evidence_ids == ("bank_evidence",)
    assert verified.blocks[0].fact_ids == ["canonical_bank"]
    assert answer.answer == "Факт: Оценка в отчёте: YELLOW."
    assert all(alias not in answer.answer for alias in ("F1", "F2", "canonical_bank"))
    check = model.inputs(GroundingVerdict)[0]["blocks"][0]
    assert check["text"] == "Оценка в отчёте: YELLOW."
    assert check["fact_ids"] == ["F1"]
    all_facts = model.inputs(GroundingVerdict)[0]["approved_facts"]
    assert [fact["text"] for fact in all_facts] == [fact.claim.text for fact in catalog.values()]


@pytest.mark.parametrize("reference", ["F999", "canonical_bank"])
async def test_unknown_or_internal_reference_in_prose_does_not_reach_verifier(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, reference: str
) -> None:
    model = ReviewModel(
        monkeypatch,
        draft=lambda data: ReviewDraft(
            blocks=[ReviewBlock(kind="fact", text=f"Оценка YELLOW {reference}.", fact_ids=["F1"])]
        ),
    )
    with pytest.raises(ValueError):
        await synthesize(settings, object(), "Какая оценка?", purpose(), scoring_facts(), "Оценка")
    assert len(model.inputs(ReviewDraft)) == 2 and not model.inputs(GroundingVerdict)


async def test_literal_f1_from_cited_source_is_not_silently_removed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = {
        "company": ApprovedFact(
            "company",
            GroundedClaim(text="Название компании: F1.", evidence_ids=("name",)),
            "company",
        )
    }
    model = ReviewModel(monkeypatch)
    answer, _ = await synthesize(settings, object(), "Название?", purpose(), catalog, "Название")
    assert answer.answer == "Факт: Название компании: F1."
    assert model.inputs(GroundingVerdict)[0]["blocks"][0]["text"] == "Название компании: F1."


@pytest.mark.parametrize("wrong_id", ["F999", "canonical_bank"])
async def test_unknown_or_non_alias_id_is_rejected_before_verifier(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, wrong_id: str
) -> None:
    model = ReviewModel(
        monkeypatch,
        draft=lambda data: ReviewDraft(
            blocks=[ReviewBlock(kind="fact", text="Оценка YELLOW.", fact_ids=[wrong_id])]
        ),
    )
    with pytest.raises(ValueError):
        await synthesize(settings, object(), "Какая оценка?", purpose(), scoring_facts(), "Оценка")
    assert len(model.inputs(ReviewDraft)) == 2 and not model.inputs(GroundingVerdict)


@pytest.mark.parametrize("text", ["YELLOW из-за убытков.", "Цвет YELLOW обусловлен убытком."])
async def test_causal_scoring_explanation_is_rejected_even_if_verifier_would_approve(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    model = ReviewModel(
        monkeypatch,
        draft=lambda data: ReviewDraft(
            blocks=[ReviewBlock(kind="interpretation", text=text, fact_ids=["F1", "F2"])]
        ),
        verdict=GroundingVerdict(unsupported_blocks=[], answers_question=True),
    )
    with pytest.raises(ValueError):
        await synthesize(
            settings, object(), "Почему YELLOW?", purpose(), scoring_facts(), "Оценка и убыток"
        )
    assert len(model.inputs(ReviewDraft)) == 2 and not model.inputs(GroundingVerdict)


async def test_independent_scoring_and_loss_blocks_remain_allowed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = ReviewModel(
        monkeypatch,
        draft=lambda data: ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind="fact", text="Оценка в отчёте: YELLOW — требует внимания.", fact_ids=["F1"]
                ),
                ReviewBlock(kind="fact", text="Отдельно в отчёте указан убыток.", fact_ids=["F2"]),
            ]
        ),
    )
    answer, draft = await synthesize(
        settings, object(), "Какие сведения есть?", purpose(), scoring_facts(), "Оценка и убыток"
    )
    assert answer.status == "answered" and len(model.inputs(GroundingVerdict)) == 1
    assert [block.fact_ids for block in draft.blocks] == [["canonical_bank"], ["canonical_loss"]]
    assert [claim.evidence_ids for claim in answer.claims] == [
        ("bank_evidence",),
        ("loss_evidence",),
    ]


@pytest.mark.parametrize(
    "explanation",
    ["Это из-за убытков.", "Такая оценка объясняется убытком.", "Причина — убытки."],
)
async def test_bank_causality_cannot_be_split_between_blocks(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, explanation: str
) -> None:
    model = ReviewModel(
        monkeypatch,
        draft=lambda data: ReviewDraft(
            blocks=[
                ReviewBlock(kind="fact", text="Оценка YELLOW.", fact_ids=["F1"]),
                ReviewBlock(kind="interpretation", text=explanation, fact_ids=["F2"]),
            ]
        ),
        verdict=GroundingVerdict(unsupported_blocks=[], answers_question=True),
    )
    with pytest.raises(ValueError):
        await synthesize(
            settings, object(), "Почему YELLOW?", purpose(), scoring_facts(), "Оценка и убыток"
        )
    assert len(model.inputs(ReviewDraft)) == 2 and not model.inputs(GroundingVerdict)


@pytest.mark.parametrize(
    "analysis",
    [
        "Риск предоплаты связан с исполнением поставки.",
        "Оценка риска сделки связана с условиями оплаты.",
        "Убыток не объясняет цвет оценки.",
        "Причина этой оценки в отчёте не указана.",
    ],
)
def test_bank_guard_allows_independent_risk_reasoning_and_unknown_reason(analysis: str) -> None:
    catalog = scoring_facts()
    catalog["support"] = ApprovedFact(
        "support",
        GroundedClaim(text=analysis, evidence_ids=("support_evidence",)),
        "attention_signal",
    )
    validate_draft(
        ReviewDraft(
            blocks=[
                ReviewBlock(kind="fact", text="Оценка YELLOW.", fact_ids=["canonical_bank"]),
                ReviewBlock(kind="interpretation", text=analysis, fact_ids=["support"]),
            ]
        ),
        catalog,
    )


@pytest.mark.parametrize(
    ("source_text", "output"),
    [
        ("Прибыль: -100.", "Прибыль: 100."),
        ("Прибыль: −100.", "Положительная прибыль: 100."),
        ("Прибыль: -100.", "Прибыль: +100."),
        ("Прибыль: минус 100.", "Прибыль: плюс 100."),
        ("Прибыль: 100.", "Прибыль: -100."),
    ],
)
def test_numeric_grounding_rejects_sign_changes(source_text: str, output: str) -> None:
    catalog = {
        "profit": ApprovedFact(
            "profit", GroundedClaim(text=source_text, evidence_ids=("profit",)), "finance"
        )
    }
    with pytest.raises(ValueError, match="знак"):
        validate_draft(
            ReviewDraft(blocks=[ReviewBlock(kind="fact", text=output, fact_ids=["profit"])]),
            catalog,
        )


@pytest.mark.parametrize(
    ("source_text", "output"),
    [
        ("Прибыль: -100.", "Прибыль: −100."),
        ("Прибыль: -100.", "Прибыль: минус 100."),
        ("Прибыль: 100.", "Прибыль: +100."),
        ("Прибыль: -100.50.", "Прибыль: −100,50."),
        ("Проверено 2026-09-04T00:00:00Z. Прибыль -100.", "На 2026-09-04 прибыль −100."),
    ],
)
def test_numeric_grounding_preserves_equivalent_signs_and_calendar_dates(
    source_text: str, output: str
) -> None:
    catalog = {
        "profit": ApprovedFact(
            "profit", GroundedClaim(text=source_text, evidence_ids=("profit",)), "finance"
        )
    }
    validate_draft(
        ReviewDraft(blocks=[ReviewBlock(kind="fact", text=output, fact_ids=["profit"])]), catalog
    )


async def test_numeric_repair_suggests_condition_source_but_model_must_fix_its_reference(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = apply_deal(purpose(), DealPatch(deadline="30 дней"), "Срок поставки — 30 дней.")
    deadline = next(fact for fact in deal_facts(context) if fact.metric == "deadline")
    catalog = {"canonical_bank": scoring_facts()["canonical_bank"], deadline.fact_id: deadline}

    def draft(data: dict[str, Any]) -> ReviewDraft:
        assert data["condition_fact_ids"] == {"deadline": "F2"}
        if "previous_draft" not in data:
            assert "number_source_candidates" not in data
            fact_ids = ["F1"]
        else:
            assert data["previous_draft"]["blocks"][0]["fact_ids"] == ["F1"]
            assert data["number_source_candidates"] == [
                {"block": 0, "number": "30", "candidate_fact_ids": ["F2"]}
            ]
            # Исправляет именно модель: подсказка не дописывает источник к первому ответу.
            fact_ids = [data["condition_fact_ids"]["deadline"]]
        return ReviewDraft(
            blocks=[
                ReviewBlock(
                    kind="fact", text="По вашим условиям срок — 30 дней.", fact_ids=fact_ids
                )
            ]
        )

    model = ReviewModel(monkeypatch, draft=draft)
    answer, verified = await synthesize(
        settings, object(), "Какой срок?", context, catalog, "Условия пользователя"
    )
    assert [schema for schema, _ in model.calls] == [ReviewDraft, ReviewDraft, GroundingVerdict]
    assert verified.blocks[0].fact_ids == [deadline.fact_id]
    assert answer.fact_ids == (deadline.fact_id,)
    assert answer.claims[0].evidence_ids == deadline.claim.evidence_ids
    checked = model.inputs(GroundingVerdict)[0]
    assert checked["blocks"][0]["fact_ids"] == ["F2"]
    assert next(f["text"] for f in checked["approved_facts"] if f["fact_id"] == "F2") == (
        deadline.claim.text
    )


async def test_repair_preserves_approved_blocks_and_verifier_sees_uncited_facts(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"draft": 0, "verify": 0}

    async def complete(settings, client, question, data, prompt, schema):
        if schema is ReviewDraft:
            calls["draft"] += 1
            if calls["draft"] == 2:
                assert data["repair_block_indices"] == [1]
            return ReviewDraft(
                blocks=[
                    ReviewBlock(
                        kind="fact",
                        text="Оценка YELLOW." if calls["draft"] == 1 else "Оценка RED.",
                        fact_ids=["F1"],
                    ),
                    ReviewBlock(
                        kind="interpretation",
                        text="Требуется проверка обстоятельств."
                        if calls["draft"] == 1
                        else "В отчёте указан убыток.",
                        fact_ids=["F2"],
                    ),
                ]
            )
        assert schema is GroundingVerdict
        calls["verify"] += 1
        # Повторная генерация не подменяет уже проверенный цвет.
        assert data["blocks"][0]["text"] == "Оценка YELLOW."
        # Даже не выбранный автором факт доступен для проверки противоречий.
        assert len(data["approved_facts"]) == 3
        return GroundingVerdict(
            unsupported_blocks=[1] if calls["verify"] == 1 else [],
            answers_question=True,
            reasons=["Уточни обстоятельство"] if calls["verify"] == 1 else [],
        )

    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", complete)
    catalog = scoring_facts()
    catalog["later"] = ApprovedFact(
        "later",
        GroundedClaim(text="Капитал за 2025 год положительный.", evidence_ids=("later_capital",)),
        "financial",
    )
    answer, _ = await synthesize(settings, object(), "Что важно?", purpose(), catalog, "Выборка")
    assert calls == {"draft": 2, "verify": 2}
    assert "RED" not in answer.answer
    assert answer.fact_ids == ("canonical_bank", "canonical_loss")
