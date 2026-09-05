"""Import diagnostics, typed with the published warning vocabulary.

A diagnostic is what the import knows but the data cannot say: an unknown
section, a number it could not read, an external token whose meaning is not
confirmed. None of them is allowed to become a default value, so each one is
recorded as a row in ``reports.import_warnings`` and none of them is swallowed.

The carrier is :class:`counterparty_contracts.ContractWarning`, not a private
shape of this script: the stored diagnostic and the one a client eventually
sees are the same three fields — a stable ``code``, a human ``message`` and the
RFC 6901 ``source_path`` the note is about. Building it here means the pointer
is validated at the moment it is produced, and a warning that cannot be
addressed back to the source never reaches the database.

Anything more specific than the published vocabulary lives in ``details``,
which reaches ``import_warnings.details_jsonb``. That keeps the code column a
closed set a client may branch on while still letting the import report name
exactly which section or which key was not understood.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from counterparty_contracts import ContractWarning, WarningCode
from counterparty_storage.reports import WarningSeverity

__all__ = ["Diagnostic", "diagnostic"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One import warning together with how serious it is."""

    severity: WarningSeverity
    warning: ContractWarning
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def code(self) -> str:
        """Stable category, as stored and as published."""
        return self.warning.code.value

    @property
    def message(self) -> str:
        """Human-readable explanation. Never the carrier of a value."""
        return self.warning.message

    @property
    def source_path(self) -> str | None:
        """Pointer into the source ``report`` object, when the note is about one field."""
        return self.warning.source_path

    @property
    def is_error(self) -> bool:
        """Whether this diagnostic means a section did not normalize."""
        return self.severity is WarningSeverity.ERROR


def diagnostic(
    code: WarningCode,
    message: str,
    *,
    severity: WarningSeverity = WarningSeverity.WARNING,
    source_path: str | None = None,
    **details: Any,
) -> Diagnostic:
    """Build a diagnostic, validating its pointer through the published contract.

    Args:
        code: Published warning category. A note with no category yet uses
            :attr:`WarningCode.UNSPECIFIED` rather than an invented one.
        message: What was not understood, in words.
        severity: ``error`` marks a section that failed to normalize and
            therefore downgrades the snapshot's ingestion status.
        source_path: RFC 6901 pointer relative to the source ``report`` object.
        **details: Anything narrower than ``code``, stored as JSONB.
    """
    return Diagnostic(
        severity=severity,
        warning=ContractWarning(code=code, message=message, source_path=source_path),
        details=dict(details),
    )
