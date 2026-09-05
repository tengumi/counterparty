"""Public projection published to the UI.

The shape follows `PublicAgentState` in Specs 10 §7. It is a service-local
transport DTO on purpose: only the values it reuses (identifiers, run status,
error envelope) come from `packages/contracts`.
"""

from datetime import datetime
from typing import Literal

from counterparty_contracts import (
    ClientRequestId,
    Error,
    ErrorCode,
    ProjectId,
    RunId,
    RunInfo,
    RunStatus,
    ThreadId,
)
from pydantic import BaseModel, ConfigDict, Field

ActivityKind = Literal[
    "reading_report",
    "reading_document",
    "comparing",
    "calculating",
    "updating_analysis",
    "skill_invocation",
]
ActivityStatus = Literal["running", "completed", "failed"]
MessageRole = Literal["user", "assistant", "system_notice"]
MessageStatus = Literal["pending", "streaming", "complete", "partial", "error"]
SaveStatus = Literal["unsaved", "saving", "saved"]


class PublicModel(BaseModel):
    """Closed model for values that leave the service."""

    model_config = ConfigDict(extra="forbid")


class TextBlock(PublicModel):
    """The only block type this spike publishes."""

    type: Literal["text"] = "text"
    text: str


class PublicMessage(PublicModel):
    """One conversation message in the public projection."""

    id: str = Field(min_length=1)
    role: MessageRole
    blocks: list[TextBlock]
    status: MessageStatus
    created_at: datetime


class PublicActivity(PublicModel):
    """Safe activity label; never internal reasoning or raw tool arguments."""

    id: str = Field(min_length=1)
    kind: ActivityKind
    label: str = Field(min_length=1)
    status: ActivityStatus
    evidence_refs: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PublicAgentState(PublicModel):
    """Everything the UI renders for one thread."""

    schema_version: Literal["0.1"] = "0.1"
    project_id: ProjectId
    thread_id: ThreadId
    run: RunInfo | None = None
    revision: int = Field(ge=0)
    messages: list[PublicMessage] = Field(default_factory=list)
    activities: list[PublicActivity] = Field(default_factory=list)
    pending_commands: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    context_version: int = Field(ge=0)
    save_status: SaveStatus = "unsaved"


def initial_state(
    *,
    project_id: ProjectId,
    thread_id: ThreadId,
    run_id: RunId,
    started_at: datetime,
    user_message: PublicMessage,
) -> PublicAgentState:
    """Build the snapshot a fresh run starts from."""
    return PublicAgentState(
        project_id=project_id,
        thread_id=thread_id,
        run=RunInfo(
            id=run_id,
            thread_id=thread_id,
            project_id=project_id,
            status=RunStatus.ACCEPTED,
            started_at=started_at,
            based_on_context_version=0,
            last_public_revision=0,
        ),
        revision=0,
        messages=[user_message],
        context_version=0,
        save_status="unsaved",
    )


def public_error(*, code: ErrorCode, message: str, request_id: ClientRequestId) -> Error:
    """Wrap a safe message into the shared error envelope."""
    return Error(code=code, message=message, retryable=False, request_id=str(request_id))
