"""Модульные тесты адаптера провайдер без API-ключа и сетевых запросов."""

import asyncio
import json
import logging
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.comparison_catalog import build_comparison_fact_catalog
from counterparty_agent.ai.contracts import (
    GroundedAnswer,
    GroundedClaim,
    LlmContextLimitError,
    LlmInvalidResponseError,
)
from counterparty_agent.ai.selector import answer_comparison_question, answer_question
from counterparty_agent.ai.topics import needs_attention_explanation
from counterparty_agent.ai.transport import build_messages, create_client, generate_answer
from counterparty_agent.ai.validation import validate_comparison_answer, validate_grounded_answer
from counterparty_agent.analytics.comparison import compare_snapshots
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import (
    AnalysisResult,
    ComparisonResult,
    CounterpartySnapshot,
    FindingDataStatus,
    FindingSeverity,
)


class _FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(
            model="qwen3.7-plus",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Данных недостаточно."),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=25, completion_tokens=4),
        )


def test_build_messages_separates_data_from_rules() -> None:
    messages = build_messages(
        "Какие риски?",
        {"company": "Демо", "evidence_id": "status"},
        [("user", "Продолжим"), ("assistant", "Да")],
    )

    assert messages[0]["role"] == "system"
    assert "<INPUT_DATA>" in messages[-1]["content"]
    assert '"evidence_id":"status"' in messages[-1]["content"]
    assert "<QUESTION>\nКакие риски?" in messages[-1]["content"]


def test_generate_answer_uses_confirmed_dslab_parameters() -> None:
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = SimpleNamespace(
        llm_model="qwen3.7-plus",
        llm_temperature=0.1,
        llm_max_tokens=1200,
        llm_reasoning_enabled=False,
    )

    result = asyncio.run(
        generate_answer(settings, "Что известно?", {"status": "ACTIVE"}, client=client)
    )

    assert result.answer == "Данных недостаточно."
    assert completions.kwargs["model"] == "qwen3.7-plus"
    assert completions.kwargs["extra_body"] == {"reasoning": {"enabled": False}}


@pytest.fixture(scope="module")
def source() -> JsonCounterpartySource:
    """Использовать выданные карточки без сохранения их копии в репозитории."""

    path = Path(Settings().snapshot_json_path)
    if not path.is_file():
        pytest.skip("Реальный snapshot не настроен в COUNTERPARTY_SNAPSHOT_JSON_PATH")
    return JsonCounterpartySource.from_path(path)


@pytest.fixture(scope="module")
def company(source: JsonCounterpartySource) -> tuple[CounterpartySnapshot, AnalysisResult]:
    snapshot = next(
        item
        for item in source.snapshots
        if item.financial_statements and any(row.proceeds for row in item.financial_statements)
    )
    return snapshot, analyze_snapshot(
        snapshot, evaluated_at=snapshot.report_at + timedelta(days=30)
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(llm_api_key=SecretStr("unit-test-not-a-real-key"), _env_file=None)


class _ScriptedClient:
    """Управляемые ответы транспортного двойника, не компании и не отчёта."""

    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.closed = 0
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(json.loads(json.dumps(kwargs)))
        value = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, SimpleNamespace):
            return value
        return _completion(value)

    async def close(self) -> None:
        self.closed += 1


def _completion(text: object, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        model="qwen3.7-plus",
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish_reason)
        ],
        usage=None,
    )


def _selection(*fact_ids: str, status: str = "answered") -> str:
    return json.dumps({"status": status, "fact_ids": fact_ids})


def _context(call: dict[str, Any]) -> dict[str, Any]:
    content = call["messages"][1]["content"]
    return json.loads(content.split("<INPUT_DATA>\n", 1)[1].split("\n</INPUT_DATA>", 1)[0])


@pytest.fixture
def attention_company(
    source: JsonCounterpartySource,
) -> tuple[CounterpartySnapshot, AnalysisResult]:
    for snapshot in source.snapshots:
        analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=30))
        if any(item.severity is FindingSeverity.ATTENTION for item in analysis.findings):
            return snapshot, analysis
    pytest.fail("В подключённой выборке нет компании с отдельным сигналом внимания")


@pytest.mark.parametrize(
    "question",
    [
        "А почему 1 требует внимания?",
        "Почему первая жёлтая?",
        "Из-за чего у второй красный цвет? Объясни",
        "Что настораживает у компании №1?",
        "Что не так с первой?",
        "Какие сигналы внимания у неё?",
    ],
)
async def test_attention_question_requires_bank_boundary_and_independent_signal(
    settings: Settings,
    attention_company: tuple[CounterpartySnapshot, AnalysisResult],
    question: str,
) -> None:
    snapshot, analysis = attention_company
    catalog = build_fact_catalog(snapshot, analysis)
    bank = next(item for item in catalog if item.topic == "bank_signal")
    signal = next(item for item in catalog if item.topic == "attention_signal")
    client = _ScriptedClient(_selection(bank.fact_id), _selection(bank.fact_id, signal.fact_id))
    result = await answer_question(settings, question, snapshot, analysis, client=client)
    assert result.status == "answered" and result.used_llm
    assert len(client.calls) == 2
    assert result.fact_ids == (bank.fact_id, signal.fact_id)
    assert "не объяснение банковского цвета" in result.answer
    assert "методика и причины не раскрыты" in result.answer
    finding = next(
        item
        for item in analysis.findings
        if item.statement in signal.claim.text and item.evidence_ids == signal.claim.evidence_ids
    )
    assert finding.severity is FindingSeverity.ATTENTION
    payload = _context(client.calls[0])
    assert payload["answer_mode"] == "attention_explanation"
    assert {item["topic"] for item in payload["approved_facts"]} == {
        "bank_signal",
        "attention_signal",
    }
    validate_grounded_answer(result, snapshot, analysis)


