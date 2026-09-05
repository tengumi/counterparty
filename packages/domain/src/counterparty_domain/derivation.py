"""Binding a computed value back to the evidence it was computed from.

A calculation is only usable when a reader can expand it down to the source
fields it rests on. Every deterministic output produced here therefore keeps
the evidence ids of its inputs, and — when a ledger is supplied — is recorded
as a ``derived`` reference whose ``input_refs`` are exactly those inputs.

Nothing in this module scores, ranks or picks a winner: it only records how a
number was obtained.
"""

from collections.abc import Sequence
from dataclasses import replace

from counterparty_contracts import EvidenceKind, EvidenceRef

from .errors import UngroundedClaimError
from .evidence import EvidenceLedger
from .facts import FactSlot

__all__ = [
    "DEFAULT_RULE_VERSION",
    "attach_derivation",
    "derived_evidence",
]

DEFAULT_RULE_VERSION = "domain-calculations/0.1"
"""Version of the calculation rules implemented in this package.

It is carried by every derived reference, so a stored conclusion stays
attributable to the formula that produced it even after the rules change.
"""


def derived_evidence(
    ref_id: str,
    input_ref_ids: Sequence[str],
    *,
    rule_version: str = DEFAULT_RULE_VERSION,
    period: int | str | None = None,
) -> EvidenceRef:
    """Build a ``derived`` reference for one computed value.

    Args:
        ref_id: Stable id to give the derived reference.
        input_ref_ids: Evidence ids the value was computed from.
        rule_version: Version of the rule that produced the value.
        period: Fiscal year or period the value belongs to, when it has one.

    Raises:
        UngroundedClaimError: If no input reference was supplied, since a
            derivation without inputs cannot be expanded to a source.
    """
    inputs = tuple(dict.fromkeys(input_ref_ids))
    if not inputs:
        raise UngroundedClaimError(ref_id)
    return EvidenceRef(
        id=ref_id,
        kind=EvidenceKind.DERIVED,
        input_refs=list(inputs),
        rule_version=rule_version,
        period=period,
    )


def attach_derivation[T](
    slot: FactSlot[T],
    *,
    ledger: EvidenceLedger,
    ref_id: str,
    rule_version: str = DEFAULT_RULE_VERSION,
    period: int | str | None = None,
) -> FactSlot[T]:
    """Register the derivation of ``slot`` and return it grounded by it.

    The returned slot carries the derived reference alone; the inputs stay
    reachable through the ledger, so a caller can still expand the value down
    to primary sources.

    An unknown or absent slot without inputs is returned unchanged with a
    warning: there is no claim to ground, and inventing evidence for a
    non-value would hide the gap instead of showing it.

    Raises:
        UngroundedClaimError: If an available value carries no input evidence,
            or if the inputs do not resolve in the ledger.
    """
    if not slot.evidence_refs:
        if slot.is_available:
            raise UngroundedClaimError(ref_id)
        return slot.with_warning(f"{ref_id} carries no evidence: nothing was computed from it")
    ref = derived_evidence(ref_id, slot.evidence_refs, rule_version=rule_version, period=period)
    ledger.add(ref)
    ledger.require_resolvable(ref_id)
    return replace(slot, evidence_refs=(ref_id,))
