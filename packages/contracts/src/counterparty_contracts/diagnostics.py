"""One non-fatal diagnostic attached to a published payload.

A warning explains why a result is less complete or less precise than it looks.
It is machine-readable on purpose: a UI has to be able to group, translate and
suppress diagnostics without matching free-form English, and a plain sentence
cannot say which source field it is about.

The shape mirrors the stored import diagnostic
(``reports.import_warnings``): a stable ``code``, a human ``message`` and the
optional ``source_path`` the diagnostic is about. A warning never carries a
value, never downgrades a value to a default and never becomes a conclusion:
"the total is unknown" stays a warning, not a zero.
"""

import re

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyString
from .enums import WarningCode

__all__ = ["ContractWarning", "unspecified_warning"]

_JSON_POINTER = re.compile(r"/(?:[^~]|~[01])*")


class ContractWarning(ContractModel):
    """A non-fatal note about precision, age, completeness or comparability.

    Attributes:
        code: Stable category a client may branch on. Unknown-to-the-client
            codes are still displayed through ``message`` rather than dropped.
        message: Human-readable explanation; never the carrier of a value.
        source_path: RFC 6901 JSON Pointer into the source ``report`` object
            the diagnostic is about, when the warning is about one field.
    """

    code: WarningCode
    message: NonEmptyString
    source_path: NonEmptyString | None = Field(default=None)

    @model_validator(mode="after")
    def validate_source_path(self) -> "ContractWarning":
        """Keep ``source_path`` a resolvable pointer rather than prose."""
        if self.source_path is not None and _JSON_POINTER.fullmatch(self.source_path) is None:
            raise ValueError("warning source_path must be an RFC 6901 JSON Pointer")
        return self


def unspecified_warning(message: str, *, source_path: str | None = None) -> ContractWarning:
    """Wrap a plain diagnostic sentence that has no category yet.

    The deterministic layer (``counterparty_domain``) still collects warnings as
    plain strings. Projecting one keeps the text and marks it
    :attr:`WarningCode.UNSPECIFIED` instead of guessing a category, so a note is
    never lost on the way to the API and never claims a meaning it does not have.

    Args:
        message: The diagnostic text produced by the lower layer.
        source_path: JSON Pointer of the source field, when it is known.

    Returns:
        The wrapped warning.
    """
    return ContractWarning(code=WarningCode.UNSPECIFIED, message=message, source_path=source_path)
