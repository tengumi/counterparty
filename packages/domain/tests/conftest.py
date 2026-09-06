"""Shared fixtures for the calculation tests."""

from decimal import Decimal
from uuid import UUID

import pytest
from counterparty_contracts import EvidenceKind, EvidenceRef, ReportId

from counterparty_domain import EvidenceLedger, FactSlot

REPORT_ID = ReportId(UUID("11111111-1111-1111-1111-111111111111"))


def report_field(ref_id: str, source_path: str) -> EvidenceRef:
    """Build a primary reference to one field of the provided report."""
    return EvidenceRef(
        id=ref_id,
        kind=EvidenceKind.REPORT_FIELD,
        report_id=REPORT_ID,
        source_path=source_path,
    )


def grounded(
    amount: str, ref_id: str, source_path: str, ledger: EvidenceLedger
) -> FactSlot[Decimal]:
    """Register a primary reference and return a value grounded in it."""
    ledger.add(report_field(ref_id, source_path))
    return FactSlot[Decimal].available(Decimal(amount), evidence_refs=(ref_id,))


@pytest.fixture
def ledger() -> EvidenceLedger:
    """An empty ledger for grounding derived values."""
    return EvidenceLedger()