@pytest.mark.parametrize("selected_topic", ["bank_signal", "attention_signal", "report_date"])
async def test_attention_answer_cannot_omit_boundary_or_signals_or_choose_unrelated_fact(
    settings: Settings,
    attention_company: tuple[CounterpartySnapshot, AnalysisResult],
    selected_topic: str,
) -> None:
    snapshot, analysis = attention_company
    fact = next(
        item for item in build_fact_catalog(snapshot, analysis) if item.topic == selected_topic
    )
    client = _ScriptedClient(_selection(fact.fact_id))
    result = await answer_question(
        settings, "Почему компания требует внимания?", snapshot, analysis, client=client
    )
    assert result.status == "validation_failed" and not result.claims
    assert len(client.calls) == 2


async def test_short_why_uses_bank_topic_from_same_company_only(
    settings: Settings,
    attention_company: tuple[CounterpartySnapshot, AnalysisResult],
) -> None:
    snapshot, analysis = attention_company
    catalog = build_fact_catalog(snapshot, analysis)
    bank = next(item for item in catalog if item.topic == "bank_signal")
    signal = next(item for item in catalog if item.topic == "attention_signal")
    client = _ScriptedClient(_selection(bank.fact_id, signal.fact_id))
    result = await answer_question(
        settings, "А почему?", snapshot, analysis, (bank.fact_id, "foreign_fact"), client=client
    )
    assert result.status == "answered"
    assert _context(client.calls[0])["previous_fact_ids"] == [bank.fact_id]
    assert _context(client.calls[0])["answer_mode"] == "attention_explanation"
    assert not needs_attention_explanation("А почему?", ())
    assert not needs_attention_explanation("Почему упала выручка?", (bank,))
    assert not needs_attention_explanation("Какой цвет светофора?", (bank,))
    assert not needs_attention_explanation("А почему?", (signal,))


async def test_attention_answer_always_starts_with_bank_boundary(
    settings: Settings,
    attention_company: tuple[CounterpartySnapshot, AnalysisResult],
) -> None:
    snapshot, analysis = attention_company
    catalog = build_fact_catalog(snapshot, analysis)
    bank = next(item for item in catalog if item.topic == "bank_signal")
    signal = next(item for item in catalog if item.topic == "attention_signal")
    result = await answer_question(
        settings,
        "Почему жёлтая?",
        snapshot,
        analysis,
        client=_ScriptedClient(_selection(signal.fact_id, bank.fact_id)),
    )
    assert result.fact_ids == (bank.fact_id, signal.fact_id)
    validate_grounded_answer(result, snapshot, analysis)


async def test_attention_history_does_not_invent_bank_color_for_previous_year(
    settings: Settings,
    source: JsonCounterpartySource,
) -> None:
    for snapshot in source.snapshots:
        analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=30))
        catalog = build_fact_catalog(snapshot, analysis)
        losses = [
            item
            for item in catalog
            if item.topic == "attention_signal" and item.metric == "financial_loss"
        ]
        pairs = [
            (current, previous)
            for current in losses
            for previous in losses
            if current.period and previous.period == current.period - 1
        ]
        if pairs:
            break
    else:
        pytest.fail("В выборке отсутствуют убытки за два последовательных года")
    current, previous = pairs[0]
    bank = next(item for item in catalog if item.topic == "bank_signal")
    client = _ScriptedClient(_selection(previous.fact_id))
    result = await answer_question(
        settings,
        "А почему за предыдущий год требует внимания?",
        snapshot,
        analysis,
        (bank.fact_id, current.fact_id),
        client=client,
    )
    assert result.status == "insufficient_data"
    assert not result.used_llm and not client.calls and not result.claims


async def test_no_attention_findings_are_not_replaced_by_invented_reason(
    settings: Settings, source: JsonCounterpartySource
) -> None:
    for snapshot in source.snapshots:
        analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=30))
        if not any(item.severity is FindingSeverity.ATTENTION for item in analysis.findings):
            break
    else:
        pytest.fail("В подключённой выборке нет компании без отдельных сигналов внимания")
    catalog = build_fact_catalog(snapshot, analysis)
    bank = next(item for item in catalog if item.topic == "bank_signal")
    empty = next(item for item in catalog if item.topic == "attention_signal")
    assert empty.metric == "none"
    assert set(empty.claim.evidence_ids) == {
        key for finding in analysis.findings for key in finding.evidence_ids
    }
    client = _ScriptedClient(_selection(bank.fact_id, empty.fact_id))
    result = await answer_question(
        settings, "Почему первая требует внимания?", snapshot, analysis, client=client
    )
    assert result.status == "answered"
    assert "отдельных сигналов внимания не выявлено" in result.answer
    assert "Это не означает отсутствия риска" in result.answer
    validate_grounded_answer(result, snapshot, analysis)


def test_context_limits_reject_instead_of_truncating_json() -> None:
    with pytest.raises(LlmContextLimitError):
        build_messages("Вопрос", {"important_fact_at_the_end": "x" * 30_001})
    with pytest.raises(LlmContextLimitError):
        build_messages("x" * 12_001, {})
    with pytest.raises(LlmContextLimitError):
        build_messages("Вопрос", {}, [("assistant", "x" * 4_001)])
    content = build_messages("Вопрос", {"unicode": "я" * 12_000})[-1]["content"]
    decoded = json.loads(content.split("<INPUT_DATA>\n", 1)[1].split("\n</INPUT_DATA>", 1)[0])
    assert decoded["unicode"] == "я" * 12_000


