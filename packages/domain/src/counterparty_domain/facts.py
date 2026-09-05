"""Explicit semantics for missing, zero, empty and unavailable values.

The product rule is that absence of data never proves absence of risk. A
``FactSlot`` therefore keeps the reason a value is not there instead of
collapsing every non-value into ``None`` or ``0``:

* ``available`` — a trustworthy value, which may legitimately be ``0``;
* ``missing`` — the source never carried the field;
* ``present_empty`` — the source carried an empty container, which only proves
  absence when the semantics were confirmed;
* ``invalid`` — the source carried something that failed parsing;
* ``restricted`` — the value exists but the caller may not see it.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace

from counterparty_contracts import Availability

from .errors import UnavailableValueError

__all__ = ["UNKNOWN_AVAILABILITY", "Availability", "FactSlot", "first_available"]

UNKNOWN_AVAILABILITY: frozenset[Availability] = frozenset(
    {Availability.MISSING, Availability.INVALID, Availability.RESTRICTED}
)
"""States in which the true value is unknown, so no conclusion may be drawn."""


@dataclass(frozen=True, slots=True)
class FactSlot[T]:
    """One value together with why it is, or is not, available.

    Attributes:
        value: The parsed value, present only when ``availability`` is
            ``available``.
        availability: How the non-value, if any, must be interpreted.
        reason: Human-readable explanation for a non-available state.
        confirms_absence: Only meaningful for ``present_empty``; ``True`` when
            the emptiness of the source container was confirmed to mean "no
            records", as opposed to an unexplained empty object.
        warnings: Non-fatal notes collected while parsing.
        evidence_refs: Evidence ids that ground this value.
    """

    value: T | None
    availability: Availability
    reason: str | None = None
    confirms_absence: bool = False
    warnings: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Keep ``value`` and ``availability`` mutually consistent."""
        if self.availability is Availability.AVAILABLE:
            if self.value is None:
                raise ValueError("available fact must carry a value")
        elif self.value is not None:
            raise ValueError(f"{self.availability.value} fact must not carry a value")
        if self.confirms_absence and self.availability is not Availability.PRESENT_EMPTY:
            raise ValueError("confirms_absence applies only to present_empty facts")

    @classmethod
    def available(
        cls,
        value: T,
        *,
        warnings: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
    ) -> "FactSlot[T]":
        """Build a slot holding a trustworthy value, including a real zero."""
        return cls(
            value=value,
            availability=Availability.AVAILABLE,
            warnings=tuple(warnings),
            evidence_refs=tuple(evidence_refs),
        )

    @classmethod
    def missing(
        cls,
        reason: str | None = None,
        *,
        warnings: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
    ) -> "FactSlot[T]":
        """Build a slot for a field the source never carried."""
        return cls(
            value=None,
            availability=Availability.MISSING,
            reason=reason,
            warnings=tuple(warnings),
            evidence_refs=tuple(evidence_refs),
        )

    @classmethod
    def present_empty(
        cls,
        reason: str | None = None,
        *,
        confirms_absence: bool = False,
        warnings: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
    ) -> "FactSlot[T]":
        """Build a slot for an empty container carried by the source."""
        return cls(
            value=None,
            availability=Availability.PRESENT_EMPTY,
            reason=reason,
            confirms_absence=confirms_absence,
            warnings=tuple(warnings),
            evidence_refs=tuple(evidence_refs),
        )

    @classmethod
    def invalid(
        cls,
        reason: str,
        *,
        warnings: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
    ) -> "FactSlot[T]":
        """Build a slot for a malformed source value, never for a zero."""
        return cls(
            value=None,
            availability=Availability.INVALID,
            reason=reason,
            warnings=tuple(warnings),
            evidence_refs=tuple(evidence_refs),
        )

    @classmethod
    def restricted(
        cls,
        reason: str | None = None,
        *,
        warnings: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
    ) -> "FactSlot[T]":
        """Build a slot for a value the caller is not allowed to see."""
        return cls(
            value=None,
            availability=Availability.RESTRICTED,
            reason=reason,
            warnings=tuple(warnings),
            evidence_refs=tuple(evidence_refs),
        )

    @property
    def is_available(self) -> bool:
        """Whether a trustworthy value is present."""
        return self.availability is Availability.AVAILABLE

    @property
    def is_unknown(self) -> bool:
        """Whether the real value is unknown and no conclusion may be drawn."""
        return self.availability in UNKNOWN_AVAILABILITY

    @property
    def is_evidence_of_absence(self) -> bool:
        """Whether emptiness was confirmed to mean "no records"."""
        return self.availability is Availability.PRESENT_EMPTY and self.confirms_absence

    def unwrap(self) -> T:
        """Return the value or fail loudly.

        Raises:
            UnavailableValueError: If the slot holds no trustworthy value.
        """
        if self.value is None:
            raise UnavailableValueError(
                f"value is {self.availability.value}",
                availability=self.availability.value,
                reason=self.reason,
            )
        return self.value

    def value_or(self, default: T) -> T:
        """Return the value, or an explicitly chosen default.

        The default is a caller decision, never an implicit zero.
        """
        return default if self.value is None else self.value

    def map[R](self, transform: Callable[[T], R]) -> "FactSlot[R]":
        """Apply ``transform`` to an available value, preserving metadata."""
        if self.value is None:
            return FactSlot[R](
                value=None,
                availability=self.availability,
                reason=self.reason,
                confirms_absence=self.confirms_absence,
                warnings=self.warnings,
                evidence_refs=self.evidence_refs,
            )
        return FactSlot[R](
            value=transform(self.value),
            availability=self.availability,
            warnings=self.warnings,
            evidence_refs=self.evidence_refs,
        )

    def with_evidence(self, *ref_ids: str) -> "FactSlot[T]":
        """Return a copy carrying the given evidence ids, without duplicates."""
        merged = list(self.evidence_refs)
        merged.extend(ref for ref in ref_ids if ref not in merged)
        return replace(self, evidence_refs=tuple(merged))

    def with_warning(self, *messages: str) -> "FactSlot[T]":
        """Return a copy with additional non-fatal warnings appended."""
        return replace(self, warnings=(*self.warnings, *messages))


def first_available[T](slots: Iterable[FactSlot[T]]) -> FactSlot[T]:
    """Return the first available slot, else the first slot seen.

    Falls back to ``missing`` when the iterable is empty, so callers never
    receive ``None`` in place of a decision.
    """
    fallback: FactSlot[T] | None = None
    for slot in slots:
        if slot.is_available:
            return slot
        if fallback is None:
            fallback = slot
    return fallback if fallback is not None else FactSlot[T].missing("no candidate values")
