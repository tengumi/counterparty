"""Arbitration aggregates stay aggregates and stay in their own breakdown."""

from decimal import Decimal

from counterparty_domain import (
    AggregationKind,
    ArbitrationAggregate,
    Availability,
    CaseStatus,
    FactSlot,
    PartyRole,
    ReportedTotals,
    parse_decimal,
    parse_integer,
    summarize_arbitration,
)


def status_slice(
    role: PartyRole, status: CaseStatus, count: object, amount: object
) -> ArbitrationAggregate:
    """Build one status slice from wire-shaped values."""
    return ArbitrationAggregate(
        aggregation=AggregationKind.STATUS,
        role=role,
        status=status,
        count=parse_integer(count),
        amount=parse_decimal(amount),
    )


def year_slice(role: PartyRole, year: int, count: object, amount: object) -> ArbitrationAggregate:
    """Build one yearly slice from wire-shaped values."""
    return ArbitrationAggregate(
        aggregation=AggregationKind.YEAR,
        role=role,
        year=year,
        count=parse_integer(count),
        amount=parse_decimal(amount),
    )


def test_status_slices_are_summed_within_a_role() -> None:
    """Slices of one breakdown are disjoint, so summing them is valid."""
    summary = summarize_arbitration(
        [
            status_slice(PartyRole.DEFENDANT, CaseStatus.FINISHED, 2, "100"),
            status_slice(PartyRole.DEFENDANT, CaseStatus.PENDING, 1, "50"),
        ]
    )
    totals = summary.totals_for(AggregationKind.STATUS, PartyRole.DEFENDANT)
    assert totals is not None
    assert totals.count.unwrap() == 3
    assert totals.amount.unwrap() == Decimal("150")


def test_reported_total_is_kept_apart_from_the_breakdown() -> None:
    """The provided grand total is never added to or replaced by the slices."""
    summary = summarize_arbitration(
        [
            status_slice(PartyRole.DEFENDANT, CaseStatus.FINISHED, 2, "100"),
            status_slice(PartyRole.PLAINTIFF, CaseStatus.PENDING, 1, "50"),
        ],
        reported=ReportedTotals(count=parse_integer(5), amount=parse_decimal("400")),
    )
    assert summary.reported.amount.unwrap() == Decimal("400")
    defendant = summary.totals_for(AggregationKind.STATUS, PartyRole.DEFENDANT)
    assert defendant is not None
    assert defendant.amount.unwrap() == Decimal("100")
    assert summary.reconciliation.unwrap() == Decimal("250")
    assert any("not added together" in warning for warning in summary.warnings)


def test_year_and_status_breakdowns_are_never_merged() -> None:
    """The two breakdowns describe the same cases from different angles."""
    summary = summarize_arbitration(
        [
            status_slice(PartyRole.PLAINTIFF, CaseStatus.FINISHED, 1, "10"),
            year_slice(PartyRole.PLAINTIFF, 2024, 1, "10"),
        ]
    )
    status_totals = summary.totals_for(AggregationKind.STATUS, PartyRole.PLAINTIFF)
    year_totals = summary.totals_for(AggregationKind.YEAR, PartyRole.PLAINTIFF)
    assert status_totals is not None and year_totals is not None
    assert status_totals.amount.unwrap() == Decimal("10")
    assert year_totals.amount.unwrap() == Decimal("10")
    assert status_totals.slice_count == 1
    assert year_totals.slice_count == 1


def test_empty_status_object_does_not_become_a_confirmed_zero() -> None:
    """``{}`` under a status keeps the count unknown, not ``0``."""
    empty = ArbitrationAggregate(
        aggregation=AggregationKind.STATUS,
        role=PartyRole.DEFENDANT,
        status=CaseStatus.APPEALED,
        count=FactSlot[int].present_empty("status object was empty"),
        amount=FactSlot[Decimal].present_empty("status object was empty"),
    )
    summary = summarize_arbitration(
        [status_slice(PartyRole.DEFENDANT, CaseStatus.FINISHED, 2, "100"), empty]
    )
    totals = summary.totals_for(AggregationKind.STATUS, PartyRole.DEFENDANT)
    assert totals is not None
    assert not totals.count.is_available
    assert not totals.amount.is_available


def test_role_without_slices_yields_present_empty_totals() -> None:
    """No slice for a role is not the same as a confirmed zero for it."""
    summary = summarize_arbitration(
        [status_slice(PartyRole.DEFENDANT, CaseStatus.FINISHED, 2, "100")]
    )
    plaintiff = summary.totals_for(AggregationKind.STATUS, PartyRole.PLAINTIFF)
    assert plaintiff is not None
    assert plaintiff.count.availability is Availability.PRESENT_EMPTY
    assert plaintiff.slice_count == 0


def test_empty_breakdown_does_not_prove_the_absence_of_cases() -> None:
    """An arbitration object with no slices proves nothing on its own."""
    summary = summarize_arbitration([])
    assert summary.availability is Availability.PRESENT_EMPTY
    assert any("does not prove" in warning for warning in summary.warnings)


def test_reconciliation_is_unknown_when_either_side_is_unknown() -> None:
    """Without a reported total there is no discrepancy to report."""
    summary = summarize_arbitration(
        [
            status_slice(PartyRole.DEFENDANT, CaseStatus.FINISHED, 2, "100"),
            status_slice(PartyRole.PLAINTIFF, CaseStatus.PENDING, 1, "50"),
        ]
    )
    assert not summary.reconciliation.is_available


def test_reconciliation_is_unknown_when_a_role_has_no_slices() -> None:
    """A role the source never described leaves the breakdown incomplete."""
    summary = summarize_arbitration(
        [status_slice(PartyRole.DEFENDANT, CaseStatus.FINISHED, 2, "100")],
        reported=ReportedTotals(count=parse_integer(5), amount=parse_decimal("400")),
    )
    assert not summary.reconciliation.is_available
    assert summary.reconciliation.is_unknown
