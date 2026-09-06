"""Extended JSON decoding, normalization and idempotent import of report snapshots."""

from .approved_source import (
    APPROVED_FILE_NAME,
    APPROVED_FILE_SHA256,
    APPROVED_RECORD_COUNT,
    APPROVED_SCHEMA_FINGERPRINT,
    SUPPORTED_WRAPPERS,
    SourceVerification,
    verify_source,
)
from .diagnostics import Diagnostic, diagnostic
from .extended_json import (
    MISSING,
    Decoded,
    DecodeIssue,
    FieldProbe,
    Invalid,
    IssueCode,
    Missing,
    SectionProbe,
    decode,
    json_pointer,
    load_source_file,
    probe_field,
    probe_section,
)
from .fingerprint import (
    FINGERPRINT_RULE_VERSION,
    SchemaFingerprint,
    canonical_json,
    file_digest,
    observed_shape,
    schema_fingerprint,
    snapshot_digest,
)
from .normalize import (
    FINANCIAL_COLUMNS,
    ZSK_DISPLAY_POLICY_VERSION,
    FailedRecord,
    NormalizedSnapshot,
    normalize,
)

__version__ = "0.1.0"

#: Recorded on every import batch so a stored row names the code that wrote it.
PARSER_VERSION = f"import_reports/{__version__}"

__all__ = [
    "APPROVED_FILE_NAME",
    "APPROVED_FILE_SHA256",
    "APPROVED_RECORD_COUNT",
    "APPROVED_SCHEMA_FINGERPRINT",
    "FINANCIAL_COLUMNS",
    "FINGERPRINT_RULE_VERSION",
    "MISSING",
    "PARSER_VERSION",
    "SUPPORTED_WRAPPERS",
    "ZSK_DISPLAY_POLICY_VERSION",
    "DecodeIssue",
    "Decoded",
    "Diagnostic",
    "FailedRecord",
    "FieldProbe",
    "Invalid",
    "IssueCode",
    "Missing",
    "NormalizedSnapshot",
    "SchemaFingerprint",
    "SectionProbe",
    "SourceVerification",
    "canonical_json",
    "decode",
    "diagnostic",
    "file_digest",
    "json_pointer",
    "load_source_file",
    "normalize",
    "observed_shape",
    "probe_field",
    "probe_section",
    "schema_fingerprint",
    "snapshot_digest",
    "verify_source",
]
