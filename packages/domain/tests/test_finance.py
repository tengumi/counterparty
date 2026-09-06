"""Financial periods, coverage of the reporting timeline and calculations."""

from decimal import Decimal
from typing import Any

import pytest
from conftest import grounded

from counterparty_domain import (
    Availability,
    BalanceConsistency,
    CapitalView,
    EquityPosition,
    EvidenceLedger,
    FactSlot,
    FinancialHistory,
    FinancialMetric,
    FinancialPeriod,
    calculate_period,
    compare_metric,
    parse_decimal,
    summarize_financials,
)
from counterparty_domain.finance import NEGATIVE_EQUITY_NOTE


def money(raw: str) -> FactSlot[Decimal]:
    """Parse a wire decimal into an available slot."""
    return parse_decimal(raw)


def period(year: int, ordinal: int | None = None, **fields: FactSlot[Decimal]) -> FinancialPeriod:
    """Build a dated period with only the named fields supplied."""
    supplied: dict[str, Any] = dict(fields)
    return FinancialPeriod(year=FactSlot[int].available(year), ordinal=ordinal, **supplied)


def test_latest_period_is_chosen_by_year_not_by_array_position() -> None:
    """Index 0 of the source array is not necessarily the newest report."""
    history = FinancialHistory.from_periods(
        [period(2023, ordinal=0), period(2025, ordinal=1), period(2024, ordinal=2)]
    )
    assert history.latest().unwrap().year.unwrap() == 2025
    assert history.coverage().years == (2023, 2024, 2025)


def test_year_without_reporting_stays_unavailable() -> None:
    """A year with no report never borrows the previous year's figures."""
    history = FinancialHistory.from_periods([period(2023, proceeds=money("100"))])
    absent = history.for_year(2024)
    assert not absent.is_available
    assert absent.availability is Availability.MISSING
    assert history.for_year(2023).unwrap().proceeds.unwrap() == Decimal("100")


def test_gaps_in_the_series_are_reported_not_filled() -> None:
    """Holes between the first and last reported year stay visible."""
    history = FinancialHistory.from_periods([period(2021), period(2025)])
    coverage = history.coverage()
    assert coverage.gap_years == (2022, 2023, 2024)
    assert not coverage.is_continuous
    summary = summarize_financials(history)
    assert any("2022" in warning for warning in summary.warnings)


def test_period_without_a_usable_year_is_kept_off_the_timeline() -> None:
    """An undatable record is preserved instead of being dropped or guessed."""
    undated = FinancialPeriod(year=FactSlot[int].missing("common.year absent"))
    history = FinancialHistory.from_periods([period(2024), undated])
    assert len(history) == 1
    assert history.undated == (undated,)
    assert history.coverage().undated_count == 1
    assert any("fiscal year" in warning for warning in history.warnings)


def test_duplicate_years_are_flagged_and_resolved_by_source_order() -> None:
    """Two records for one year are ambiguous, not silently merged."""
    history = FinancialHistory.from_periods(
        [
            period(2024, ordinal=1, proceeds=money("200")),
            period(2024, ordinal=0, proceeds=money("100")),
        ]
    )
    assert history.coverage().duplicate_years == (2024,)
    chosen = history.for_year(2024)
    assert chosen.unwrap().proceeds.unwrap() == Decimal("100")
    assert chosen.warnings


def test_empty_section_is_present_empty_and_carries_no_calculation() -> None:
    """No reporting at all is not a company with zero revenue."""
    history = FinancialHistory.from_periods([], confirms_absence=True)
    assert history.availability is Availability.PRESENT_EMPTY
    summary = summarize_financials(history)
    assert summary.latest_calculation is None
    assert summary.latest_period.availability is Availability.PRESENT_EMPTY
    assert summary.latest_period.is_evidence_of_absence
    assert not summary.has_reporting


def test_missing_component_keeps_the_obligations_total_unknown() -> None:
    """A missing liability section is not a zero liability."""
    calculation = calculate_period(period(2025, short_term_total=money("500")))
    assert not calculation.reported_obligations.is_available
    assert calculation.reported_obligations.is_unknown


def test_zero_component_is_summed_while_missing_one_is_not() -> None:
    """A real zero participates in the total; an absent value blocks it."""
    with_zero = calculate_period(
        period(2025, long_term_total=money("0"), short_term_total=money("500"))
    )
    assert with_zero.reported_obligations.unwrap() == Decimal("500")
    with_empty = calculate_period(
        period(2025, long_term_total=parse_decimal(""), short_term_total=money("500"))
    )
    assert not with_empty.reported_obligations.is_available


def test_liabilities_side_total_is_not_used_as_an_amount_of_debt() -> None:
    """``totalLiabilities`` is the balance total, never the debt figure."""
    calculation = calculate_period(
        period(
            2025,
            total_assets=money("39448000"),
            balance_total_liabilities_side=money("39448000"),
            equity=money("22836000"),
            long_term_total=money("0"),
            short_term_total=money("16612000"),
        )
    )
    assert calculation.reported_obligations.unwrap() == Decimal("16612000")
    assert calculation.balance_consistency is BalanceConsistency.CONSISTENT
    assert calculation.balance_gap.unwrap() == 0


def test_balance_gap_is_reported_when_the_two_sides_disagree() -> None:
    """A mismatch between the sides is surfaced, not silently absorbed."""
    calculation = calculate_period(
        period(
            2025,
            total_assets=money("100"),
            balance_total_liabilities_side=money("90"),
        )
    )
    assert calculation.balance_consistency is BalanceConsistency.INCONSISTENT
    assert calculation.balance_gap.unwrap() == Decimal("10")
    assert any("do not match" in note for note in calculation.notes)


