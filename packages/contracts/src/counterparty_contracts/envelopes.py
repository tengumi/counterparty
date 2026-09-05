"""Minimal public project, thread, and run envelopes."""

from pydantic import Field, JsonValue

from .base import ContractModel, SchemaVersion, UtcDatetime
from .enums import ErrorCode, RunStatus, ThreadStatus, WorkflowStatus
from .identifiers import ProjectId, RunId, ThreadId


class Error(ContractModel):
    """Safe error information suitable for a public response."""

    schema_version: SchemaVersion = "0.1"
    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool
    request_id: str = Field(min_length=1)
    details: dict[str, JsonValue] | None = None


class ProjectEnvelope(ContractModel):
    """Stable project identity and concurrency metadata for early integrations."""

    schema_version: SchemaVersion = "0.1"
    id: ProjectId
    title: str = Field(min_length=1)
    default_thread_id: ThreadId
    threads_count: int = Field(ge=1)
    context_version: int = Field(ge=0)
    workflow_status: WorkflowStatus
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ThreadEnvelope(ContractModel):
    """Public summary of one persistent conversation inside a project."""

    schema_version: SchemaVersion = "0.1"
    id: ThreadId
    project_id: ProjectId
    title: str = Field(min_length=1)
    status: ThreadStatus
    last_activity_at: UtcDatetime
    active_run_id: RunId | None = None
    last_open_question: str | None = None
    archived_at: UtcDatetime | None = None


class RunInfo(ContractModel):
    """Public lifecycle information for one agent run."""

    schema_version: SchemaVersion = "0.1"
    id: RunId
    thread_id: ThreadId
    project_id: ProjectId
    status: RunStatus
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    based_on_context_version: int = Field(ge=0)
    last_public_revision: int = Field(ge=0)
    error: Error | None = None
