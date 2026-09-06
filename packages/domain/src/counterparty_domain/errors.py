"""Domain-level errors raised by pure computations."""

from collections.abc import Sequence

__all__ = [
    "DomainError",
    "DuplicateEvidenceRefError",
    "EvidenceError",
    "IdentifierError",
    "UnavailableValueError",
    "UngroundedClaimError",
    "UnknownEvidenceRefError",
    "UnresolvableEvidenceRefError",
]


class DomainError(Exception):
    """Base class for every error raised by the domain layer."""


class IdentifierError(DomainError):
    """A registry identifier failed format or checksum validation."""

    def __init__(self, message: str, *, raw: str | None, problems: Sequence[str]) -> None:
        """Store the rejected input and the machine-readable problem codes."""
        super().__init__(message)
        self.raw = raw
        self.problems: tuple[str, ...] = tuple(problems)


class UnavailableValueError(DomainError):
    """A value was required but is missing, empty, invalid or restricted.

    Raised by ``FactSlot.unwrap``. Absence of a value never means absence of
    risk, so callers must handle this state instead of substituting zero.
    """

    def __init__(self, message: str, *, availability: str, reason: str | None = None) -> None:
        """Store which non-available state was encountered."""
        super().__init__(message)
        self.availability = availability
        self.reason = reason


class EvidenceError(DomainError):
    """Base class for evidence ledger failures."""


class DuplicateEvidenceRefError(EvidenceError):
    """Two different references were registered under the same evidence id."""

    def __init__(self, ref_id: str) -> None:
        """Store the conflicting evidence id."""
        super().__init__(f"evidence id {ref_id!r} is already registered with different content")
        self.ref_id = ref_id


class UnknownEvidenceRefError(EvidenceError):
    """A referenced evidence id is not present in the ledger."""

    def __init__(self, ref_id: str) -> None:
        """Store the unknown evidence id."""
        super().__init__(f"evidence id {ref_id!r} is not registered in the ledger")
        self.ref_id = ref_id


class UnresolvableEvidenceRefError(EvidenceError):
    """A registered reference cannot be resolved to a usable source."""

    def __init__(self, ref_id: str, *, problems: Sequence[str]) -> None:
        """Store the reference id and why resolution failed."""
        super().__init__(f"evidence id {ref_id!r} is not resolvable: {', '.join(problems)}")
        self.ref_id = ref_id
        self.problems: tuple[str, ...] = tuple(problems)


class UngroundedClaimError(EvidenceError):
    """A factual statement carries no resolvable evidence reference."""

    def __init__(self, claim: str, *, problems: Sequence[str] = ()) -> None:
        """Store the rejected claim and, when known, the failing references."""
        detail = f": {', '.join(problems)}" if problems else ""
        super().__init__(f"claim {claim!r} has no resolvable evidence{detail}")
        self.claim = claim
        self.problems: tuple[str, ...] = tuple(problems)
