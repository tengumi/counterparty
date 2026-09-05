"""Shared validation and serialization conventions for public contracts."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict

SchemaVersion = Literal["0.1"]


def _as_utc(value: datetime) -> datetime:
    """Reject naive timestamps and normalize aware timestamps to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class ContractModel(BaseModel):
    """Base model for closed, assignment-validated public DTOs."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
