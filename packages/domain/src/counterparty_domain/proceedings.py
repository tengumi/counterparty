"""Deterministic summary of enforcement (execution) proceedings.

Each source record carries a number, a start date, an active flag and an
amount, and any of them may be absent. The summary keeps three things apart
that are easy to merge by accident:

* a proceeding whose amount is unknown — the total is then unknown too;
* a proceeding whose amount is a real zero — it counts as an amount;
* the absence of proceedings — which only proves "no records" when the source
  section was confirmed empty.

The total therefore never silently becomes a lower bound. The known part is
published separately, as an explicit subtotal with its own count, so a caller
can say "at least X across N of M records" without claiming a total.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from counterparty_contracts import Availability

from .derivation import DEFAULT_RULE_VERSION, attach_derivation
from .evidence import EvidenceLedger
from .facts import FactSlot
from .values import sum_decimals

__all__ = [
    "AmountCoverage",
    "ExecutionProceeding",
    "ProceedingStatus",
    "ProceedingsSummary",
    "summarize_proceedings",
]


def _absent_amount() -> FactSlot[Decimal]:
    """Default slot for a proceeding whose amount was not supplied."""
    return FactSlot[Decimal].missing("proceeding amount was not supplied to the domain layer")


class ProceedingStatus(StrEnum):
    """Whether a proceeding is currently being enforced."""

    ACTIVE = "active"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExecutionProceeding:
    """One enforcement proceeding as the source described it."""

    number: FactSlot[str] = field(
        default_factory=lambda: FactSlot[str].missing("proceeding number was not supplied")
    )
    started_at: FactSlot[date] = field(
        default_factory=lambda: FactSlot[date].missing("proceeding start date was not supplied")
    )
    active: FactSlot[bool] = field(
        default_factory=lambda: FactSlot[bool].missing("proceeding active flag was not supplied")
    )
    amount: FactSlot[Decimal] = field(default_factory=_absent_amount)
    evidence_refs: tuple[str, ...] = ()

    @property
    def status(self) -> ProceedingStatus:
        """Three-valued status: an unknown flag never means "closed"."""
        if not self.active.is_available:
            return ProceedingStatus.UNKNOWN
        return ProceedingStatus.ACTIVE if self.active.unwrap() else ProceedingStatus.CLOSED


@dataclass(frozen=True, slots=True)
class AmountCoverage:
    """How much of a group of proceedings carries a usable amount.

    Attributes:
        total: Sum over the group, unknown when any member's amount is
            unknown. It is never reduced to the known part.
        known_subtotal: Sum over the members whose amount is known. It is a
            lower bound, valid only together with ``unknown_count``.
        record_count: Members of the group.
        known_count: Members whose amount is known, zeros included.
        unknown_count: Members whose amount is missing, empty, malformed or
            withheld.
    """

    total: FactSlot[Decimal]
    known_subtotal: FactSlot[Decimal]
    record_count: int
    known_count: int
    unknown_count: int

    @property
    def is_complete(self) -> bool:
        """Whether every member of the group carries a usable amount."""
        return self.record_count > 0 and self.unknown_count == 0


def _record_refs(proceedings: Sequence[ExecutionProceeding]) -> tuple[str, ...]:
    """Collect every evidence id backing a group of records, without repeats."""
    collected: list[str] = []
    for item in proceedings:
        for ref in (*item.evidence_refs, *item.amount.evidence_refs):
            if ref not in collected:
                collected.append(ref)
    return tuple(collected)


def _amount_coverage(proceedings: Sequence[ExecutionProceeding], *, label: str) -> AmountCoverage:
    """Sum a group's amounts, keeping the unknown part visible."""
    amounts = [item.amount for item in proceedings]
    known = [slot for slot in amounts if slot.is_available]
    seed = _record_refs(proceedings)
    total = sum_decimals(amounts, label=label, evidence_refs=seed)
    subtotal = sum_decimals(known, label=f"known part of {label}", evidence_refs=seed)
    return AmountCoverage(
        total=total,
        known_subtotal=subtotal,
        record_count=len(amounts),
        known_count=len(known),
        unknown_count=len(amounts) - len(known),
    )


@dataclass(frozen=True, slots=True)
class ProceedingsSummary:
    """Counts, amounts and dates over one company's proceedings.

    Attributes:
        availability: Availability of the source section as a whole.
        confirms_absence: Only for ``present_empty``: whether the empty
            section was confirmed to mean "no proceedings". Without that
            confirmation an empty section is not evidence of absence.
        status_unknown_count: Records whose active flag is unknown. While it
            is above zero, the active figures stay unknown as well.
        active: Amounts over the records known to be active.
        closed: Amounts over the records known to be closed.
        overall: Amounts over every record, whatever its status.
        earliest_start / latest_start: Bounds of the known start dates.
        undated_count: Records with no usable start date.
    """

    availability: Availability
    confirms_absence: bool = False
    record_count: int = 0
    active_count: int = 0
    closed_count: int = 0
    status_unknown_count: int = 0
    active: AmountCoverage | None = None
    closed: AmountCoverage | None = None
    overall: AmountCoverage | None = None
    earliest_start: FactSlot[date] = field(
        default_factory=lambda: FactSlot[date].missing("no proceeding start date is known")
    )
    latest_start: FactSlot[date] = field(
        default_factory=lambda: FactSlot[date].missing("no proceeding start date is known")
    )
    undated_count: int = 0
    warnings: tuple[str, ...] = ()

    @property
    def has_records(self) -> bool:
        """Whether the section carried at least one proceeding."""
        return self.record_count > 0

    @property
    def proves_no_proceedings(self) -> bool:
        """Whether "no proceedings" is a confirmed fact rather than a gap."""
        return (
            self.record_count == 0
            and self.availability is Availability.PRESENT_EMPTY
            and self.confirms_absence
        )


