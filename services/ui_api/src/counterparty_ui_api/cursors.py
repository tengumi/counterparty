"""Opaque cursors for the list endpoints.

A cursor names the exact row a page ended on — a sort key and the id that
breaks its ties — rather than an offset. Two rows written in the same instant
are therefore still paged through exactly once, and a project created while the
user is paging does not shift the page under them.

The value is opaque on purpose: it is a server-owned position, not a client-
editable filter. A cursor that does not decode is refused as a validation
error rather than quietly treated as "start from the beginning", which would
silently repeat a page the caller has already seen.
"""

import base64
import binascii
from datetime import UTC, datetime
from uuid import UUID

from counterparty_contracts import ErrorCode

from .errors import ApiError

__all__ = ["Cursor", "decode_cursor", "encode_cursor"]

_SEPARATOR = "\x1f"


class Cursor:
    """Position of the last row of a page: its sort key and its id."""

    __slots__ = ("key", "row_id")

    def __init__(self, key: str, row_id: UUID) -> None:
        """Record the sort key and the tie-breaking id."""
        self.key = key
        self.row_id = row_id

    @property
    def instant(self) -> datetime:
        """The sort key read back as an instant.

        Raises:
            ApiError: If the key is not a timestamp.
        """
        try:
            parsed = datetime.fromisoformat(self.key)
        except ValueError as error:
            raise _invalid() from error
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def encode_cursor(key: str | datetime, row_id: UUID) -> str:
    """Render one position as an opaque string."""
    rendered = key.isoformat() if isinstance(key, datetime) else key
    raw = f"{rendered}{_SEPARATOR}{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> Cursor:
    """Read a cursor back.

    Raises:
        ApiError: If the value was not produced by :func:`encode_cursor`.
    """
    padded = value + "=" * (-len(value) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        key, row_id = raw.split(_SEPARATOR)
        return Cursor(key=key, row_id=UUID(row_id))
    except (ValueError, binascii.Error, UnicodeDecodeError) as error:
        raise _invalid() from error


def _invalid() -> ApiError:
    """Return the refusal used for a cursor this server did not issue."""
    return ApiError(ErrorCode.VALIDATION_ERROR, "the pagination cursor is not valid")
