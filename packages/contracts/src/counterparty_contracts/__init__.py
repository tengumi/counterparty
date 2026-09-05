"""Public contracts shared by Counterparty Workspace services."""

from .enums import (
    Availability,
    DecisionOutcome,
    ErrorCode,
    EvidenceKind,
    RunStatus,
    ThreadStatus,
    WorkflowStatus,
)
from .envelopes import Error, ProjectEnvelope, RunInfo, ThreadEnvelope
from .evidence import (
    DocumentLocator,
    EvidenceRef,
    PdfPageLocator,
    SpreadsheetRangeLocator,
    TextLinesLocator,
    WordBlockLocator,
)
from .identifiers import (
    ArtifactId,
    ClientRequestId,
    CompanyId,
    DecisionId,
    DocumentId,
    EvidenceRefId,
    FragmentId,
    ProjectId,
    ReportId,
    RunId,
    TenantId,
    ThreadId,
    UserId,
)

__version__ = "0.1.0"

__all__ = [
    "ArtifactId",
    "Availability",
    "ClientRequestId",
    "CompanyId",
    "DecisionId",
    "DecisionOutcome",
    "DocumentId",
    "DocumentLocator",
    "Error",
    "ErrorCode",
    "EvidenceKind",
    "EvidenceRef",
    "EvidenceRefId",
    "FragmentId",
    "PdfPageLocator",
    "ProjectEnvelope",
    "ProjectId",
    "ReportId",
    "RunId",
    "RunInfo",
    "RunStatus",
    "SpreadsheetRangeLocator",
    "TenantId",
    "TextLinesLocator",
    "ThreadEnvelope",
    "ThreadId",
    "ThreadStatus",
    "UserId",
    "WordBlockLocator",
    "WorkflowStatus",
]
