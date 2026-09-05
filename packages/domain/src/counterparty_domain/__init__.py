"""Pure domain logic for Counterparty Workspace.

The package holds deterministic computations only: identifier validation,
value parsing with explicit availability semantics, and the evidence ledger
that keeps every factual output resolvable. It opens no network, database or
file handle, including at import time.
"""

from .errors import (
    DomainError,
    DuplicateEvidenceRefError,
    EvidenceError,
    IdentifierError,
    UnavailableValueError,
    UngroundedClaimError,
    UnknownEvidenceRefError,
    UnresolvableEvidenceRefError,
)
from .evidence import (
    EvidenceLedger,
    EvidenceProblem,
    EvidenceResolution,
    ReferenceProblem,
    require_grounded,
)
from .facts import UNKNOWN_AVAILABILITY, Availability, FactSlot, first_available
from .identifiers import (
    IdentifierKind,
    IdentifierProblem,
    IdentifierValidation,
    inn_check_digits,
    inn_slot,
    ogrn_slot,
    parse_inn,
    parse_kpp,
    parse_ogrn,
    validate_inn,
    validate_kpp,
    validate_ogrn,
)
from .values import (
    MAX_FISCAL_YEAR,
    MIN_FISCAL_YEAR,
    MONEY_EXPONENT,
    format_decimal,
    is_zero,
    parse_date,
    parse_decimal,
    parse_fiscal_year,
    parse_integer,
    quantize_money,
    sum_decimals,
)

__version__ = "0.1.0"

__all__ = [
    "MAX_FISCAL_YEAR",
    "MIN_FISCAL_YEAR",
    "MONEY_EXPONENT",
    "UNKNOWN_AVAILABILITY",
    "Availability",
    "DomainError",
    "DuplicateEvidenceRefError",
    "EvidenceError",
    "EvidenceLedger",
    "EvidenceProblem",
    "EvidenceResolution",
    "FactSlot",
    "IdentifierError",
    "IdentifierKind",
    "IdentifierProblem",
    "IdentifierValidation",
    "ReferenceProblem",
    "UnavailableValueError",
    "UngroundedClaimError",
    "UnknownEvidenceRefError",
    "UnresolvableEvidenceRefError",
    "__version__",
    "first_available",
    "format_decimal",
    "inn_check_digits",
    "inn_slot",
    "is_zero",
    "ogrn_slot",
    "parse_date",
    "parse_decimal",
    "parse_fiscal_year",
    "parse_inn",
    "parse_integer",
    "parse_kpp",
    "parse_ogrn",
    "quantize_money",
    "require_grounded",
    "sum_decimals",
    "validate_inn",
    "validate_kpp",
    "validate_ogrn",
]
