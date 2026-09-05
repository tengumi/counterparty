"""Краткая оценка, отдельные причины и честные ограничения данных."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from benchmarks.synthetic import synthetic_factory
from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.comparison_catalog import build_comparison_fact_catalog
from counterparty_agent.ai.selector import answer_comparison_question, answer_question
from counterparty_agent.ai.topics import needs_attention_explanation, needs_bank_reason, topic_key
from counterparty_agent.analytics.comparison import compare_snapshots
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource

NOW = datetime(2026, 9, 5, tzinfo=UTC)


@pytest.fixture
def bank_source(tmp_path: Path) -> JsonCounterpartySource:
    """Граничные значения существуют только во временном тестовом источнике."""

    reports = synthetic_factory(n=6).reports
    reports[-1]["report"]["zskRiskLevel"] = "UNKNOWN"
    path = tmp_path / "bank-cases.json"
    path.write_text(json.dumps(reports), encoding="utf-8")
    return JsonCounterpartySource.from_path(path)


def test_bank_catalog_keeps_color_and_separates_unknown_reason(
    bank_source: JsonCounterpartySource,
) -> None:
    for snapshot in bank_source.snapshots:
        analysis = analyze_snapshot(snapshot, evaluated_at=NOW)
        facts = build_fact_catalog(snapshot, analysis)
        bank = next(f for f in facts if f.topic == "bank_signal" and f.metric is None)
        reason = next(f for f in facts if f.metric == "reason_unavailable")
        assert analysis.bank_risk == snapshot.bank_risk
        assert bank.fact_id != reason.fact_id
        assert bank.claim.evidence_ids == reason.claim.evidence_ids == (analysis.bank_evidence_id,)
        assert "Причина" not in bank.claim.text
        assert "методик" not in bank.claim.text and "скоринг" not in bank.claim.text
        if snapshot.bank_risk.recognized_level is not None:
            assert snapshot.bank_risk.raw_level in bank.claim.text
            assert reason.claim.text == "Причина этой оценки в отчёте не указана."
        else:
            assert "GREY" not in bank.claim.text
            assert "нет распознанной оценки" in reason.claim.text


def test_no_attention_does_not_claim_safety_or_explain_color(
    bank_source: JsonCounterpartySource,
) -> None:
    snapshot = bank_source.snapshots[0]
    facts = build_fact_catalog(snapshot, analyze_snapshot(snapshot, evaluated_at=NOW))
    empty = next(f for f in facts if f.topic == "attention_signal" and f.metric == "none")
    assert "В выполненных проверках" in empty.claim.text
    assert "Это не означает отсутствия риска или полноты данных." in empty.claim.text
    assert "цвет" not in empty.claim.text and "оценк" not in empty.claim.text
    assert empty.claim.evidence_ids


def test_comparison_keeps_missing_unknown_and_grey_distinct(
    bank_source: JsonCounterpartySource,
) -> None:
    snapshots = bank_source.snapshots
    comparison = compare_snapshots(snapshots, evaluated_at=NOW)
    row = next(r for r in comparison.rows if r.key == "bank_risk")
    assert [cell.value for cell in row.cells] == ["GREEN", "YELLOW", "RED", "GREY", None, "UNKNOWN"]
    assert row.cells[3].display_value == "GREY — нет данных для оценки"
    assert row.cells[4].display_value == "Оценка отсутствует"
    assert row.cells[5].display_value == "Значение оценки не распознано"
    facts = build_comparison_fact_catalog(snapshots, comparison)
    bank = next(f for f in facts if f.topic == "comparison_bank_signal" and f.metric is None)
    reason = next(f for f in facts if f.metric == "reason_unavailable")
    assert "методик" not in bank.claim.text.casefold()
    assert "внешний" not in bank.claim.text.casefold()
    assert "Причина этой оценки" not in bank.claim.text
    assert set(bank.claim.evidence_ids) == set(reason.claim.evidence_ids)
    for position in range(1, len(snapshots) + 1):
        assert f"Компания №{position}:" in bank.claim.text
        assert f"Компания №{position}:" in reason.claim.text


class ReasonSelector:
    """Двойник выбирает заранее заданные темы, в том числе заведомо неполный ответ."""

    def __init__(self, topics: set[str]):
        self.topics = topics
        self.chat = SimpleNamespace(completions=self)
        self.calls = 0

    async def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        text = kwargs["messages"][1]["content"]
        data = json.loads(text.split("<INPUT_DATA>\n")[1].split("\n</INPUT_DATA>")[0])
        selected: dict[str, str] = {}
        for fact in data["approved_facts"]:
            topic = fact["topic"]
            if fact["metric"] == "reason_unavailable":
                topic += ":reason_unavailable"
            if topic in self.topics and topic not in selected:
                selected[topic] = fact["fact_id"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=json.dumps(
                            {"status": "answered", "fact_ids": list(selected.values())}
                        )
                    ),
                )
            ]
        )


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("omitted", [None, "reason", "signal", "assessment"])
async def test_reason_answer_requires_assessment_unknown_reason_and_separate_findings(
    bank_source: JsonCounterpartySource, group: bool, omitted: str | None
) -> None:
    prefix = "comparison_" if group else ""
    topics = {
        "assessment": f"{prefix}bank_signal",
        "reason": f"{prefix}bank_signal:reason_unavailable",
        "signal": "comparison_attention_signals" if group else "attention_signal",
    }
    client = ReasonSelector({topic for kind, topic in topics.items() if kind != omitted})
    settings = Settings(_env_file=None, llm_api_key=SecretStr("test-only"))
    snapshots = bank_source.snapshots
    if group:
        comparison = compare_snapshots(snapshots, evaluated_at=NOW)
        result = await answer_comparison_question(
            settings, "Почему такие цвета светофора?", snapshots, comparison, client=client
        )
        catalog = build_comparison_fact_catalog(snapshots, comparison)
    else:
        snapshot = snapshots[0]
        analysis = analyze_snapshot(snapshot, evaluated_at=NOW)
        result = await answer_question(
            settings, "Почему контрагент надёжен?", snapshot, analysis, client=client
        )
        catalog = build_fact_catalog(snapshot, analysis)
    if omitted is not None:
        assert result.status == "validation_failed" and not result.claims
        assert client.calls == 2
    else:
        assert result.status == "answered" and client.calls == 1
        selected = {topic_key(f) for f in catalog if f.fact_id in result.fact_ids}
        assert selected == set(topics.values())
        assert "Причина этой оценки в отчёте не указана." in result.answer
        assert "методик" not in result.answer and "скоринг" not in result.answer


@pytest.mark.parametrize(
    "question", ["Какие сигналы внимания?", "Что настораживает?", "Какой цвет?"]
)
def test_noncausal_question_does_not_request_reason_copy(question: str) -> None:
    assert not needs_bank_reason(question)


@pytest.mark.parametrize(
    "question",
    [
        "Из-за чего этот контрагент надежен?",
        "Из-за чего этот контрагент надёжен?",
        "Почему этот контрагент надёжен?",
        "Из-за чего у него зелёная оценка?",
        "Почему компания надёжная?",
    ],
)
def test_bank_reason_question_requires_closed_scoring_boundary(question: str) -> None:
    assert needs_attention_explanation(question)


@pytest.mark.parametrize(
    "question",
    [
        "Из-за чего упала выручка?",
        "А каккие есть судебные дела?",
        "Какой цвет светофора?",
        "Этот контрагент надёжен?",
        "Из-за чего?",
    ],
)
def test_unrelated_or_noncausal_question_does_not_trigger_bank_explanation(question: str) -> None:
    assert not needs_attention_explanation(question)
