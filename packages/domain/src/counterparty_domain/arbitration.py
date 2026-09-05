"""Arbitration aggregates, kept as aggregates.

The source never carries individual cases: it carries counts and amounts per
role and status (``arbitrationByStatus``) and per role and year
(``arbitrationCases``), plus its own reported grand total
(``commonCount`` / ``commonAmount``). Three rules follow, and this module
enforces them:

* an aggregate is never expanded into an invented case;
* the reported grand total is never added to the breakdowns, and the two
  breakdowns are never added to each other — they are different slices of an
  unknown set of cases;
* an empty status object stays ``present_empty`` and does not become a
  confirmed ``count = 0``.

Comparing the reported total against a breakdown is allowed and useful, but
it is published as a comparison, never as a corrected total.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from counterparty_contracts import Availability

from .derivation import DEFAULT_RULE_VERSION, attach_derivation
from .evidence import EvidenceLedger
from .facts import FactSlot
from .values import subtract_decimals, sum_decimals

__all__ = [
    "AggregationKind",
    "ArbitrationAggregate",
    "ArbitrationSummary",
    "CaseStatus",
    "PartyRole",
    "ReportedTotals",
    "RoleTotals",
    "summarize_arbitration",
]


class PartyRole(StrEnum):
    """Side the company took in the aggregated cases.

    The source misspells the defendant branch as ``defandantArbitration``;
    the misspelling stays in the parser and never reaches this layer.
    """

    PLAINTIFF = "plaintiff"
    DEFENDANT = "defendant"


class CaseStatus(StrEnum):
    """Status slice of the status-based aggregate."""

    FINISHED = "finished"
    APPEALED = "appealed"
    PENDING = "pending"


class AggregationKind(StrEnum):
    """Which breakdown an aggregate belongs to."""

    STATUS = "status"
    YEAR = "year"


def _absent_count() -> FactSlot[int]:
    """Default slot for an aggregate whose count was not supplied."""
    return FactSlot[int].missing("aggregate count was not supplied to the domain layer")


def _absent_amount() -> FactSlot[Decimal]:
    """Default slot for an aggregate whose amount was not supplied."""
    return FactSlot[Decimal].missing("aggregate amount was not supplied to the domain layer")


@dataclass(frozen=True, slots=True)
class ArbitrationAggregate:
    """One count/amount pair for a role, and a status or a year.

    An aggregate with an empty source object keeps ``missing`` or
    ``present_empty`` counts: a status branch that carried ``{}`` is not a
    confirmed absence of cases.
    """

    aggregation: AggregationKind
    role: PartyRole
    status: CaseStatus | None = None
    year: int | None = None
    count: FactSlot[int] = field(default_factory=_absent_count)
    amount: FactSlot[Decimal] = field(default_factory=_absent_amount)
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Keep the slice consistent with the breakdown it belongs to."""
        if self.aggregation is AggregationKind.STATUS and self.status is None:
            raise ValueError("a status aggregate requires a case status")
        if self.aggregation is AggregationKind.YEAR and self.year is None:
            raise ValueError("a year aggregate requires a year")


@dataclass(frozen=True, slots=True)
class ReportedTotals:
    """The grand total the source stated itself.

    It is stored as provided and is never recomputed from, or added to, the
    breakdowns.
    """

    count: FactSlot[int] = field(default_factory=_absent_count)
    amount: FactSlot[Decimal] = field(default_factory=_absent_amount)


@dataclass(frozen=True, slots=True)
class RoleTotals:
    """Sums within one breakdown and one role.

    Summing inside a single breakdown is legitimate: the slices of one
    breakdown are disjoint. Summing across breakdowns is not, and no field
    here does it.
    """

    aggregation: AggregationKind
    role: PartyRole
    count: FactSlot[int]
    amount: FactSlot[Decimal]
    slice_count: int


@dataclass(frozen=True, slots=True)
class ArbitrationSummary:
    """Role totals per breakdown, plus the reported grand total.

    Attributes:
        reconciliation: Reported total amount minus the summed status
            breakdown, when both are known. It is a discrepancy report, not a
            replacement total.
    """

    availability: Availability
    confirms_absence: bool = False
    reported: ReportedTotals = field(default_factory=ReportedTotals)
    by_status: tuple[RoleTotals, ...] = ()
    by_year: tuple[RoleTotals, ...] = ()
    reconciliation: FactSlot[Decimal] = field(
        default_factory=lambda: FactSlot[Decimal].missing(
            "reported and aggregated amounts cannot be compared"
        )
    )
    warnings: tuple[str, ...] = ()

    def totals_for(self, aggregation: AggregationKind, role: PartyRole) -> RoleTotals | None:
        """Return the totals of one breakdown and role, if they exist."""
        source = self.by_status if aggregation is AggregationKind.STATUS else self.by_year
        for totals in source:
            if totals.role is role:
                return totals
        return None