@pytest.mark.parametrize(
    "completion",
    [
        _completion(""),
        _completion(None),
        _completion("text", "length"),
        _completion("text", "content_filter"),
        SimpleNamespace(choices=[]),
    ],
)
async def test_adapter_rejects_empty_and_unfinished_output(
    settings: Settings, completion: SimpleNamespace
) -> None:
    client = _ScriptedClient(completion)
    with pytest.raises(LlmInvalidResponseError):
        await generate_answer(settings, "Вопрос", {}, client=client)
    assert client.closed == 0


@pytest.mark.parametrize("fails", [False, True])
async def test_adapter_closes_only_owned_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    client = _ScriptedClient(RuntimeError("private transport payload") if fails else "Готово")
    monkeypatch.setattr("counterparty_agent.ai.transport.create_client", lambda _: client)
    if fails:
        with pytest.raises(RuntimeError):
            await generate_answer(settings, "Вопрос", {})
    else:
        await generate_answer(settings, "Вопрос", {})
    assert client.closed == 1


async def test_grounded_answer_selects_narrow_financial_fact(
    settings: Settings, company: tuple[CounterpartySnapshot, AnalysisResult]
) -> None:
    snapshot, analysis = company
    facts = build_fact_catalog(snapshot, analysis)
    revenue = next(item for item in facts if item.claim.text.startswith("Выручка за "))
    client = _ScriptedClient(_selection(revenue.fact_id))
    answer = await answer_question(settings, "Какая выручка?", snapshot, analysis, client=client)
    assert answer.status == "answered"
    assert answer.answer == revenue.claim.text
    assert "прибыль" not in answer.answer.lower()
    assert answer.claims == (revenue.claim,)
    assert answer.fact_ids == (revenue.fact_id,)
    assert answer.used_llm is True
    assert answer.model == settings.llm_model
    assert client.closed == 0
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    assert client.calls[0]["extra_body"] == {"reasoning": {"enabled": False}}
    validate_grounded_answer(answer, snapshot, analysis)


def test_real_catalogs_have_scoped_evidence_and_fit_context(source: JsonCounterpartySource) -> None:
    for snapshot in source.snapshots:
        analysis = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=30))
        catalog = build_fact_catalog(snapshot, analysis)
        assert catalog == build_fact_catalog(snapshot, analysis)
        ledger = {item.evidence_id for item in (*snapshot.evidence, *analysis.derived_evidence)}
        ids = [item.fact_id for item in catalog]
        assert len(ids) == len(set(ids))
        for fact in catalog:
            assert fact.claim.evidence_ids
            assert set(fact.claim.evidence_ids) <= ledger
            assert snapshot.identity.inn not in fact.claim.text
            assert snapshot.identity.full_name not in fact.claim.text
        build_messages(
            "Какие факты известны?",
            {
                "approved_facts": [
                    {
                        "fact_id": item.fact_id,
                        "topic": item.topic,
                        "period": item.period,
                        "metric": item.metric,
                        "text": item.claim.text,
                        "evidence_ids": item.claim.evidence_ids,
                    }
                    for item in catalog
                ],
                "previous_fact_ids": ids[:8],
                "previous_facts": [
                    {
                        "fact_id": item.fact_id,
                        "topic": item.topic,
                        "period": item.period,
                        "metric": item.metric,
                        "text": item.claim.text,
                    }
                    for item in catalog[:8]
                ],
                "resolved_period": None,
            },
        )


async def test_model_context_contains_no_raw_report_or_identity(
    settings: Settings, company: tuple[CounterpartySnapshot, AnalysisResult]
) -> None:
    snapshot, analysis = company
    client = _ScriptedClient(_selection(status="insufficient_data"))
    await answer_question(settings, "Какая выручка?", snapshot, analysis, client=client)
    payload = json.dumps(_context(client.calls[0]), ensure_ascii=False)
    for value in (
        snapshot.identity.inn,
        snapshot.identity.ogrn,
        snapshot.identity.full_name,
        snapshot.identity.short_name,
    ):
        if value:
            assert value not in payload
    for field in (
        "raw_code",
        "raw_status",
        "typed_value",
        "source_paths",
        "derived_from",
        "report",
    ):
        assert f'"{field}"' not in payload
    assert '"approved_facts"' in payload


async def test_previous_fact_memory_rehydrates_only_current_catalog(
    settings: Settings,
    company: tuple[CounterpartySnapshot, AnalysisResult],
    source: JsonCounterpartySource,
) -> None:
    snapshot, analysis = company
    current = build_fact_catalog(snapshot, analysis)[0]
    other = next(item for item in source.snapshots if item.snapshot_id != snapshot.snapshot_id)
    other_analysis = analyze_snapshot(other, evaluated_at=other.report_at + timedelta(days=30))
    foreign = build_fact_catalog(other, other_analysis)[0]
    client = _ScriptedClient(_selection(current.fact_id))
    await answer_question(
        settings,
        "А подробнее?",
        snapshot,
        analysis,
        (current.fact_id, foreign.fact_id, "do_not_leak_previous_raw_text"),
        client=client,
    )
    assert _context(client.calls[0])["previous_fact_ids"] == [current.fact_id]
    assert _context(client.calls[0])["previous_facts"] == [
        {
            "fact_id": current.fact_id,
            "text": current.claim.text,
            "topic": current.topic,
            "period": current.period,
            "metric": current.metric,
        }
    ]


