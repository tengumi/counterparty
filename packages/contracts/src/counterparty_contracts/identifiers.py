"""Semantically distinct resource identifiers used across service boundaries."""

from typing import NewType
from uuid import UUID

TenantId = NewType("TenantId", UUID)
UserId = NewType("UserId", UUID)
ProjectId = NewType("ProjectId", UUID)
ThreadId = NewType("ThreadId", UUID)
RunId = NewType("RunId", UUID)
ClientRequestId = NewType("ClientRequestId", UUID)
ReportId = NewType("ReportId", UUID)
CompanyId = NewType("CompanyId", UUID)
DocumentId = NewType("DocumentId", UUID)
FragmentId = NewType("FragmentId", UUID)
ArtifactId = NewType("ArtifactId", UUID)
DecisionId = NewType("DecisionId", UUID)

# Evidence IDs are stable opaque server strings, not necessarily UUIDs.
EvidenceRefId = NewType("EvidenceRefId", str)
