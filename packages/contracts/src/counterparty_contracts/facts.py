"""The public representation of one typed fact and why it is or is not there.

``FactValue`` is the API projection of :class:`counterparty_domain.FactSlot`
and keeps the same rule: *missing*, *present_empty*, *invalid* and *restricted*
are different answers and none of them is ``0``. A trustworthy zero is an
``available`` value like any other.

``restricted`` describes what this caller may see. It is not the source-file
state recorded in ``reports.section_availability``.
"""

from typing import Self

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyString, SchemaVersion
from .diagnostics import ContractWarning
from .enums import Availability, ValueType
from .identifiers import EvidenceRefId
from .values import CurrencyCode, parse_calendar_date, parse_decimal_string

__all__ = ["FactValue", "FactValueScalar"]

FactValueScalar = bool | int | str
"""JSON scalars a fact may carry. Decimals and dates travel as strings."""


class FactValue(ContractModel):
    """One named fact with its type, availability and grounding.

    Attributes:
        key: Stable machine key, unique inside its containing collection.
        label: Human-readable caption; never the carrier of the value itself.
        value: The payload, or ``None`` whenever ``availability`` is not
            ``available``.
        value_type: Declared type the payload must match exactly.
        unit: Unit of measure when the number alone is ambiguous.
        currency: Currency of a monetary decimal; absent for non-money values.
        period: Reporting year or period label the fact belongs to.
        availability: Why a non-value is not there, per the domain semantics.
        evidence_refs: Resolvable evidence ids. At least one is required for an
            available value, so no reported fact is ungrounded.
        warnings: Typed non-fatal notes about precision, age or comparability.
            Each note names its category, so a client can group or suppress it
            without matching free-form text.
    """

    schema_version: SchemaVersion = "0.1"
    key: NonEmptyString
    label: NonEmptyString
    value: FactValueScalar | None = None
    value_type: ValueType
    unit: NonEmptyString | None = None
    currency: CurrencyCode | None = None
    period: int | str | None = None
    availability: Availability
    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)
    warnings: list[ContractWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_availability_and_type(self) -> Self:
        """Keep the payload, its declared type and its availability consistent."""
        if self.availability is Availability.AVAILABLE:
            if self.value is None:
                raise ValueError("an available fact must carry a value")
            if not self.evidence_refs:
                raise ValueError("an available fact must reference at least one evidence ref")
        elif self.value is not None:
            raise ValueError(f"a {self.availability.value} fact must not carry a value")

        if self.currency is not None and self.value_type is not ValueType.DECIMAL:
            raise ValueError("currency applies only to a decimal fact")

        if self.value is not None:
            self._validate_payload_type()
        return self

    def _validate_payload_type(self) -> None:
        """Reject a payload whose runtime type contradicts ``value_type``."""
        value = self.value
        if self.value_type is ValueType.BOOLEAN:
            if not isinstance(value, bool):
                raise ValueError("a boolean fact must carry true or false")
            return
        if isinstance(value, bool):
            raise ValueError(f"a {self.value_type.value} fact must not carry a boolean")
        if self.value_type is ValueType.INTEGER:
            if not isinstance(value, int):
                raise ValueError("an integer fact must carry an integer")
            return
        if not isinstance(value, str):
            raise ValueError(f"a {self.value_type.value} fact must carry a string")
        if not value:
            raise ValueError(f"a {self.value_type.value} fact must not carry an empty string")
        if self.value_type is ValueType.DECIMAL:
            parse_decimal_string(value)
        elif self.value_type is ValueType.DATE:
            parse_calendar_date(value)

    @property
    def is_available(self) -> bool:
        """Whether a trustworthy value is present, including a real zero."""
        return self.availability is Availability.AVAILABLE

    @property
    def is_unknown(self) -> bool:
        """Whether the true value is unknown, so no conclusion may be drawn."""
        return self.availability in {
            Availability.MISSING,
            Availability.INVALID,
            Availability.RESTRICTED,
        }