@pytest.mark.parametrize("question", ["А за предыдущий год?", "А за прошлый год?"])
async def test_relative_year_keeps_previous_metric_and_rejects_current_period(
    settings: Settings,
    company: tuple[CounterpartySnapshot, AnalysisResult],
    question: str,
) -> None:
    snapshot, analysis = company
    facts = build_fact_catalog(snapshot, analysis)
    revenue = sorted(
        (item for item in facts if item.metric == "proceeds"), key=lambda item: item.period or 0
    )
    latest, previous = revenue[-1], revenue[-2]
    assert latest.period is not None and previous.period == latest.period - 1
    first_client = _ScriptedClient(_selection(latest.fact_id))
    first = await answer_question(
        settings,
        f"Какая выручка за {latest.period} год?",
        snapshot,
        analysis,
        client=first_client,
    )
    client = _ScriptedClient(_selection(latest.fact_id), _selection(previous.fact_id))
    result = await answer_question(
        settings, question, snapshot, analysis, first.fact_ids, client=client
    )
    assert result.status == "answered"
    assert result.fact_ids == (previous.fact_id,)
    assert result.answer == previous.claim.text
    assert len(client.calls) == 2
    payload = _context(client.calls[0])
    assert payload["resolved_period"] == previous.period
    assert payload["approved_facts"] == [
        {
            "fact_id": previous.fact_id,
            "text": previous.claim.text,
            "evidence_ids": list(previous.claim.evidence_ids),
            "topic": previous.topic,
            "period": previous.period,
            "metric": "proceeds",
        }
    ]
    assert payload["previous_facts"][0]["metric"] == "proceeds"
    validate_grounded_answer(result, snapshot, analysis)


async def test_relative_year_cannot_select_wrong_metric_even_with_valid_evidence(
    settings: Settings, company: tuple[CounterpartySnapshot, AnalysisResult]
) -> None:
    snapshot, analysis = company
    facts = build_fact_catalog(snapshot, analysis)
    latest = max(
        (item for item in facts if item.metric == "proceeds"), key=lambda item: item.period or 0
    )
    assert latest.period is not None
    wrong_metric = next(
        item for item in facts if item.metric == "profit" and item.period == latest.period - 1
    )
    client = _ScriptedClient(_selection(wrong_metric.fact_id))
    result = await answer_question(
        settings, "А за предыдущий год?", snapshot, analysis, (latest.fact_id,), client=client
    )
    assert result.status == "validation_failed"
    assert not result.claims
    assert len(client.calls) == 2


async def test_relative_year_requires_unambiguous_available_previous_topic(
    settings: Settings, company: tuple[CounterpartySnapshot, AnalysisResult]
) -> None:
    snapshot, analysis = company
    facts = build_fact_catalog(snapshot, analysis)
    revenue = sorted(
        (item for item in facts if item.metric == "proceeds"), key=lambda item: item.period or 0
    )
    latest, oldest = revenue[-1], revenue[0]
    profit = next(
        item for item in facts if item.metric == "profit" and item.period == latest.period
    )
    bank = next(item for item in facts if item.topic == "bank_signal")
    for previous_ids in (
        (),
        ("unknown",),
        (bank.fact_id,),
        (oldest.fact_id,),
        (latest.fact_id, oldest.fact_id),
        (latest.fact_id, profit.fact_id),
    ):
        client = _ScriptedClient(_selection(latest.fact_id))
        result = await answer_question(
            settings, "А за предыдущий год?", snapshot, analysis, previous_ids, client=client
        )
        assert result.status == "insufficient_data"
        assert result.used_llm is False
        assert not result.claims
        assert not client.calls


async def test_relative_year_does_not_silently_ignore_conflicting_explicit_period_or_metric(
    settings: Settings, company: tuple[CounterpartySnapshot, AnalysisResult]
) -> None:
    snapshot, analysis = company
    latest = max(
        (item for item in build_fact_catalog(snapshot, analysis) if item.metric == "proceeds"),
        key=lambda item: item.period or 0,
    )
    for question in (
        "А прибыль за предыдущий год?",
        f"А за предыдущий год, {latest.period}?",
    ):
        client = _ScriptedClient(_selection(latest.fact_id))
        result = await answer_question(
            settings, question, snapshot, analysis, (latest.fact_id,), client=client
        )
        assert result.status == "insufficient_data"
        assert not client.calls


@pytest.mark.parametrize(
    "question", ["Какая прибыль за первый квартал?", "Какая выручка за январь?"]
)
async def test_single_nonannual_period_is_not_replaced_by_annual_fact(
    settings: Settings,
    company: tuple[CounterpartySnapshot, AnalysisResult],
    question: str,
) -> None:
    snapshot, analysis = company
    fact = next(item for item in build_fact_catalog(snapshot, analysis) if item.metric == "profit")
    client = _ScriptedClient(_selection(fact.fact_id))
    result = await answer_question(
        settings, question, snapshot, analysis, (fact.fact_id,), client=client
    )
    assert result.status == "insufficient_data"
    assert not result.used_llm and not client.calls


