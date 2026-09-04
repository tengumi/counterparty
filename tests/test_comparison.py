"""Явное сравнение реальных карточек без сети, новых компаний и синтетических сумм."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_DOWN, localcontext
from pathlib import Path

import pytest

from counterparty_agent.analytics.common import AnalysisValidationError
from counterparty_agent.analytics.comparison import compare_snapshots, validate_comparison
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import (
    ComparisonCell,
    ComparisonResult,
    ComparisonRow,
    CounterpartySnapshot,
    FindingDataStatus,
    FindingSeverity,
    PartyType,
)


@pytest.fixture(scope="module")
def snapshots() -> tuple[CounterpartySnapshot, ...]:
    path = Path(Settings().snapshot_json_path)
    if not path.is_file():
        pytest.skip("Реальный snapshot не настроен в COUNTERPARTY_SNAPSHOT_JSON_PATH")
    return JsonCounterpartySource.from_path(path).snapshots


@pytest.fixture(scope="module")
def evaluated_at(snapshots: tuple[CounterpartySnapshot, ...]) -> datetime:
    return max(item.report_at for item in snapshots) + timedelta(days=1)


def _row(result: ComparisonResult, key: str) -> ComparisonRow:
    return next(row for row in result.rows if row.key == key)


def _replace_cell(result: ComparisonResult, key: str, cell: ComparisonCell) -> ComparisonResult:
    row = _row(result, key)
    changed = row.model_copy(update={"cells": (cell, *row.cells[1:])})
    return result.model_copy(
        update={"rows": tuple(changed if item.key == key else item for item in result.rows)}
    )


@pytest.mark.parametrize("count", [2, 10, 11, 20])
def test_comparison_is_ordered_reproducible_and_scoped(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime, count: int
) -> None:
    selected = snapshots[:count]
    result = compare_snapshots(selected, evaluated_at=evaluated_at)
    assert result == compare_snapshots(selected, evaluated_at=evaluated_at)
    assert result.snapshot_ids == tuple(item.snapshot_id for item in selected)
    assert all(
        tuple(cell.snapshot_id for cell in row.cells) == result.snapshot_ids for row in result.rows
    )
    assert len(result.rows) == 22
    validate_comparison(result, selected)
    for index, snapshot in enumerate(selected):
        analysis = analyze_snapshot(snapshot, evaluated_at=evaluated_at)
        allowed = {
            item.evidence_id
            for item in snapshot.evidence
            if item.canonical_path in {"identity", "status", "report_at", "bank_risk"}
        } | {item.evidence_id for item in analysis.derived_evidence}
        for row in result.rows:
            assert row.cells[index].evidence_ids
            assert set(row.cells[index].evidence_ids) <= allowed
        serialized = result.model_dump_json()
        for value in (snapshot.identity.inn, snapshot.identity.ogrn, snapshot.identity.full_name):
            if value in serialized:
                pytest.fail("Сравнение раскрыло реквизиты вне карточки")


@pytest.mark.parametrize("count", [0, 1])
def test_comparison_rejects_outside_size_limit(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime, count: int
) -> None:
    with pytest.raises(AnalysisValidationError, match="хотя бы 2"):
        compare_snapshots(snapshots[:count], evaluated_at=evaluated_at)


def test_comparison_rejects_duplicate_company_and_naive_date(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    first = snapshots[0]
    for other in (first, first.model_copy(update={"snapshot_id": snapshots[1].snapshot_id})):
        with pytest.raises(AnalysisValidationError, match="повторяющихся"):
            compare_snapshots((first, other), evaluated_at=evaluated_at)
    with pytest.raises(AnalysisValidationError, match="часовой пояс"):
        compare_snapshots(snapshots[:2], evaluated_at=evaluated_at.replace(tzinfo=None))


def test_last_common_financial_year_not_individual_latest(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    long = next(item for item in snapshots if len(item.financial_statements or ()) >= 3)
    short = next(item for item in snapshots if len(item.financial_statements or ()) == 1)
    selected = (long, short)
    expected_year = max(
        {item.year for item in long.financial_statements or ()}
        & {item.year for item in short.financial_statements or ()}
    )
    result = compare_snapshots(selected, evaluated_at=evaluated_at)
    assert result.financial_year == expected_year
    for index, snapshot in enumerate(selected):
        statement = next(
            item for item in snapshot.financial_statements or () if item.year == expected_year
        )
        for key, value in (
            ("proceeds", statement.proceeds),
            ("profit", statement.profit),
            ("assets_total", statement.assets.total),
            ("liabilities_total", statement.liabilities.total),
            ("equity", statement.liabilities.capital_and_reserves),
        ):
            row = _row(result, f"financial_{key}")
            assert row.period == expected_year
            assert row.cells[index].value == (str(value) if value is not None else None)
            assert row.comparable is False
    assert max(item.year for item in long.financial_statements or ()) > expected_year


def test_no_common_year_uses_one_explicit_year_and_preserves_missing(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    full = next(item for item in snapshots if item.financial_statements)
    missing = next(item for item in snapshots if not item.financial_statements)
    result = compare_snapshots((full, missing), evaluated_at=evaluated_at)
    assert result.financial_year == max(item.year for item in full.financial_statements or ())
    assert any("Общего завершённого финансового года нет" in item for item in result.limitations)
    for row in result.rows:
        if row.category == "finance":
            assert row.period == result.financial_year
            assert row.cells[1].value is None
            assert row.cells[1].data_status in {
                FindingDataStatus.INSUFFICIENT,
                FindingDataStatus.INAPPLICABLE,
            }
            assert "Нет отчёта" in row.cells[1].display_value
    validate_comparison(result, (full, missing))


def test_all_financial_data_missing_never_becomes_zero(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    selected = tuple(item for item in snapshots if not item.financial_statements)[:2]
    result = compare_snapshots(selected, evaluated_at=evaluated_at)
    assert result.financial_year is None
    for row in result.rows:
        if row.category == "finance":
            assert row.period is None
            assert all(cell.value is None for cell in row.cells)
    validate_comparison(result, selected)


def test_partial_financial_fields_remain_missing_at_selected_year(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    selected = next(
        item
        for item in snapshots
        if item.financial_statements
        and max(
            item.financial_statements, key=lambda row: row.year
        ).liabilities.capital_and_reserves
        is None
    )
    other = next(
        item
        for item in snapshots
        if item.snapshot_id != selected.snapshot_id and not item.financial_statements
    )
    result = compare_snapshots((selected, other), evaluated_at=evaluated_at)
    cell = _row(result, "financial_equity").cells[0]
    assert cell.value is None
    assert cell.data_status is FindingDataStatus.INSUFFICIENT


def test_bank_signal_and_mixed_types_are_not_reranked(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    legal = next(item for item in snapshots if item.identity.party_type is PartyType.LEGAL_ENTITY)
    entrepreneur = next(
        item for item in snapshots if item.identity.party_type is PartyType.INDIVIDUAL_ENTREPRENEUR
    )
    selected = (legal, entrepreneur)
    result = compare_snapshots(selected, evaluated_at=evaluated_at)
    row = _row(result, "bank_risk")
    assert [cell.value for cell in row.cells] == [item.bank_risk.raw_level for item in selected]
    assert row.comparable is False
    assert any("неоднородная группа" in item for item in result.limitations)
    assert _row(result, "party_type").cells[0].display_value == "ЮЛ"
    assert _row(result, "party_type").cells[1].display_value == "ИП"
    if legal.report_at != entrepreneur.report_at:
        assert any("Даты снимков различаются" in item for item in result.limitations)
    assert "winner" not in result.model_dump()


def test_court_roles_and_enforcement_coverage_remain_separate(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    selected = sorted(snapshots, key=lambda item: len(item.enforcement_proceedings), reverse=True)[
        :2
    ]
    result = compare_snapshots(selected, evaluated_at=evaluated_at)
    for index, snapshot in enumerate(selected):
        for role in ("as_plaintiff", "as_defendant"):
            for field in ("finished_count", "pending_count", "appealed_count"):
                row = _row(result, f"arbitration_{role}_{field}")
                assert row.cells[index].value == getattr(
                    getattr(snapshot.arbitration_summary, role), field
                )
                assert row.comparable is False
        records = snapshot.enforcement_proceedings
        assert _row(result, "enforcement_total_count").cells[index].value == len(records)
        assert _row(result, "enforcement_active_count").cells[index].value == sum(
            item.is_active for item in records
        )
        missing = sum(item.amount is None for item in records)
        assert _row(result, "enforcement_missing_amount_count").cells[index].value == missing
        amount = _row(result, "enforcement_known_amount").cells[index]
        assert f"без суммы: {missing}" in amount.display_value
        assert "Единицы источника" in amount.display_value


def test_attention_row_uses_verified_findings_and_is_not_a_risk_score(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    selected = snapshots[:10]
    result = compare_snapshots(selected, evaluated_at=evaluated_at)
    row = _row(result, "attention_signals")
    assert row.comparable is False
    for snapshot, cell in zip(selected, row.cells, strict=True):
        analysis = analyze_snapshot(snapshot, evaluated_at=evaluated_at)
        attention = tuple(
            item for item in analysis.findings if item.severity is FindingSeverity.ATTENTION
        )
        assert cell.value == len(attention)
        for finding in attention[:3]:
            assert finding.statement in cell.display_value
            assert set(finding.evidence_ids) <= set(cell.evidence_ids)
        if not attention:
            assert "это не отсутствие риска" in cell.display_value


def test_comparison_decimal_values_do_not_depend_on_callers_context(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    expected = compare_snapshots(snapshots[:2], evaluated_at=evaluated_at)
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        assert compare_snapshots(snapshots[:2], evaluated_at=evaluated_at) == expected
        assert context.prec == 6


def test_comparison_replay_rejects_tampering_and_foreign_evidence(
    snapshots: tuple[CounterpartySnapshot, ...], evaluated_at: datetime
) -> None:
    selected = snapshots[:2]
    result = compare_snapshots(selected, evaluated_at=evaluated_at)
    row = _row(result, "financial_proceeds")
    first = row.cells[0]
    invalid = [
        _replace_cell(result, row.key, first.model_copy(update={"value": "999999999999"})),
        _replace_cell(
            result, row.key, first.model_copy(update={"display_value": "Гарантированно лучше"})
        ),
        _replace_cell(
            result, row.key, first.model_copy(update={"evidence_ids": row.cells[1].evidence_ids})
        ),
        _replace_cell(result, row.key, first.model_copy(update={"evidence_ids": ("unknown",)})),
        _replace_cell(result, row.key, first.model_copy(update={"evidence_ids": ()})),
        result.model_copy(update={"financial_year": 1900}),
        result.model_copy(update={"limitations": ()}),
        result.model_copy(update={"rows": result.rows[:-1]}),
    ]
    changed_row = row.model_copy(update={"comparable": True})
    invalid.append(
        result.model_copy(
            update={
                "rows": tuple(changed_row if item.key == row.key else item for item in result.rows)
            }
        )
    )
    for item in invalid:
        with pytest.raises(AnalysisValidationError):
            validate_comparison(item, selected)
    with pytest.raises(AnalysisValidationError):
        validate_comparison(result, selected[::-1])