def summarize_proceedings(
    proceedings: Sequence[ExecutionProceeding],
    *,
    availability: Availability = Availability.AVAILABLE,
    confirms_absence: bool = False,
    ledger: EvidenceLedger | None = None,
    ref_prefix: str = "calc",
    rule_version: str = DEFAULT_RULE_VERSION,
) -> ProceedingsSummary:
    """Summarise enforcement proceedings without inventing totals.

    Args:
        proceedings: The records of the section.
        availability: Availability of the section itself.
        confirms_absence: Whether an empty section was confirmed to mean "no
            proceedings".
        ledger: When supplied, each computed amount is registered as a derived
            reference over the records it was computed from.
        ref_prefix: Namespace for the generated derived reference ids.
        rule_version: Version recorded on the derived references.

    Returns:
        A summary where an unknown amount or an unknown status keeps the
        corresponding aggregate unknown.
    """
    resolved = availability
    if not proceedings and availability is Availability.AVAILABLE:
        resolved = Availability.PRESENT_EMPTY

    warnings: list[str] = []
    if not proceedings:
        summary = ProceedingsSummary(
            availability=resolved,
            confirms_absence=confirms_absence,
            warnings=(
                ()
                if confirms_absence and resolved is Availability.PRESENT_EMPTY
                else ("an empty proceedings section does not prove that none exist",)
            ),
        )
        return summary

    active_records = [item for item in proceedings if item.status is ProceedingStatus.ACTIVE]
    closed_records = [item for item in proceedings if item.status is ProceedingStatus.CLOSED]
    unknown_records = [item for item in proceedings if item.status is ProceedingStatus.UNKNOWN]

    active = _amount_coverage(active_records, label="active proceedings amount")
    closed = _amount_coverage(closed_records, label="closed proceedings amount")
    overall = _amount_coverage(list(proceedings), label="proceedings amount")

    if unknown_records:
        unusable = FactSlot[Decimal].missing(
            f"{len(unknown_records)} proceeding(s) have an unknown status, so the "
            "active and closed totals cannot be established",
            evidence_refs=_record_refs(proceedings),
        )
        active = AmountCoverage(
            total=unusable,
            known_subtotal=active.known_subtotal,
            record_count=active.record_count,
            known_count=active.known_count,
            unknown_count=active.unknown_count + len(unknown_records),
        )
        closed = AmountCoverage(
            total=unusable,
            known_subtotal=closed.known_subtotal,
            record_count=closed.record_count,
            known_count=closed.known_count,
            unknown_count=closed.unknown_count + len(unknown_records),
        )
        warnings.append(
            f"{len(unknown_records)} proceeding(s) do not state whether they are active"
        )
    if overall.unknown_count:
        warnings.append(
            f"{overall.unknown_count} of {overall.record_count} proceeding(s) carry no "
            "amount; the total is unknown and the known part is a lower bound"
        )

    dates = [item.started_at for item in proceedings if item.started_at.is_available]
    undated = len(proceedings) - len(dates)
    if dates:
        ordered = sorted(dates, key=lambda slot: slot.unwrap())
        earliest = ordered[0]
        latest = ordered[-1]
    else:
        earliest = FactSlot[date].missing("no proceeding start date is known")
        latest = earliest
    if undated:
        warnings.append(f"{undated} proceeding(s) carry no usable start date")

    if ledger is not None:
        active = _attach_coverage(active, ledger, f"{ref_prefix}:proceedings:active", rule_version)
        closed = _attach_coverage(closed, ledger, f"{ref_prefix}:proceedings:closed", rule_version)
        overall = _attach_coverage(
            overall, ledger, f"{ref_prefix}:proceedings:overall", rule_version
        )

    return ProceedingsSummary(
        availability=resolved,
        confirms_absence=confirms_absence,
        record_count=len(proceedings),
        active_count=len(active_records),
        closed_count=len(closed_records),
        status_unknown_count=len(unknown_records),
        active=active,
        closed=closed,
        overall=overall,
        earliest_start=earliest,
        latest_start=latest,
        undated_count=undated,
        warnings=tuple(warnings),
    )


def _attach_coverage(
    coverage: AmountCoverage, ledger: EvidenceLedger, scope: str, rule_version: str
) -> AmountCoverage:
    """Register the derivations of one amount coverage."""
    return AmountCoverage(
        total=attach_derivation(
            coverage.total, ledger=ledger, ref_id=f"{scope}:total", rule_version=rule_version
        ),
        known_subtotal=attach_derivation(
            coverage.known_subtotal,
            ledger=ledger,
            ref_id=f"{scope}:known_subtotal",
            rule_version=rule_version,
        ),
        record_count=coverage.record_count,
        known_count=coverage.known_count,
        unknown_count=coverage.unknown_count,
    )