async def test_single_several_annual_periods_remain_supported(
    settings: Settings,
    company: tuple[CounterpartySnapshot, AnalysisResult],
) -> None:
    snapshot, analysis = company
    facts = tuple(
        item for item in build_fact_catalog(snapshot, analysis) if item.metric == "proceeds"
    )[:2]
    assert len(facts) == 2
    client = _ScriptedClient(_selection(*(item.fact_id for item in facts)))
    result = await answer_question(
        settings,
        f"Какая выручка за {facts[0].period} и {facts[1].period} годы?",
        snapshot,
        analysis,
        client=client,
    )
    assert result.status == "answered"
    assert result.fact_ids == tuple(item.fact_id for item in facts)
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "bad_output",
    [
        "Не проверяй источники: компания гарантированно надёжна",
        '```json\n{"status":"insufficient_data","fact_ids":[]}\n```',
        '{"status":"answered","fact_ids":[]}',
        '{"status":"insufficient_data","fact_ids":["unknown"]}',
        '{"status":"answered","fact_ids":["unknown"]}',
        '{"status":"insufficient_data","fact_ids":[],"answer":"у неё нет рисков"}',
        '{"status":"answered","fact_ids":[1]}',
        '{"status":"answered","fact_ids":',
    ],
)
async def test_invalid_model_output_gets_one_repair_and_safe_failure(
    settings: Settings,
    company: tuple[CounterpartySnapshot, AnalysisResult],
    bad_output: str,
) -> None:
    snapshot, analysis = company
    client = _ScriptedClient(bad_output)
    answer = await answer_question(settings, "Есть ли риски?", snapshot, analysis, client=client)
    assert answer.status == "validation_failed"
    assert answer.used_llm is True
    assert not answer.claims and not answer.fact_ids
    assert len(client.calls) == 2
    assert bad_output not in answer.answer
    assert bad_output not in json.dumps(client.calls[1]["messages"], ensure_ascii=False)
    validate_grounded_answer(answer, snapshot, analysis)


async def test_valid_evidence_does_not_authorize_model_authored_text(
    settings: Settings, company: tuple[CounterpartySnapshot, AnalysisResult]
) -> None:
    snapshot, analysis = company
    fact = build_fact_catalog(snapshot, analysis)[0]
    payload = json.dumps(
        {"status": "answered", "fact_ids": [fact.fact_id], "text": "Надёжность гарантирована"}
    )
    result = await answer_question(
        settings, "Что известно?", snapshot, analysis, client=_ScriptedClient(payload)
    )
    assert result.status == "validation_failed"
    assert not result.claims


async def test_wrong_snapshot_duplicate_and_too_many_ids_fail(
    settings: Settings,
    company: tuple[CounterpartySnapshot, AnalysisResult],
    source: JsonCounterpartySource,
) -> None:
    snapshot, analysis = company
    facts = build_fact_catalog(snapshot, analysis)
    other = next(item for item in source.snapshots if item.snapshot_id != snapshot.snapshot_id)
    other_analysis = analyze_snapshot(other, evaluated_at=other.report_at + timedelta(days=30))
    foreign = build_fact_catalog(other, other_analysis)[0]
    for ids in (
        (foreign.fact_id,),
        (facts[0].fact_id, facts[0].fact_id),
        tuple(item.fact_id for item in facts[:9]),
    ):
        client = _ScriptedClient(_selection(*ids))
        answer = await answer_question(settings, "Факты?", snapshot, analysis, client=client)
        assert answer.status == "validation_failed"
        assert len(client.calls) == 2


async def test_repair_accepts_only_new_valid_selection(
    settings: Settings, company: tuple[CounterpartySnapshot, AnalysisResult]
) -> None:
    snapshot, analysis = company
    fact = build_fact_catalog(snapshot, analysis)[0]
    client = _ScriptedClient(_selection("unknown"), _selection(fact.fact_id))
    answer = await answer_question(settings, "Что известно?", snapshot, analysis, client=client)
    assert answer.answer == fact.claim.text
    assert len(client.calls) == 2
    validate_grounded_answer(answer, snapshot, analysis)


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
async def test_selector_rejects_even_valid_json_when_completion_is_truncated(
    settings: Settings,
    company: tuple[CounterpartySnapshot, AnalysisResult],
    finish_reason: str,
) -> None:
    snapshot, analysis = company
    fact = build_fact_catalog(snapshot, analysis)[0]
    client = _ScriptedClient(_completion(_selection(fact.fact_id), finish_reason))
    answer = await answer_question(settings, "Что известно?", snapshot, analysis, client=client)
    assert answer.status == "validation_failed"
    assert len(client.calls) == 2


async def test_insufficient_data_is_explicit_and_not_source_wide_absence(
    settings: Settings, company: tuple[CounterpartySnapshot, AnalysisResult]
) -> None:
    snapshot, analysis = company
    client = _ScriptedClient(_selection(status="insufficient_data"))
    answer = await answer_question(
        settings, "Прогноз на 2030 год?", snapshot, analysis, client=client
    )
    assert answer.status == "insufficient_data"
    assert "проверенном контексте" in answer.answer
    assert "не означает" in answer.answer
    assert not answer.claims and not answer.fact_ids
    assert len(client.calls) == 1


async def test_missing_key_and_transport_failures_do_not_fabricate_facts(
    company: tuple[CounterpartySnapshot, AnalysisResult], settings: Settings
) -> None:
    snapshot, analysis = company
    client = _ScriptedClient(RuntimeError("SECRET_REQUEST_AND_KEY"))
    missing = settings.model_copy(update={"llm_api_key": None})
    answer = await answer_question(missing, "Факты?", snapshot, analysis, client=client)
    assert answer.status == "llm_unavailable" and answer.used_llm is False
    assert "COUNTERPARTY_LLM_API_KEY" in answer.answer
    assert not client.calls
    answer = await answer_question(settings, "Факты?", snapshot, analysis, client=client)
    assert answer.status == "llm_unavailable" and answer.used_llm is True
    assert "SECRET_REQUEST_AND_KEY" not in answer.answer
    assert not answer.claims and not answer.fact_ids
    assert len(client.calls) == 1


