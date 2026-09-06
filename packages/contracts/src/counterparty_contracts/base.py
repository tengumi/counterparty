"""Shared validation and serialization conventions for public contracts."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

SchemaVersion = Literal["0.1"]


def _as_utc(value: datetime) -> datetime:
    """Reject naive timestamps and normalize aware timestamps to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]
"""An exact instant in UTC. Source ``$date`` values keep this type: they
encode local midnights at more than one offset, so a calendar date cannot
be derived without guessing a timezone."""

NonEmptyString = Annotated[str, Field(min_length=1)]
"""A string that must carry content; an empty string is not a value."""


class ContractModel(BaseModel):
    """Base model for closed, assignment-validated public DTOs."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
