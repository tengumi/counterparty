"""Every computed value is expandable back to its sources."""

from decimal import Decimal

import pytest
from conftest import grounded, report_field

from counterparty_domain import (
    DEFAULT_RULE_VERSION,
    EvidenceLedger,
    FactSlot,
    UngroundedClaimError,
    attach_derivation,
    derived_evidence,
    sum_decimals,
)


def test_derived_reference_records_inputs_and_rule_version() -> None:
    """A derivation states what it was computed from and by which rule."""
    ref = derived_evidence("d:total", ("a", "b", "a"), period=2025)
    assert ref.input_refs == ["a", "b"]
    assert ref.rule_version == DEFAULT_RULE_VERSION
    assert ref.period == 2025


def test_derivation_without_inputs_is_refused() -> None:
    """A number with no inputs cannot be expanded and is not accepted."""
    with pytest.raises(UngroundedClaimError):
        derived_evidence("d:total", ())


def test_attached_value_resolves_to_its_primary_sources(ledger: EvidenceLedger) -> None:
    """The ledger walks the derivation down to the report fields."""
    total = sum_decimals(
        (
            grounded("10", "e:a", "/executionProceedings/0/amount", ledger),
            grounded("5", "e:b", "/executionProceedings/1/amount", ledger),
        )
    )
    attached = attach_derivation(total, ledger=ledger, ref_id="d:total")
    assert attached.unwrap() == Decimal("15")
    assert attached.evidence_refs == ("d:total",)
    resolution = ledger.resolve("d:total")
    assert resolution.primary_sources == ("e:a", "e:b")


def test_available_value_without_evidence_is_rejected(ledger: EvidenceLedger) -> None:
    """An ungrounded factual number never receives invented evidence."""
    with pytest.raises(UngroundedClaimError):
        attach_derivation(
            FactSlot[Decimal].available(Decimal("1")), ledger=ledger, ref_id="d:total"
        )


def test_unknown_value_without_evidence_is_returned_with_a_warning(
    ledger: EvidenceLedger,
) -> None:
    """There is no claim to ground when nothing was computed."""
    attached = attach_derivation(
        FactSlot[Decimal].missing("nothing to sum"), ledger=ledger, ref_id="d:total"
    )
    assert not attached.is_available
    assert attached.warnings
    assert "d:total" not in ledger


def test_removed_source_makes_the_computed_value_unresolvable(ledger: EvidenceLedger) -> None:
    """A deleted document invalidates the conclusions drawn from it."""
    total = sum_decimals((grounded("10", "e:a", "/executionProceedings/0/amount", ledger),))
    attach_derivation(total, ledger=ledger, ref_id="d:total")
    ledger.mark_unavailable("e:a", "document deleted")
    assert not ledger.is_resolvable("d:total")


def test_derivation_can_be_reattached_idempotently(ledger: EvidenceLedger) -> None:
    """Recomputing the same value does not conflict with its own record."""
    ledger.add(report_field("e:a", "/executionProceedings/0/amount"))
    slot = FactSlot[Decimal].available(Decimal("10"), evidence_refs=("e:a",))
    first = attach_derivation(slot, ledger=ledger, ref_id="d:total")
    second = attach_derivation(slot, ledger=ledger, ref_id="d:total")
    assert first == second
    assert len(ledger) == 2