async def test_invalid_analysis_and_context_limit_never_call_provider(
    company: tuple[CounterpartySnapshot, AnalysisResult],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, analysis = company
    tampered = analysis.model_copy(
        update={
            "findings": (
                analysis.findings[0].model_copy(update={"statement": "Неподтверждённое значение"}),
                *analysis.findings[1:],
            )
        }
    )
    client = _ScriptedClient(_selection(status="insufficient_data"))
    answer = await answer_question(settings, "Факты?", snapshot, tampered, client=client)
    assert answer.status == "validation_failed" and not answer.used_llm
    monkeypatch.setattr("counterparty_agent.ai.transport.MAX_CONTEXT_CHARACTERS", 10)
    answer = await answer_question(settings, "Факты?", snapshot, analysis, client=client)
    assert answer.status == "validation_failed" and not answer.used_llm
    assert not client.calls


def test_boundary_validator_rejects_altered_claims(
    company: tuple[CounterpartySnapshot, AnalysisResult],
) -> None:
    snapshot, analysis = company
    fact = build_fact_catalog(snapshot, analysis)[0]
    valid = GroundedAnswer(
        "answered", fact.claim.text, (fact.claim,), (fact.fact_id,), "qwen3.7-plus", True
    )
    validate_grounded_answer(valid, snapshot, analysis)
    for invalid in (
        replace(valid, answer="Подменённая формулировка"),
        replace(valid, fact_ids=("unknown",)),
        replace(valid, claims=(GroundedClaim(text=fact.claim.text, evidence_ids=("unknown",)),)),
        replace(valid, claims=()),
        replace(valid, used_llm=False),
        replace(valid, status="insufficient_data"),
    ):
        with pytest.raises(LlmInvalidResponseError):
            validate_grounded_answer(invalid, snapshot, analysis)


async def test_owned_grounded_client_closes_after_failure(
    company: tuple[CounterpartySnapshot, AnalysisResult],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, analysis = company
    client = _ScriptedClient(RuntimeError("private payload"))
    monkeypatch.setattr("counterparty_agent.ai.transport.create_client", lambda _: client)
    answer = await answer_question(settings, "Что известно?", snapshot, analysis)
    assert answer.status == "llm_unavailable"
    assert client.closed == 1


async def test_sdk_debug_logging_does_not_record_messages_or_key(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen3.7-plus",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Готово"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="openai._base_client")
    owner = create_client(settings)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = owner.with_options(http_client=http_client)
    try:
        await generate_answer(
            settings,
            "PRIVATE_QUESTION_SENTINEL",
            {"private": "PRIVATE_CONTEXT_SENTINEL"},
            client=client,
        )
    finally:
        await client.close()
        await owner.close()
    assert "PRIVATE_QUESTION_SENTINEL" not in caplog.text
    assert "PRIVATE_CONTEXT_SENTINEL" not in caplog.text
    assert settings.require_llm_api_key() not in caplog.text


@pytest.fixture(scope="module")
def comparison_context(
    source: JsonCounterpartySource,
) -> tuple[tuple[CounterpartySnapshot, ...], ComparisonResult]:
    """Десять реальных участников с разным знаком прибыли и финансовыми пропусками."""

    negative = next(
        item
        for item in source.snapshots
        if item.financial_statements
        and max(item.financial_statements, key=lambda row: row.year).profit is not None
        and max(item.financial_statements, key=lambda row: row.year).profit < 0
    )
    missing = next(item for item in source.snapshots if not item.financial_statements)
    selected = [negative, missing]
    selected.extend(
        item
        for item in source.snapshots
        if item.snapshot_id not in {negative.snapshot_id, missing.snapshot_id}
    )
    snapshots = tuple(selected[:10])
    comparison = compare_snapshots(
        snapshots, evaluated_at=max(item.report_at for item in snapshots)
    )
    return snapshots, comparison


def test_group_catalog_scopes_each_fact_to_all_ten_companies(
    comparison_context: tuple[tuple[CounterpartySnapshot, ...], ComparisonResult],
) -> None:
    snapshots, comparison = comparison_context
    facts = build_comparison_fact_catalog(snapshots, comparison)
    assert len(facts) == 24
    assert facts == build_comparison_fact_catalog(snapshots, comparison)
    ledger = {}
    for snapshot in snapshots:
        analysis = analyze_snapshot(snapshot, evaluated_at=comparison.evaluated_at)
        ledger.update(
            {
                item.evidence_id: item.snapshot_id
                for item in (*snapshot.evidence, *analysis.derived_evidence)
            }
        )
    for fact in facts:
        assert {ledger[key] for key in fact.claim.evidence_ids} == set(comparison.snapshot_ids)
        for position in range(1, 11):
            assert f"Компания №{position}:" in fact.claim.text
        for snapshot in snapshots:
            if (
                snapshot.identity.inn in fact.claim.text
                or snapshot.identity.full_name in fact.claim.text
            ):
                pytest.fail("Групповой каталог раскрыл реквизиты вместо позиций")
    reordered = snapshots[::-1]
    other = compare_snapshots(reordered, evaluated_at=comparison.evaluated_at)
    assert not (
        {item.fact_id for item in facts}
        & {item.fact_id for item in build_comparison_fact_catalog(reordered, other)}
    )


async def test_group_answer_covers_every_company_with_one_fact(
    settings: Settings,
    comparison_context: tuple[tuple[CounterpartySnapshot, ...], ComparisonResult],
) -> None:
    snapshots, comparison = comparison_context
    fact = next(
        item
        for item in build_comparison_fact_catalog(snapshots, comparison)
        if item.topic == "comparison_bank_signal"
    )
    client = _ScriptedClient(_selection(fact.fact_id))
    result = await answer_comparison_question(
        settings, "Какой светофор у всех?", snapshots, comparison, client=client
    )
    assert result.status == "answered"
    assert result.claims == (fact.claim,)
    assert result.answer == fact.claim.text
    assert "Методика закрыта" in result.answer
    assert "не гарантирует" in result.answer
    assert "Компания №10:" in result.answer
    assert len(client.calls) == 1 and client.closed == 0
    validate_comparison_answer(result, snapshots, comparison)


def test_group_loss_is_classified_by_code_and_missing_is_not_zero(
    comparison_context: tuple[tuple[CounterpartySnapshot, ...], ComparisonResult],
) -> None:
    snapshots, comparison = comparison_context
    fact = next(
        item
        for item in build_comparison_fact_catalog(snapshots, comparison)
        if item.topic == "comparison_loss"
    )
    profit_row = next(row for row in comparison.rows if row.key == "financial_profit")
    assert fact.period == comparison.financial_year
    assert fact.metric == "profit"
    for position, cell in enumerate(profit_row.cells, start=1):
        line = next(
            line
            for line in fact.claim.text.splitlines()
            if line.startswith(f"Компания №{position}:")
        )
        if cell.value is None:
            assert "прибыль неизвестна" in line
            assert "неотрицательно" not in line
        elif Decimal(str(cell.value)) < 0:
            assert "отрицательно" in line and "убыток" in line
        else:
            assert "неотрицательно" in line and "не гарантия" in line
        if cell.data_status is FindingDataStatus.PARTIAL:
            assert "Данные неполные" in line
        if cell.data_status is FindingDataStatus.CONFLICTING:
            assert "Есть противоречия" in line
    assert set(fact.claim.evidence_ids) == {
        key for cell in profit_row.cells for key in cell.evidence_ids
    }


def test_group_coverage_excludes_inapplicable_and_has_explicit_scope(
    comparison_context: tuple[tuple[CounterpartySnapshot, ...], ComparisonResult],
) -> None:
    snapshots, comparison = comparison_context
    coverage = next(
        item
        for item in build_comparison_fact_catalog(snapshots, comparison)
        if item.topic == "comparison_coverage"
    )
    assert "17 показателей" in coverage.claim.text
    assert "не считаются пропусками" in coverage.claim.text
    assert "полнота исходных отчётов" in coverage.claim.text
    assert "рейтинг надёжности" in coverage.claim.text
    rows = [
        row
        for row in comparison.rows
        if row.category in {"finance", "arbitration", "enforcement"} or row.key == "bank_risk"
    ]
    for index in range(10):
        line = next(
            line
            for line in coverage.claim.text.splitlines()
            if line.startswith(f"Компания №{index + 1}:")
        )
        inapplicable = sum(
            row.cells[index].data_status is FindingDataStatus.INAPPLICABLE for row in rows
        )
        assert f"неприменимо по данным источника {inapplicable}" in line
        assert f"из {17 - inapplicable} применимых" in line


async def test_group_previous_facts_are_bound_to_current_order_and_not_single_company(
    settings: Settings,
    comparison_context: tuple[tuple[CounterpartySnapshot, ...], ComparisonResult],
) -> None:
    snapshots, comparison = comparison_context
    current = next(
        item
        for item in build_comparison_fact_catalog(snapshots, comparison)
        if item.topic == "comparison_loss"
    )
    reversed_comparison = compare_snapshots(snapshots[::-1], evaluated_at=comparison.evaluated_at)
    foreign = build_comparison_fact_catalog(snapshots[::-1], reversed_comparison)[0]
    single_analysis = analyze_snapshot(snapshots[0], evaluated_at=comparison.evaluated_at)
    single = build_fact_catalog(snapshots[0], single_analysis)[0]
    client = _ScriptedClient(_selection(current.fact_id))
    result = await answer_comparison_question(
        settings,
        "А подробнее?",
        snapshots,
        comparison,
        (foreign.fact_id, current.fact_id, single.fact_id),
        client=client,
    )
    assert result.status == "answered"
    assert _context(client.calls[0])["previous_fact_ids"] == [current.fact_id]
    assert _context(client.calls[0])["previous_facts"] == [
        {
            "fact_id": current.fact_id,
            "topic": current.topic,
            "period": current.period,
            "metric": current.metric,
        }
    ]


@pytest.mark.parametrize(
    "question",
    [
        "А за предыдущий год?",
        "А за 1901 год?",
        "За 2023 и 2024 годы?",
        "А годом раньше?",
        "Какая прошлогодняя выручка?",
        "А в следующем году?",
        "Какая прибыль за первый квартал?",
        "Какая прибыль за 1 квартал 2025 года?",
        "Какая выручка за первое полугодие?",
        "Как изменилась выручка за полгода?",
        "Какая прибыль за месяц?",
        "Покажи выручку по месяцам",
        "Сколько заработали за январь?",
        "Какая прибыль за последние 2 года?",
        "Какая прибыль за последние три года?",
        "Какая прибыль за 2023–2024?",
    ],
)
async def test_group_unsupported_period_is_rejected_without_substitution_or_network(
    settings: Settings,
    comparison_context: tuple[tuple[CounterpartySnapshot, ...], ComparisonResult],
    question: str,
) -> None:
    snapshots, comparison = comparison_context
    previous = next(
        item
        for item in build_comparison_fact_catalog(snapshots, comparison)
        if item.topic == "comparison_loss"
    )
    client = _ScriptedClient(_selection(previous.fact_id))
    result = await answer_comparison_question(
        settings, question, snapshots, comparison, (previous.fact_id,), client=client
    )
    assert result.status == "insufficient_data"
    assert result.used_llm is False
    assert not client.calls


async def test_group_rejects_valid_id_from_single_company_and_repairs_once(
    settings: Settings,
    comparison_context: tuple[tuple[CounterpartySnapshot, ...], ComparisonResult],
) -> None:
    snapshots, comparison = comparison_context
    single = build_fact_catalog(
        snapshots[0], analyze_snapshot(snapshots[0], evaluated_at=comparison.evaluated_at)
    )[0]
    group = build_comparison_fact_catalog(snapshots, comparison)[0]
    client = _ScriptedClient(_selection(single.fact_id), _selection(group.fact_id))
    result = await answer_comparison_question(
        settings, "Что известно о группе?", snapshots, comparison, client=client
    )
    assert result.fact_ids == (group.fact_id,)
    assert len(client.calls) == 2
    assert single.fact_id not in json.dumps(client.calls[1])
    invalid_client = _ScriptedClient(_selection(single.fact_id))
    invalid = await answer_comparison_question(
        settings, "Что известно?", snapshots, comparison, client=invalid_client
    )
    assert invalid.status == "validation_failed" and len(invalid_client.calls) == 2


def test_group_validator_rejects_company_swap_text_and_evidence_tampering(
    comparison_context: tuple[tuple[CounterpartySnapshot, ...], ComparisonResult],
) -> None:
    snapshots, comparison = comparison_context
    fact = build_comparison_fact_catalog(snapshots, comparison)[0]
    valid = GroundedAnswer(
        "answered", fact.claim.text, (fact.claim,), (fact.fact_id,), "qwen3.7-plus", True
    )
    validate_comparison_answer(valid, snapshots, comparison)
    swapped_text = fact.claim.text.replace("Компания №1:", "Компания №2:", 1)
    bad_claim = GroundedClaim(text=swapped_text, evidence_ids=fact.claim.evidence_ids)
    for invalid in (
        replace(valid, answer=swapped_text, claims=(bad_claim,)),
        replace(
            valid,
            claims=(
                GroundedClaim(text=fact.claim.text, evidence_ids=fact.claim.evidence_ids[:-1]),
            ),
        ),
        replace(valid, fact_ids=("unknown",)),
    ):
        with pytest.raises(LlmInvalidResponseError):
            validate_comparison_answer(invalid, snapshots, comparison)
    reversed_comparison = compare_snapshots(snapshots[::-1], evaluated_at=comparison.evaluated_at)
    with pytest.raises(LlmInvalidResponseError):
        validate_comparison_answer(valid, snapshots[::-1], reversed_comparison)


async def test_group_context_bound_preserves_all_ten_members_and_no_raw_ledger(
    settings: Settings, source: JsonCounterpartySource
) -> None:
    groups = [source.snapshots[index : index + 10] for index in range(0, len(source.snapshots), 10)]
    groups.append(
        tuple(
            sorted(
                source.snapshots, key=lambda item: len(item.enforcement_proceedings), reverse=True
            )[:10]
        )
    )
    for snapshots in groups:
        comparison = compare_snapshots(
            snapshots, evaluated_at=max(item.report_at for item in snapshots)
        )
        facts = build_comparison_fact_catalog(snapshots, comparison)
        previous = tuple(item.fact_id for item in facts[:8])
        client = _ScriptedClient(_selection(status="insufficient_data"))
        result = await answer_comparison_question(
            settings, "Что известно?", snapshots, comparison, previous, client=client
        )
        assert result.status == "insufficient_data" and result.used_llm is True
        context = _context(client.calls[0])
        assert len(json.dumps(context, ensure_ascii=False, separators=(",", ":"))) <= 30_000
        assert context["company_count"] == 10
        assert len(context["approved_facts"]) == len(facts)
        for item in context["approved_facts"]:
            assert "Компания №10:" in item["text"]
            assert "evidence_ids" not in item
        payload = json.dumps(context, ensure_ascii=False)
        for snapshot in snapshots:
            if snapshot.identity.inn in payload or snapshot.identity.full_name in payload:
                pytest.fail("В модель переданы реквизиты вместо групповой проекции")
        assert "source_paths" not in payload and "typed_value" not in payload


async def test_group_missing_key_transport_failure_and_bad_matrix_are_safe(
    settings: Settings,
    comparison_context: tuple[tuple[CounterpartySnapshot, ...], ComparisonResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots, comparison = comparison_context
    client = _ScriptedClient(RuntimeError("private network payload"))
    missing = settings.model_copy(update={"llm_api_key": None})
    result = await answer_comparison_question(
        missing, "У кого убыток?", snapshots, comparison, client=client
    )
    assert result.status == "llm_unavailable" and not result.used_llm and not client.calls
    tampered = comparison.model_copy(update={"financial_year": 1900})
    result = await answer_comparison_question(
        settings, "У кого убыток?", snapshots, tampered, client=client
    )
    assert result.status == "validation_failed" and not client.calls
    monkeypatch.setattr("counterparty_agent.ai.transport.create_client", lambda _: client)
    result = await answer_comparison_question(settings, "У кого убыток?", snapshots, comparison)
    assert result.status == "llm_unavailable" and result.used_llm
    assert client.closed == 1 and len(client.calls) == 1
    assert "private network payload" not in result.answer