def test_negative_equity_is_an_observation_not_a_bankruptcy_verdict() -> None:
    """Negative reported capital carries an explicit interpretation note."""
    calculation = calculate_period(period(2025, equity=money("-300000")))
    assert calculation.equity_position is EquityPosition.NEGATIVE
    assert NEGATIVE_EQUITY_NOTE in calculation.notes
    assert "bankrupt" not in " ".join(calculation.notes).replace(NEGATIVE_EQUITY_NOTE, "")


def test_unknown_equity_is_not_reported_as_zero_capital() -> None:
    """An absent capital value has an unknown sign, not a zero one."""
    assert calculate_period(period(2025)).equity_position is EquityPosition.UNKNOWN
    assert calculate_period(period(2025, equity=money("0"))).equity_position is EquityPosition.ZERO


def test_profit_margin_is_undefined_when_proceeds_are_zero() -> None:
    """A zero denominator produces no ratio, and never a zero ratio."""
    calculation = calculate_period(period(2025, profit=money("10"), proceeds=money("0")))
    assert not calculation.profit_margin.is_available
    assert calculation.profit_margin.is_unknown
    assert "undefined" in (calculation.profit_margin.reason or "")


def test_change_across_a_reporting_hole_is_not_year_on_year() -> None:
    """A comparison spanning unreported years says so."""
    history = FinancialHistory.from_periods(
        [period(2021, proceeds=money("100")), period(2025, proceeds=money("150"))]
    )
    change = compare_metric(history, FinancialMetric.PROCEEDS)
    assert change.absolute.unwrap() == Decimal("50")
    assert change.relative.unwrap() == Decimal("0.500000")
    assert change.years_skipped == 3
    assert not change.is_year_on_year


def test_change_without_an_earlier_period_stays_unknown() -> None:
    """A single reported year yields no movement, not a zero movement."""
    history = FinancialHistory.from_periods([period(2025, proceeds=money("100"))])
    change = compare_metric(history, FinancialMetric.PROCEEDS)
    assert not change.absolute.is_available
    assert change.from_year is None
    assert change.to_year == 2025


def test_relative_change_from_zero_is_unknown() -> None:
    """Growth from a zero base has no relative value."""
    history = FinancialHistory.from_periods(
        [period(2024, proceeds=money("0")), period(2025, proceeds=money("100"))]
    )
    change = compare_metric(history, FinancialMetric.PROCEEDS)
    assert change.absolute.unwrap() == Decimal("100")
    assert not change.relative.is_available


def test_charter_capital_reported_capital_and_balance_total_stay_distinct() -> None:
    """The three capital-shaped amounts are never merged or substituted."""
    view = CapitalView(
        year=2025,
        share_capital=money("10000"),
        reported_equity=money("-300000"),
        balance_total_liabilities_side=money("39448000"),
    )
    assert view.equity_position is EquityPosition.NEGATIVE
    assert view.notes == (NEGATIVE_EQUITY_NOTE,)
    assert view.equity_over_share_capital().unwrap() == Decimal("-310000")
    assert view.balance_total_liabilities_side.unwrap() == Decimal("39448000")


def test_charter_capital_comparison_is_unknown_when_it_was_not_reported() -> None:
    """A company without a stated charter capital gets no invented one."""
    view = CapitalView(year=2025, reported_equity=money("100"))
    assert not view.equity_over_share_capital().is_available


def test_summary_grounds_every_computed_value_in_its_inputs(ledger: EvidenceLedger) -> None:
    """A computed number expands to the report fields it came from."""
    history = FinancialHistory.from_periods(
        [
            period(
                2025,
                long_term_total=grounded(
                    "0", "e:lt", "/finReports/0/liabilities/longTermDuties/total", ledger
                ),
                short_term_total=grounded(
                    "500", "e:st", "/finReports/0/liabilities/shortTermLiabilities/total", ledger
                ),
            )
        ]
    )
    summary = summarize_financials(history, ledger=ledger)
    assert summary.latest_calculation is not None
    total = summary.latest_calculation.reported_obligations
    assert total.unwrap() == Decimal("500")
    (ref_id,) = total.evidence_refs
    resolution = ledger.resolve(ref_id)
    assert resolution.is_resolvable
    assert resolution.primary_sources == ("e:lt", "e:st")


def test_ungrounded_computation_does_not_invent_evidence(ledger: EvidenceLedger) -> None:
    """A value with no input evidence is rejected rather than fabricated."""
    history = FinancialHistory.from_periods(
        [period(2025, long_term_total=money("0"), short_term_total=money("500"))]
    )
    with pytest.raises(Exception, match="no resolvable evidence"):
        summarize_financials(history, ledger=ledger)


def test_summary_carries_requested_metric_changes_and_their_warnings() -> None:
    """Requested comparisons reach the summary together with their caveats."""
    history = FinancialHistory.from_periods(
        [
            period(2022, proceeds=money("100"), profit=money("10")),
            period(2025, proceeds=money("150"), profit=money("5")),
        ]
    )
    summary = summarize_financials(
        history, change_metrics=(FinancialMetric.PROCEEDS, FinancialMetric.PROFIT)
    )
    assert [change.metric for change in summary.changes] == [
        FinancialMetric.PROCEEDS,
        FinancialMetric.PROFIT,
    ]
    assert summary.changes[1].absolute.unwrap() == Decimal("-5")
    assert any("not year-on-year" in warning for warning in summary.warnings)


def test_metric_lookup_returns_the_named_reported_field() -> None:
    """Metric names address exactly one documented source column."""
    reported = period(2025, receivables=money("24998000"))
    assert reported.metric(FinancialMetric.RECEIVABLES).unwrap() == Decimal("24998000")
    assert not reported.metric(FinancialMetric.STOCKS).is_available
