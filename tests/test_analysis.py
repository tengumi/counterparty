"""Проверки детерминированной аналитики на выданных реальных карточках."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from counterparty_agent.analytics.common import AnalysisValidationError
from counterparty_agent.analytics.core import analyze_snapshot, validate_analysis
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import (
    AnalysisPolicy,
    AnalysisResult,
    BankTrafficLight,
    Evidence,
    EvidenceKind,
    Finding,
    FindingDataStatus,
    FindingSeverity,
    PartyType,
)


@pytest.fixture(scope="module")
def source() -> JsonCounterpartySource:
    """Прочитать локальный источник, не добавляя копии и идентификаторы в Git."""

    snapshot_path = Path(Settings().snapshot_json_path)
    if not snapshot_path.is_file():
        pytest.skip("Реальный snapshot не настроен в COUNTERPARTY_SNAPSHOT_JSON_PATH")
    return JsonCounterpartySource.from_path(snapshot_path)


@pytest.fixture(scope="module")
def results(source: JsonCounterpartySource) -> tuple[AnalysisResult, ...]:
    """Зафиксировать момент анализа относительно даты каждого исходного отчёта."""

    return tuple(
        analyze_snapshot(snapshot, evaluated_at=snapshot.report_at + timedelta(days=30))
        for snapshot in source.snapshots
    )


def test_analysis_is_deterministic_and_does_not_mutate_source(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    for index, (snapshot, result) in enumerate(zip(source.snapshots, results, strict=True)):
        original = snapshot.model_copy(deep=True)
        repeated = analyze_snapshot(snapshot, evaluated_at=result.evaluated_at)
        if result != repeated:
            pytest.fail(f"Анализ недетерминирован для записи {index}")
        if snapshot != original:
            pytest.fail(f"Анализ изменил исходную запись {index}")
        if result.bank_risk != snapshot.bank_risk:
            pytest.fail(f"Анализ изменил банковский светофор записи {index}")
        validate_analysis(result, snapshot)


def test_every_finding_has_scoped_evidence_and_valid_lineage(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    for index, (snapshot, result) in enumerate(zip(source.snapshots, results, strict=True)):
        ledger = {item.evidence_id: item for item in (*snapshot.evidence, *result.derived_evidence)}
        if len(ledger) != len(snapshot.evidence) + len(result.derived_evidence):
            pytest.fail(f"Коллизия исходного и производного evidence в записи {index}")
        if result.bank_evidence_id not in ledger:
            pytest.fail(f"Банковский сигнал без evidence в записи {index}")
        for finding in result.findings:
            if not finding.evidence_ids or any(key not in ledger for key in finding.evidence_ids):
                pytest.fail(f"Вывод без доступного evidence в записи {index}")
            if (finding.company_id, finding.snapshot_id) != (
                snapshot.company_id,
                snapshot.snapshot_id,
            ):
                pytest.fail(f"Вывод относится к другой карточке в записи {index}")
        for evidence in result.derived_evidence:
            if evidence.kind is not EvidenceKind.DERIVED or not evidence.derived_from:
                pytest.fail(f"Неполный lineage производного evidence в записи {index}")
            if (
                evidence.company_id != snapshot.company_id
                or evidence.snapshot_id != snapshot.snapshot_id
                or evidence.source_hash != snapshot.source_hash
                or evidence.record_hash != snapshot.record_hash
                or evidence.report_at != snapshot.report_at
            ):
                pytest.fail(f"Неверный provenance производного evidence в записи {index}")
            _check_lineage(evidence.evidence_id, ledger, (), index)


def test_analysis_does_not_depend_on_callers_decimal_context(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    for snapshot, expected in zip(source.snapshots, results, strict=True):
        if not snapshot.financial_statements:
            continue
        with localcontext() as context:
            context.prec = 6
            context.rounding = ROUND_DOWN
            actual = analyze_snapshot(snapshot, evaluated_at=expected.evaluated_at)
            _equal(actual, expected, "Результат зависит от Decimal-контекста вызывающего кода")
            _equal(context.prec, 6, "Анализ изменил точность вызывающего кода")
            _equal(context.rounding, ROUND_DOWN, "Анализ изменил округление вызывающего кода")


def test_financial_periods_preserve_decimal_values_and_missing_fields(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    checked = 0
    missing_fields = 0
    for snapshot, result in zip(source.snapshots, results, strict=True):
        for statement in snapshot.financial_statements or ():
            finding = _finding(result, "financial_period", statement.year)
            values = _values(result, finding)
            expected = {
                "proceeds": statement.proceeds,
                "profit": statement.profit,
                "assets_total": statement.assets.total,
                "liabilities_total": statement.liabilities.total,
                "equity": statement.liabilities.capital_and_reserves,
            }
            for key, expected_value in expected.items():
                _equal(values.get(key), expected_value, f"Неверное финансовое поле: {key}")
                if expected_value is None:
                    missing_fields += 1
                elif not isinstance(values.get(key), Decimal):
                    pytest.fail("Финансовое значение потеряло тип Decimal")
            checked += 1
    assert checked > 0
    assert missing_fields > 0


def test_financial_attention_rules_follow_only_observed_values(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    counts = {"financial_loss": 0, "negative_equity": 0, "financial_balance_mismatch": 0}
    for snapshot, result in zip(source.snapshots, results, strict=True):
        for statement in snapshot.financial_statements or ():
            expected = {
                "financial_loss": statement.profit is not None and statement.profit < 0,
                "negative_equity": statement.liabilities.capital_and_reserves is not None
                and statement.liabilities.capital_and_reserves < 0,
                "financial_balance_mismatch": statement.assets.total != statement.liabilities.total,
            }
            for code, present in expected.items():
                found = _findings(result, code, statement.year)
                _equal(bool(found), present, f"Неверное условие правила {code}")
                if found:
                    _equal(len(found), 1, f"Правило {code} продублировано")
                    if found[0].severity is not FindingSeverity.ATTENTION:
                        pytest.fail(f"Правило {code} не отмечено для внимания")
                    counts[code] += 1
    assert counts["financial_loss"] > 0
    assert counts["negative_equity"] > 0


def test_revenue_change_uses_decimal_and_does_not_divide_by_nonpositive_base(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    checked = 0
    nonpositive = 0
    for snapshot, result in zip(source.snapshots, results, strict=True):
        statements = sorted(snapshot.financial_statements or (), key=lambda item: item.year)
        for previous, current in zip(statements, statements[1:], strict=False):
            period = f"{previous.year}:{current.year}"
            gap = _findings(result, "financial_period_gap", period)
            _equal(bool(gap), current.year != previous.year + 1, "Неверный признак пропущенных лет")
            if current.year != previous.year + 1:
                if _findings(result, "financial_revenue_change", period):
                    pytest.fail("Годовая динамика рассчитана через пропущенные годы")
                continue
            if previous.proceeds is None or current.proceeds is None:
                continue
            finding = _finding(result, "financial_revenue_change", period)
            values = _values(result, finding)
            delta = current.proceeds - previous.proceeds
            with localcontext() as context:
                context.prec = 50
                context.rounding = ROUND_HALF_UP
                percent = (
                    (delta / previous.proceeds * 100).quantize(Decimal("0.01"))
                    if previous.proceeds > 0 and current.proceeds >= 0
                    else None
                )
            expected = {
                "previous_year": previous.year,
                "year": current.year,
                "previous": previous.proceeds,
                "current": current.proceeds,
                "delta": delta,
                "percent": percent,
            }
            for key, expected_value in expected.items():
                _equal(values.get(key), expected_value, f"Неверное поле динамики: {key}")
            if not isinstance(values["delta"], Decimal):
                pytest.fail("Изменение выручки не Decimal")
            if percent is not None and not isinstance(values["percent"], Decimal):
                pytest.fail("Процент изменения выручки не Decimal")
            if percent is None:
                nonpositive += 1
            checked += 1
    assert checked > 0
    assert nonpositive > 0


def test_missing_and_empty_financial_sections_are_not_positive_findings(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    checked = {"missing": 0, "empty": 0}
    for snapshot, result in zip(source.snapshots, results, strict=True):
        if snapshot.financial_statements is None:
            finding = _finding(result, "financial_missing")
            expected = (
                FindingDataStatus.INAPPLICABLE
                if snapshot.identity.party_type is PartyType.INDIVIDUAL_ENTREPRENEUR
                else FindingDataStatus.INSUFFICIENT
            )
            if finding.data_status is not expected:
                pytest.fail("Пропуск финансов неверно интерпретирован")
            checked["missing"] += 1
        elif snapshot.financial_statements == ():
            finding = _finding(result, "financial_empty")
            if finding.data_status is not FindingDataStatus.INSUFFICIENT:
                pytest.fail("Пустая финансовая коллекция не обозначена как нехватка данных")
            checked["empty"] += 1
        else:
            continue
        if any(item.code == "financial_period" for item in result.findings):
            pytest.fail("Финансовый период создан без входных финансов")
    assert checked["missing"] > 0
    assert checked["empty"] > 0


def test_enforcement_summary_counts_and_sums_only_available_amounts(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    with_unknown_amounts = 0
    empty_collections = 0
    for snapshot, result in zip(source.snapshots, results, strict=True):
        values = _values(result, _finding(result, "enforcement_summary"))
        proceedings = snapshot.enforcement_proceedings
        active = tuple(item for item in proceedings if item.is_active)
        active_amounts = tuple(item.amount for item in active if item.amount is not None)
        all_amounts = tuple(item.amount for item in proceedings if item.amount is not None)
        expected = {
            "total_count": len(proceedings),
            "active_count": len(active),
            "inactive_count": len(proceedings) - len(active),
            "known_amount": sum(all_amounts, Decimal(0)) if all_amounts else None,
            "missing_amount_count": len(proceedings) - len(all_amounts),
            "active_known_amount": sum(active_amounts, Decimal(0)) if active_amounts else None,
            "active_missing_amount_count": len(active) - len(active_amounts),
            "future_opened_count": sum(item.opened_at > snapshot.report_at for item in proceedings),
        }
        for key, expected_value in expected.items():
            _equal(values.get(key), expected_value, f"Неверный агрегат производств: {key}")
        with_unknown_amounts += len(active) > len(active_amounts)
        empty_collections += not proceedings
    assert with_unknown_amounts > 0
    assert empty_collections > 0


def test_provider_summaries_preserve_roles_counts_and_missing_values(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    for snapshot, result in zip(source.snapshots, results, strict=True):
        arbitration = _values(result, _finding(result, "arbitration_summary"))
        for key, value in snapshot.arbitration_summary.model_dump(mode="python").items():
            _equal(arbitration.get(key), value, f"Изменён агрегат арбитража: {key}")
        reputation = _values(result, _finding(result, "reputation_summary"))
        _equal(
            reputation.get("positive_count"),
            len(snapshot.reputation.positive),
            "Неверное число положительных сигналов",
        )
        _equal(
            reputation.get("negative_count"),
            len(snapshot.reputation.negative),
            "Неверное число отрицательных сигналов",
        )


def test_confirmed_ruble_unit_is_preserved_in_evidence(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    checked = 0
    for snapshot, result in zip(source.snapshots, results, strict=True):
        if not snapshot.financial_statements:
            continue
        units = _finding(result, "money_units_confirmed")
        source_finance = [
            evidence
            for evidence in snapshot.evidence
            if evidence.canonical_path == "financial_statements.item"
        ]
        assert source_finance and all(
            evidence.currency == "RUB" and evidence.unit == "ruble" for evidence in source_finance
        )
        derived = next(
            evidence
            for evidence in result.derived_evidence
            if evidence.evidence_id in units.evidence_ids
        )
        assert derived.currency == "RUB" and derived.unit == "ruble"
        assert derived.typed_value == {"currency": "RUB", "unit": "ruble"}
        checked += 1
    assert checked > 0


def test_report_age_uses_explicit_policy_and_handles_future_reports(
    source: JsonCounterpartySource,
) -> None:
    snapshot = source.snapshots[0]
    evaluated_at = snapshot.report_at + timedelta(days=10)
    default = analyze_snapshot(snapshot, evaluated_at=evaluated_at)
    _equal(_values(default, _finding(default, "report_age")).get("age_days"), 10, "Давность")
    if _findings(default, "report_stale"):
        pytest.fail("Норматив давности придуман без политики")

    boundary = analyze_snapshot(
        snapshot, evaluated_at=evaluated_at, policy=AnalysisPolicy(max_report_age_days=10)
    )
    if _findings(boundary, "report_stale"):
        pytest.fail("Равенство порогу неверно считается превышением")
    stale = analyze_snapshot(
        snapshot, evaluated_at=evaluated_at, policy=AnalysisPolicy(max_report_age_days=9)
    )
    _finding(stale, "report_stale")
    future = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at - timedelta(days=1))
    _finding(future, "report_future")
    if _findings(future, "report_stale"):
        pytest.fail("Будущий отчёт ошибочно помечен как устаревший")
    for result in (default, boundary, stale, future):
        validate_analysis(result, snapshot)


def test_negative_report_age_policy_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AnalysisPolicy(max_report_age_days=-1)


def test_naive_evaluation_date_is_rejected(source: JsonCounterpartySource) -> None:
    with pytest.raises(ValueError):
        analyze_snapshot(source.snapshots[0], evaluated_at=datetime(2026, 9, 3))


def test_serialization_is_compact_and_excludes_raw_and_personal_data(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
) -> None:
    for snapshot, result in zip(source.snapshots, results, strict=True):
        payload = result.model_dump(mode="json")
        for forbidden_key in ("derived_evidence", "report", "identity", "enforcement_proceedings"):
            if forbidden_key in payload:
                pytest.fail("Компактная сериализация раскрывает полный раздел источника")
        encoded = result.model_dump_json()
        for private_value in (snapshot.identity.full_name, snapshot.identity.inn):
            if private_value in encoded:
                pytest.fail("В компактный аналитический результат попали реквизиты")
        if '"typed_value"' in encoded:
            pytest.fail("В компактный результат включены значения полного ledger")


@pytest.mark.parametrize(
    "change",
    (
        "statement",
        "unknown_reference",
        "unrelated_reference",
        "derived_value",
        "foreign_evidence_scope",
        "foreign_lineage",
        "source_hash",
        "removed_finding",
        "foreign_result",
        "bank_signal",
    ),
)
def test_validation_rejects_tampered_results(
    source: JsonCounterpartySource,
    results: tuple[AnalysisResult, ...],
    change: str,
) -> None:
    """Менять только результат анализа, не создавать вымышленные компании."""

    snapshot = source.snapshots[0]
    foreign = source.snapshots[1]
    result = results[0]
    finding = result.findings[0]
    evidence = result.derived_evidence[0]
    updates: dict[str, Any]
    if change == "statement":
        updates = {
            "findings": (
                finding.model_copy(update={"statement": "Необоснованное новое утверждение"}),
                *result.findings[1:],
            )
        }
    elif change in {"unknown_reference", "unrelated_reference"}:
        reference = (
            "evidence_" + "f" * 24
            if change == "unknown_reference"
            else snapshot.evidence[0].evidence_id
        )
        updates = {
            "findings": (
                finding.model_copy(update={"evidence_ids": (reference,)}),
                *result.findings[1:],
            )
        }
    elif change in {"derived_value", "foreign_evidence_scope", "foreign_lineage", "source_hash"}:
        evidence_update = {
            "derived_value": {"typed_value": {"tampered": True}},
            "foreign_evidence_scope": {"company_id": foreign.company_id},
            "foreign_lineage": {"derived_from": (foreign.evidence[0].evidence_id,)},
            "source_hash": {"source_hash": "f" * 64},
        }[change]
        updates = {
            "derived_evidence": (
                evidence.model_copy(update=evidence_update),
                *result.derived_evidence[1:],
            )
        }
    elif change == "removed_finding":
        updates = {"findings": result.findings[1:]}
    elif change == "bank_signal":
        other_level = (
            BankTrafficLight.RED
            if result.bank_risk.display_level is not BankTrafficLight.RED
            else BankTrafficLight.GREEN
        )
        updates = {
            "bank_risk": result.bank_risk.model_copy(
                update={
                    "raw_level": other_level.value,
                    "recognized_level": other_level,
                    "display_level": other_level,
                }
            )
        }
    else:
        updates = {"company_id": foreign.company_id, "snapshot_id": foreign.snapshot_id}
    corrupted = result.model_copy(update=updates)
    with pytest.raises(AnalysisValidationError):
        validate_analysis(corrupted, snapshot)


@pytest.mark.parametrize("section", ("financial_statements.item", "reputation.negative.item"))
def test_validation_rejects_mismatched_source_metadata(
    source: JsonCounterpartySource,
    section: str,
) -> None:
    snapshot = next(
        item
        for item in source.snapshots
        if any(evidence.canonical_path == section for evidence in item.evidence)
    )
    target = next(item for item in snapshot.evidence if item.canonical_path == section)
    replacement = target.model_copy(update={"stable_key": "wrong_key"})
    corrupted = snapshot.model_copy(
        update={
            "evidence": tuple(
                replacement if item.evidence_id == target.evidence_id else item
                for item in snapshot.evidence
            )
        }
    )
    with pytest.raises(AnalysisValidationError):
        analyze_snapshot(corrupted, evaluated_at=snapshot.report_at)


def test_analysis_does_not_log_source_data(
    source: JsonCounterpartySource,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    snapshot = source.snapshots[0]
    result = analyze_snapshot(snapshot, evaluated_at=snapshot.report_at)
    validate_analysis(result, snapshot)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert not caplog.records


def test_analysis_rejects_real_snapshot_with_missing_required_evidence(
    source: JsonCounterpartySource,
) -> None:
    """Удаление основания проверяет безопасный отказ, а не новую компанию."""

    snapshot = source.snapshots[0]
    without_bank_evidence = snapshot.model_copy(
        update={
            "evidence": tuple(
                item for item in snapshot.evidence if item.canonical_path != "bank_risk"
            )
        }
    )
    with pytest.raises(AnalysisValidationError):
        analyze_snapshot(without_bank_evidence, evaluated_at=snapshot.report_at)


def test_analysis_rejects_canonical_value_that_disagrees_with_evidence(
    source: JsonCounterpartySource,
) -> None:
    for snapshot in source.snapshots:
        if not snapshot.financial_statements:
            continue
        first = snapshot.financial_statements[0]
        if first.profit is None:
            continue
        altered = snapshot.model_copy(
            update={
                "financial_statements": (
                    first.model_copy(update={"profit": first.profit + Decimal(1)}),
                    *snapshot.financial_statements[1:],
                )
            }
        )
        with pytest.raises(AnalysisValidationError):
            analyze_snapshot(altered, evaluated_at=snapshot.report_at)
        return
    pytest.fail("Реальный источник не содержит прибыль для проверки согласованности evidence")


def _findings(
    result: AnalysisResult,
    code: str,
    period: int | str | None = None,
) -> tuple[Finding, ...]:
    return tuple(item for item in result.findings if item.code == code and item.period == period)


def _finding(result: AnalysisResult, code: str, period: int | str | None = None) -> Finding:
    found = _findings(result, code, period)
    if len(found) != 1:
        pytest.fail(f"Ожидался один вывод {code}; найдено: {len(found)}")
    return found[0]


def _values(result: AnalysisResult, finding: Finding) -> dict[str, Any]:
    derived = tuple(
        item for item in result.derived_evidence if item.evidence_id in finding.evidence_ids
    )
    if len(derived) != 1 or not isinstance(derived[0].typed_value, dict):
        pytest.fail(f"Правило {finding.code} не содержит одного структурированного расчёта")
    return derived[0].typed_value


def _check_lineage(
    evidence_id: str,
    ledger: dict[str, Evidence],
    ancestors: tuple[str, ...],
    record_index: int,
) -> None:
    if evidence_id in ancestors:
        pytest.fail(f"Циклический lineage в записи {record_index}")
    if evidence_id not in ledger:
        pytest.fail(f"Неизвестный предок evidence в записи {record_index}")
    evidence = ledger[evidence_id]
    if evidence.kind is EvidenceKind.DERIVED:
        for parent_id in evidence.derived_from:
            _check_lineage(parent_id, ledger, (*ancestors, evidence_id), record_index)


def _equal(actual: object, expected: object, message: str) -> None:
    """Проверить результат без раскрытия исходных значений в отчёте pytest."""

    if actual != expected:
        pytest.fail(message)
