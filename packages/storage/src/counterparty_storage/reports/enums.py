"""Closed value sets used by the ``reports`` schema.

These describe the *state of the source file*, which is deliberately not the
same vocabulary as the public ``Availability`` DTO enum: a section that is
absent, present but empty, present with data, or present but unparsable are
four different facts about the provided snapshot, and none of them may be
collapsed into "no risk" or into a zero.
"""

from enum import StrEnum


class SourceState(StrEnum):
    """How one section of the source report was actually found."""

    MISSING = "missing"
    """The key is absent from the source object."""

    PRESENT_EMPTY = "present_empty"
    """The key exists but carries no records: ``[]``, ``{}`` or ``null``."""

    PRESENT = "present"
    """The key exists and carries at least one record or a usable value."""

    INVALID = "invalid"
    """The key exists but could not be parsed; the raw value is kept as-is."""


class IngestionStatus(StrEnum):
    """How completely one snapshot was normalized into typed rows."""

    COMPLETE = "complete"
    """Every recognized section was normalized without an error."""

    PARTIAL = "partial"
    """The raw snapshot is stored, but at least one section failed to normalize."""

    INVALID = "invalid"
    """Only raw/diagnostic data is trustworthy; typed rows must not be served."""


class WarningSeverity(StrEnum):
    """Severity of one import warning."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
