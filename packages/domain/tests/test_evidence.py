"""Evidence ledger registration, resolution and grounding."""

from uuid import UUID

import pytest
from counterparty_contracts import EvidenceKind, EvidenceRef

from counterparty_domain import (
    DuplicateEvidenceRefError,
    EvidenceLedger,
    EvidenceProblem,
    UngroundedClaimError,
    UnknownEvidenceRefError,
    UnresolvableEvidenceRefError,
    require_grounded,
)

REPORT_ID = UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
FRAGMENT_ID = UUID("33333333-3333-4333-8333-333333333333")


def report_field(ref_id: str, source_path: str = "/finReports/0/common/proceeds") -> EvidenceRef:
    """Build a primary report-field reference."""
    return EvidenceRef(
        id=ref_id,
        kind=EvidenceKind.REPORT_FIELD,
        report_id=REPORT_ID,  # type: ignore[arg-type]
        source_path=source_path,
    )


def document_fragment(ref_id: str) -> EvidenceRef:
    """Build a primary document-fragment reference."""
    return EvidenceRef(
        id=ref_id,
        kind=EvidenceKind.DOCUMENT_FRAGMENT,
        document_id=DOCUMENT_ID,  # type: ignore[arg-type]
        fragment_id=FRAGMENT_ID,  # type: ignore[arg-type]
    )


def derived(ref_id: str, *inputs: str, rule_version: str = "rules/1") -> EvidenceRef:
    """Build a derived reference over the given input references."""
    return EvidenceRef(
        id=ref_id,
        kind=EvidenceKind.DERIVED,
        input_refs=list(inputs),
        rule_version=rule_version,
    )


def test_registration_is_idempotent_but_rejects_conflicts() -> None:
    """Replaying the same reference is safe; reusing an id is not."""
    ledger = EvidenceLedger([report_field("ev-1")])
    ledger.add(report_field("ev-1"))
    assert len(ledger) == 1
    with pytest.raises(DuplicateEvidenceRefError):
        ledger.add(report_field("ev-1", source_path="/status/statusRaw"))


def test_primary_reference_resolves_to_itself() -> None:
    """A report field is its own primary source."""
    ledger = EvidenceLedger([report_field("ev-1")])
    resolution = ledger.resolve("ev-1")
    assert resolution.is_resolvable
    assert resolution.primary_sources == ("ev-1",)


def test_unknown_reference_is_not_resolvable() -> None:
    """An id absent from the ledger can never ground a statement."""
    ledger = EvidenceLedger([report_field("ev-1")])
    resolution = ledger.resolve("ev-missing")
    assert not resolution.is_resolvable
    assert resolution.problems[0].problem is EvidenceProblem.UNKNOWN_REF
    assert "ev-missing" in resolution.problem_descriptions()[0]
    with pytest.raises(UnknownEvidenceRefError):
        ledger.require("ev-missing")


def test_derived_chain_resolves_to_primary_sources() -> None:
    """A derivation is resolvable through every one of its inputs."""
    ledger = EvidenceLedger(
        [
            report_field("ev-1"),
            document_fragment("ev-2"),
            derived("ev-3", "ev-1", "ev-2"),
            derived("ev-4", "ev-3"),
        ]
    )
    resolution = ledger.resolve("ev-4")
    assert resolution.is_resolvable
    assert set(resolution.primary_sources) == {"ev-1", "ev-2"}


def test_derived_chain_with_dangling_input_is_broken() -> None:
    """A derivation over a missing input is unusable, not partially usable."""
    ledger = EvidenceLedger([report_field("ev-1"), derived("ev-2", "ev-1", "ev-gone")])
    resolution = ledger.resolve("ev-2")
    assert not resolution.is_resolvable
    assert resolution.problems[0].problem is EvidenceProblem.BROKEN_DERIVATION
    assert resolution.problems[0].path == ("ev-2",)
    assert ledger.dangling_ref_ids() == ("ev-gone",)
    assert ledger.unresolvable_ref_ids() == ("ev-2",)
    with pytest.raises(UnresolvableEvidenceRefError):
        ledger.require_resolvable("ev-2")


def test_cyclic_derivation_is_detected() -> None:
    """A derivation cycle terminates with an explicit problem."""
    ledger = EvidenceLedger([derived("ev-a", "ev-b"), derived("ev-b", "ev-a")])
    resolution = ledger.resolve("ev-a")
    assert not resolution.is_resolvable
    assert resolution.problems[0].problem is EvidenceProblem.CYCLIC_DERIVATION


def test_unavailable_source_invalidates_dependent_derivations() -> None:
    """A removed document keeps its reference but stops grounding conclusions."""
    ledger = EvidenceLedger([document_fragment("ev-1"), derived("ev-2", "ev-1")])
    ledger.mark_unavailable("ev-1", "document deleted from project")
    assert ledger.is_unavailable("ev-1")
    assert ledger.unavailable_reason("ev-1") == "document deleted from project"
    assert "ev-1" in ledger

    resolution = ledger.resolve("ev-2")
    assert not resolution.is_resolvable
    assert resolution.problems[0].problem is EvidenceProblem.UNAVAILABLE_SOURCE
    assert "document deleted" in resolution.problem_descriptions()[0]

    ledger.mark_available("ev-1")
    assert ledger.resolve("ev-2").is_resolvable
    with pytest.raises(UnknownEvidenceRefError):
        ledger.mark_unavailable("ev-nope", "typo")


def test_resolve_all_reports_every_problem() -> None:
    """Resolution collects all failures instead of stopping at the first."""
    ledger = EvidenceLedger([report_field("ev-1")])
    resolution = ledger.resolve_all(("ev-1", "ev-x", "ev-y"))
    assert resolution.resolved == ("ev-1",)
    assert len(resolution.problems) == 2


def test_diamond_derivation_visits_shared_input_once() -> None:
    """A shared input is reported once, not duplicated per path."""
    ledger = EvidenceLedger(
        [
            report_field("ev-1"),
            derived("ev-2", "ev-1"),
            derived("ev-3", "ev-1"),
            derived("ev-4", "ev-2", "ev-3"),
        ]
    )
    assert ledger.resolve("ev-4").primary_sources == ("ev-1",)


def test_require_grounded_rejects_claims_without_evidence() -> None:
    """Every factual output must name at least one resolvable reference."""
    ledger = EvidenceLedger([report_field("ev-1")])
    assert require_grounded("proceeds 2025", ["ev-1"], ledger).primary_sources == ("ev-1",)

    with pytest.raises(UngroundedClaimError) as empty:
        require_grounded("proceeds 2025", [], ledger)
    assert EvidenceProblem.NO_EVIDENCE.value in empty.value.problems[0]

    with pytest.raises(UngroundedClaimError) as unknown:
        require_grounded("proceeds 2025", ["ev-1", "ev-ghost"], ledger)
    assert unknown.value.claim == "proceeds 2025"