def _sum_counts(slots: Sequence[FactSlot[int]], *, label: str) -> FactSlot[int]:
    """Sum integer counts, refusing to treat an unknown slice as zero."""
    total = 0
    collected: list[str] = []
    for slot in slots:
        if not slot.is_available:
            return FactSlot[int].missing(
                f"{label} is unknown: a slice is {slot.availability.value}",
                evidence_refs=collected,
            )
        total += slot.unwrap()
        collected.extend(ref for ref in slot.evidence_refs if ref not in collected)
    if not slots:
        return FactSlot[int].present_empty(f"{label} had no slices to sum", evidence_refs=collected)
    return FactSlot[int].available(total, evidence_refs=collected)


def _role_totals(
    aggregates: Sequence[ArbitrationAggregate],
    aggregation: AggregationKind,
    role: PartyRole,
    *,
    ledger: EvidenceLedger | None,
    ref_prefix: str,
    rule_version: str,
) -> RoleTotals:
    """Sum the slices of one breakdown for one role."""
    slices = [item for item in aggregates if item.aggregation is aggregation and item.role is role]
    seed: list[str] = []
    for item in slices:
        seed.extend(ref for ref in item.evidence_refs if ref not in seed)
    label = f"{role.value} {aggregation.value} arbitration"
    count = _sum_counts(
        [item.count.with_evidence(*item.evidence_refs) for item in slices],
        label=f"{label} count",
    )
    amount = sum_decimals(
        [item.amount for item in slices], label=f"{label} amount", evidence_refs=seed
    )
    if ledger is not None:
        scope = f"{ref_prefix}:arbitration:{aggregation.value}:{role.value}"
        amount = attach_derivation(
            amount, ledger=ledger, ref_id=f"{scope}:amount", rule_version=rule_version
        )
    return RoleTotals(
        aggregation=aggregation,
        role=role,
        count=count,
        amount=amount,
        slice_count=len(slices),
    )


def summarize_arbitration(
    aggregates: Sequence[ArbitrationAggregate],
    *,
    reported: ReportedTotals | None = None,
    availability: Availability = Availability.AVAILABLE,
    confirms_absence: bool = False,
    ledger: EvidenceLedger | None = None,
    ref_prefix: str = "calc",
    rule_version: str = DEFAULT_RULE_VERSION,
) -> ArbitrationSummary:
    """Summarise arbitration aggregates without merging incompatible slices.

    Args:
        aggregates: Status- and year-based aggregates, in any order.
        reported: The grand total the source stated itself.
        availability: Availability of the arbitration section.
        confirms_absence: Whether an empty section was confirmed to mean "no
            cases".
        ledger: When supplied, computed sums are registered as derived
            references over their slices.
        ref_prefix: Namespace for the generated derived reference ids.
        rule_version: Version recorded on the derived references.

    Returns:
        Totals per breakdown and role, the reported total as provided, and
        their difference where both are known.
    """
    totals = reported if reported is not None else ReportedTotals()
    resolved = availability
    if not aggregates and availability is Availability.AVAILABLE:
        resolved = Availability.PRESENT_EMPTY

    by_status = tuple(
        _role_totals(
            aggregates,
            AggregationKind.STATUS,
            role,
            ledger=ledger,
            ref_prefix=ref_prefix,
            rule_version=rule_version,
        )
        for role in PartyRole
    )
    by_year = tuple(
        _role_totals(
            aggregates,
            AggregationKind.YEAR,
            role,
            ledger=ledger,
            ref_prefix=ref_prefix,
            rule_version=rule_version,
        )
        for role in PartyRole
    )

    status_amount = sum_decimals(
        [totals.amount for totals in by_status], label="status breakdown amount"
    )
    reconciliation = subtract_decimals(
        totals.amount, status_amount, label="reported total against status breakdown"
    )
    if ledger is not None:
        reconciliation = attach_derivation(
            reconciliation,
            ledger=ledger,
            ref_id=f"{ref_prefix}:arbitration:reconciliation",
            rule_version=rule_version,
        )

    warnings: list[str] = []
    if not aggregates:
        warnings.append(
            "an empty arbitration breakdown does not prove that no cases exist"
            if not confirms_absence
            else "the arbitration breakdown is confirmed empty"
        )
    if reconciliation.is_available and reconciliation.unwrap() != 0:
        warnings.append(
            "the reported arbitration total differs from the status breakdown; "
            "both are kept as provided and are not added together"
        )
    return ArbitrationSummary(
        availability=resolved,
        confirms_absence=confirms_absence,
        reported=totals,
        by_status=by_status,
        by_year=by_year,
        reconciliation=reconciliation,
        warnings=tuple(warnings),
    )
