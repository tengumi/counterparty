"""Evidence ledger: registration and resolvability of evidence references.

Every factual output must resolve to an existing ``EvidenceRef``. The ledger
is the in-memory authority for that check: it owns the registered references,
walks ``derived`` chains down to primary sources, and reports precisely why a
reference cannot be used. It performs no I/O; loading references from storage
is the caller's responsibility.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from counterparty_contracts import EvidenceKind, EvidenceRef

from .errors import (
    DuplicateEvidenceRefError,
    UngroundedClaimError,
    UnknownEvidenceRefError,
    UnresolvableEvidenceRefError,
)

__all__ = [
    "EvidenceLedger",
    "EvidenceProblem",
    "EvidenceResolution",
    "ReferenceProblem",
    "require_grounded",
]


class EvidenceProblem(StrEnum):
    """Why an evidence reference cannot be resolved."""

    UNKNOWN_REF = "unknown_ref"
    UNAVAILABLE_SOURCE = "unavailable_source"
    BROKEN_DERIVATION = "broken_derivation"
    CYCLIC_DERIVATION = "cyclic_derivation"
    NO_EVIDENCE = "no_evidence"


@dataclass(frozen=True, slots=True)
class ReferenceProblem:
    """One unresolvable reference and the derivation path that reached it."""

    ref_id: str
    problem: EvidenceProblem
    path: tuple[str, ...] = ()
    detail: str | None = None

    def describe(self) -> str:
        """Render a short, log-safe description of the problem."""
        trail = " -> ".join((*self.path, self.ref_id))
        suffix = f" ({self.detail})" if self.detail else ""
        return f"{self.problem.value}: {trail}{suffix}"


@dataclass(frozen=True, slots=True)
class EvidenceResolution:
    """Outcome of resolving one or more evidence references."""

    requested: tuple[str, ...]
    resolved: tuple[str, ...]
    primary_sources: tuple[str, ...]
    problems: tuple[ReferenceProblem, ...] = ()

    @property
    def is_resolvable(self) -> bool:
        """Whether every requested reference resolves to primary sources."""
        return not self.problems and bool(self.resolved)

    def problem_descriptions(self) -> tuple[str, ...]:
        """Return one description per problem, in discovery order."""
        return tuple(problem.describe() for problem in self.problems)


class EvidenceLedger:
    """A mutable set of evidence references keyed by their stable id.

    The ledger keeps derivation edges, so a ``derived`` reference is resolvable
    only when every input it was computed from is itself resolvable.
    """

    __slots__ = ("_refs", "_unavailable")

    def __init__(self, refs: Iterable[EvidenceRef] = ()) -> None:
        """Build a ledger, registering the given references."""
        self._refs: dict[str, EvidenceRef] = {}
        self._unavailable: dict[str, str] = {}
        self.extend(refs)

    def __contains__(self, ref_id: object) -> bool:
        """Whether a reference id is registered, available or not."""
        return isinstance(ref_id, str) and ref_id in self._refs

    def __len__(self) -> int:
        """Number of registered references."""
        return len(self._refs)

    def __iter__(self) -> Iterator[EvidenceRef]:
        """Iterate over registered references in insertion order."""
        return iter(self._refs.values())

    @property
    def refs(self) -> Mapping[str, EvidenceRef]:
        """Read-only view of the registered references."""
        return self._refs

    def add(self, ref: EvidenceRef) -> EvidenceRef:
        """Register a reference.

        Re-registering an identical reference is a no-op, which keeps import
        and replay idempotent.

        Raises:
            DuplicateEvidenceRefError: If the id is taken by a different
                reference.
        """
        existing = self._refs.get(ref.id)
        if existing is not None:
            if existing != ref:
                raise DuplicateEvidenceRefError(ref.id)
            return existing
        self._refs[ref.id] = ref
        return ref

    def extend(self, refs: Iterable[EvidenceRef]) -> None:
        """Register several references."""
        for ref in refs:
            self.add(ref)

    def get(self, ref_id: str) -> EvidenceRef | None:
        """Return a registered reference, or ``None``."""
        return self._refs.get(ref_id)

    def require(self, ref_id: str) -> EvidenceRef:
        """Return a registered reference or raise.

        Raises:
            UnknownEvidenceRefError: If the id is not registered.
        """
        ref = self._refs.get(ref_id)
        if ref is None:
            raise UnknownEvidenceRefError(ref_id)
        return ref

    def mark_unavailable(self, ref_id: str, reason: str) -> None:
        """Flag a registered reference whose source no longer exists.

        The reference stays in history — a deleted document does not erase the
        fact that a conclusion was drawn from it — but it stops being usable
        as grounding, and every derivation above it becomes unresolvable.

        Raises:
            UnknownEvidenceRefError: If the id is not registered.
        """
        self.require(ref_id)
        self._unavailable[ref_id] = reason

    def mark_available(self, ref_id: str) -> None:
        """Clear a previously recorded unavailability."""
        self.require(ref_id)
        self._unavailable.pop(ref_id, None)

    def is_unavailable(self, ref_id: str) -> bool:
        """Whether the reference is registered but flagged unavailable."""
        return ref_id in self._unavailable

    def unavailable_reason(self, ref_id: str) -> str | None:
        """Return why a reference was flagged unavailable, if it was."""
        return self._unavailable.get(ref_id)

    def is_resolvable(self, ref_id: str) -> bool:
        """Whether one reference resolves to available primary sources."""
        return self.resolve(ref_id).is_resolvable

    def resolve(self, ref_id: str) -> EvidenceResolution:
        """Resolve one reference, walking derivation inputs transitively."""
        return self.resolve_all((ref_id,))

    def resolve_all(self, ref_ids: Sequence[str]) -> EvidenceResolution:
        """Resolve several references and collect every problem found.

        Returns:
            An ``EvidenceResolution`` listing the references that resolved and
            the primary, non-derived sources they ultimately rest on.
        """
        resolved: list[str] = []
        primary: list[str] = []
        problems: list[ReferenceProblem] = []
        for ref_id in ref_ids:
            before = len(problems)
            self._walk(ref_id, path=(), seen=set(), primary=primary, problems=problems)
            if len(problems) == before and ref_id not in resolved:
                resolved.append(ref_id)
        if not ref_ids:
            problems.append(
                ReferenceProblem(
                    ref_id="", problem=EvidenceProblem.NO_EVIDENCE, detail="no references supplied"
                )
            )
        return EvidenceResolution(
            requested=tuple(ref_ids),
            resolved=tuple(resolved),
            primary_sources=tuple(dict.fromkeys(primary)),
            problems=tuple(problems),
        )

    def _walk(
        self,
        ref_id: str,
        *,
        path: tuple[str, ...],
        seen: set[str],
        primary: list[str],
        problems: list[ReferenceProblem],
    ) -> None:
        """Depth-first traversal of one derivation chain."""
        if ref_id in path:
            problems.append(
                ReferenceProblem(
                    ref_id=ref_id, problem=EvidenceProblem.CYCLIC_DERIVATION, path=path
                )
            )
            return
        ref = self._refs.get(ref_id)
        if ref is None:
            problem = EvidenceProblem.BROKEN_DERIVATION if path else EvidenceProblem.UNKNOWN_REF
            problems.append(ReferenceProblem(ref_id=ref_id, problem=problem, path=path))
            return
        if ref_id in self._unavailable:
            problems.append(
                ReferenceProblem(
                    ref_id=ref_id,
                    problem=EvidenceProblem.UNAVAILABLE_SOURCE,
                    path=path,
                    detail=self._unavailable[ref_id],
                )
            )
            return
        if ref_id in seen:
            return
        seen.add(ref_id)
        if ref.kind is not EvidenceKind.DERIVED:
            primary.append(ref_id)
            return
        for input_id in ref.input_refs:
            self._walk(
                input_id, path=(*path, ref_id), seen=seen, primary=primary, problems=problems
            )

    def dangling_ref_ids(self) -> tuple[str, ...]:
        """Return ids referenced by derivations but never registered."""
        missing = [
            input_id
            for ref in self._refs.values()
            for input_id in ref.input_refs
            if input_id not in self._refs
        ]
        return tuple(dict.fromkeys(missing))

    def unresolvable_ref_ids(self) -> tuple[str, ...]:
        """Return every registered reference that cannot be resolved."""
        return tuple(ref_id for ref_id in self._refs if not self.is_resolvable(ref_id))

    def require_resolvable(self, ref_id: str) -> EvidenceRef:
        """Return a reference only if it fully resolves.

        Raises:
            UnknownEvidenceRefError: If the id is not registered.
            UnresolvableEvidenceRefError: If resolution fails.
        """
        ref = self.require(ref_id)
        resolution = self.resolve(ref_id)
        if not resolution.is_resolvable:
            raise UnresolvableEvidenceRefError(ref_id, problems=resolution.problem_descriptions())
        return ref


def require_grounded(
    claim: str, ref_ids: Sequence[str], ledger: EvidenceLedger
) -> EvidenceResolution:
    """Assert that a factual claim rests on resolvable evidence.

    Args:
        claim: Short identifier of the statement being grounded.
        ref_ids: Evidence ids attached to the claim.
        ledger: Ledger holding the known references.

    Returns:
        The successful resolution, for callers that need the primary sources.

    Raises:
        UngroundedClaimError: If no reference was supplied or any of them fails
            to resolve.
    """
    resolution = ledger.resolve_all(tuple(ref_ids))
    if not resolution.is_resolvable:
        raise UngroundedClaimError(claim, problems=resolution.problem_descriptions())
    return resolution
