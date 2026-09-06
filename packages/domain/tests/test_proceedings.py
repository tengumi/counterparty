"""Enforcement proceedings: counts, amounts and what stays unknown."""

from datetime import date
from decimal import Decimal

from conftest import grounded

from counterparty_domain import (
    Availability,
    EvidenceLedger,
    ExecutionProceeding,
    FactSlot,
    ProceedingStatus,
    parse_date,
    parse_decimal,
    summarize_proceedings,
)


def proceeding(
    *,
    active: bool | None = None,
    amount: str | None = None,
    started: str | None = None,
    number: str | None = None,
) -> ExecutionProceeding:
    """Build one proceeding from wire-shaped values."""
    return ExecutionProceeding(
        number=FactSlot[str].available(number)
        if number is not None
        else FactSlot[str].missing("no number"),
        started_at=parse_date(started)
        if started is not None
        else FactSlot[date].missing("no date"),
        active=FactSlot[bool].available(active)
        if active is not None
        else FactSlot[bool].missing("no active flag"),
        amount=parse_decimal(amount)
        if amount is not None
        else FactSlot[Decimal].missing("no amount"),
    )


def test_empty_section_does_not_prove_the_absence_of_proceedings() -> None:
    """An empty array only proves absence when the semantics were confirmed."""
    unconfirmed = summarize_proceedings([])
    assert unconfirmed.availability is Availability.PRESENT_EMPTY
    assert not unconfirmed.proves_no_proceedings
    assert unconfirmed.warnings
    confirmed = summarize_proceedings([], confirms_absence=True)
    assert confirmed.proves_no_proceedings


def test_missing_section_is_not_an_empty_one() -> None:
    """A section the report never carried stays missing."""
    summary = summarize_proceedings([], availability=Availability.MISSING)
    assert summary.availability is Availability.MISSING
    assert not summary.proves_no_proceedings


def test_a_proceeding_without_an_amount_keeps_the_total_unknown() -> None:
    """The known part is a lower bound and never becomes the total."""
    summary = summarize_proceedings(
        [
            proceeding(active=True, amount="517235.54"),
            proceeding(active=True),
        ]
    )
    assert summary.overall is not None
    assert not summary.overall.total.is_available
    assert summary.overall.total.is_unknown
    assert summary.overall.known_subtotal.unwrap() == Decimal("517235.54")
    assert summary.overall.unknown_count == 1
    assert not summary.overall.is_complete
    assert any("lower bound" in warning for warning in summary.warnings)


def test_a_zero_amount_is_an_amount() -> None:
    """Zero is a reported value, so the total stays computable."""
    summary = summarize_proceedings(
        [proceeding(active=True, amount="0"), proceeding(active=True, amount="24.63")]
    )
    assert summary.overall is not None
    assert summary.overall.total.unwrap() == Decimal("24.63")
    assert summary.overall.is_complete
    assert summary.overall.unknown_count == 0


def test_an_invalid_amount_is_not_a_zero() -> None:
    """A malformed number blocks the total instead of degrading to zero."""
    summary = summarize_proceedings(
        [proceeding(active=True, amount="n/a"), proceeding(active=True, amount="10")]
    )
    assert summary.overall is not None
    assert not summary.overall.total.is_available
    assert summary.overall.known_subtotal.unwrap() == Decimal("10")


def test_unknown_status_keeps_active_and_closed_totals_unknown() -> None:
    """A record that does not state its status is never counted as closed."""
    summary = summarize_proceedings([proceeding(active=True, amount="10"), proceeding(amount="5")])
    assert summary.active_count == 1
    assert summary.closed_count == 0
    assert summary.status_unknown_count == 1
    assert summary.active is not None and summary.closed is not None
    assert not summary.active.total.is_available
    assert not summary.closed.total.is_available
    assert summary.overall is not None
    assert summary.overall.total.unwrap() == Decimal("15")


def test_active_and_closed_amounts_are_split_when_every_status_is_known() -> None:
    """With all statuses known the two totals are computable and disjoint."""
    summary = summarize_proceedings(
        [
            proceeding(active=True, amount="24.63"),
            proceeding(active=False, amount="52024.63"),
        ]
    )
    assert summary.active is not None and summary.closed is not None
    assert summary.active.total.unwrap() == Decimal("24.63")
    assert summary.closed.total.unwrap() == Decimal("52024.63")
    assert summary.overall is not None
    assert summary.overall.total.unwrap() == Decimal("52049.26")


def test_status_property_is_three_valued() -> None:
    """Active, closed and unknown are distinct states."""
    assert proceeding(active=True).status is ProceedingStatus.ACTIVE
    assert proceeding(active=False).status is ProceedingStatus.CLOSED
    assert proceeding().status is ProceedingStatus.UNKNOWN


def test_date_bounds_ignore_undated_records_but_count_them() -> None:
    """Records without a usable date do not shift the known bounds."""
    summary = summarize_proceedings(
        [
            proceeding(active=False, amount="1", started="2024-11-10"),
            proceeding(active=False, amount="2", started="2026-03-30"),
            proceeding(active=True, amount="3"),
        ]
    )
    assert summary.earliest_start.unwrap() == date(2024, 11, 10)
    assert summary.latest_start.unwrap() == date(2026, 3, 30)
    assert summary.undated_count == 1
    assert any("start date" in warning for warning in summary.warnings)


def test_no_usable_date_leaves_the_bounds_unknown() -> None:
    """Without any parseable date the bounds stay unavailable."""
    summary = summarize_proceedings([proceeding(active=True, started="not-a-date")])
    assert not summary.earliest_start.is_available
    assert not summary.latest_start.is_available


def test_totals_are_grounded_in_the_records_they_were_computed_from(
    ledger: EvidenceLedger,
) -> None:
    """An amount total expands back to each proceeding's source field."""
    records = [
        ExecutionProceeding(
            active=FactSlot[bool].available(True),
            amount=grounded("10", "e:p0", "/executionProceedings/0/amount", ledger),
            evidence_refs=("e:p0",),
        ),
        ExecutionProceeding(
            active=FactSlot[bool].available(True),
            amount=grounded("5", "e:p1", "/executionProceedings/1/amount", ledger),
            evidence_refs=("e:p1",),
        ),
    ]
    summary = summarize_proceedings(records, ledger=ledger)
    assert summary.overall is not None
    (ref_id,) = summary.overall.total.evidence_refs
    resolution = ledger.resolve(ref_id)
    assert resolution.is_resolvable
    assert resolution.primary_sources == ("e:p0", "e:p1")


def test_unknown_total_is_still_grounded_in_the_records(ledger: EvidenceLedger) -> None:
    """An unknown total is itself a claim about identified records."""
    records = [
        ExecutionProceeding(
            active=FactSlot[bool].available(True),
            amount=grounded("10", "e:p0", "/executionProceedings/0/amount", ledger),
            evidence_refs=("e:p0",),
        ),
        ExecutionProceeding(
            active=FactSlot[bool].available(True),
            amount=FactSlot[Decimal].missing("amount absent"),
            evidence_refs=("e:p0",),
        ),
    ]
    summary = summarize_proceedings(records, ledger=ledger)
    assert summary.overall is not None
    assert not summary.overall.total.is_available
    (ref_id,) = summary.overall.total.evidence_refs
    assert ledger.resolve(ref_id).primary_sources == ("e:p0",)
