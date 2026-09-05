"""What the agent publishes to the UI, and what the UI may ask it to do.

Two boundaries are encoded here.

The published projection (:class:`PublicAgentState`) is a whitelist. Internal
prompts, hidden memory, chain-of-thought and whole raw tool arguments or
results are not representable in these types, so they cannot leak by being
forwarded. A message is made of typed blocks from a closed union: the model
never sends executable HTML or a component to render.

The command side (:data:`AgentCommand`) is a small closed set too. The client
names an intent and its references; it does not choose a model, a system prompt
or a tool, and the server never accepts a project, tenant or author identity
from the body. ``client_request_id`` makes a repeat of the same command return
the same result instead of running twice.

The wire envelope of the stream belongs to the pinned assistant-stream version.
These DTOs are the meaning that envelope carries, and they are not a second
streaming protocol.
"""

from collections.abc import Iterable
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyString, SchemaVersion, UtcDatetime
from .enums import (
    ActivityKind,
    ActivityStatus,
    MessageRole,
    MessageStatus,
    PendingCommandStatus,
    SaveStatus,
    SkillInvocationStatus,
)
from .envelopes import Error, RunInfo
from .identifiers import (
    ArtifactId,
    ClientRequestId,
    CompanyId,
    DocumentId,
    EvidenceRefId,
    FragmentId,
    ProjectId,
    RunId,
    ThreadId,
)
from .projects import ArtifactAttachment
from .values import NonNegativeCount

__all__ = [
    "AddMessageCommand",
    "AgentCommand",
    "AnalysisReferenceBlock",
    "CancelRunRequest",
    "ChatRequest",
    "CommandMessage",
    "ComparisonReferenceBlock",
    "ContinueCommand",
    "ContinueRunRequest",
    "DocumentReferenceBlock",
    "EvidenceReferenceBlock",
    "FollowUpRequest",
    "MessageBlock",
    "PendingCommand",
    "PendingCommandsResponse",
    "PendingQuestion",
    "PublicActivity",
    "PublicAgentState",
    "PublicMessage",
    "QuestionBlock",
    "ReanalyzeCommand",
    "SkillInvocation",
    "SubscribeRequest",
    "TextBlock",
    "ThreadConversationState",
]


class TextBlock(ContractModel):
    """Plain text written by the assistant, the user or the service."""

    type: Literal["text"] = "text"
    text: NonEmptyString


class EvidenceReferenceBlock(ContractModel):
    """A pointer to a fact the server can resolve.

    The reference is resolved by the server; the model cannot invent a URL, and
    the UI decides where the resolved source is shown.
    """

    type: Literal["evidence_reference"] = "evidence_reference"
    evidence_ref_id: EvidenceRefId
    label: NonEmptyString | None = None


class DocumentReferenceBlock(ContractModel):
    """A pointer to an uploaded document, optionally to one fragment of it."""

    type: Literal["document_reference"] = "document_reference"
    document_id: DocumentId
    fragment_id: FragmentId | None = None
    label: NonEmptyString | None = None


class AnalysisReferenceBlock(ContractModel):
    """A pointer to one immutable version of an AI artifact.

    An attached conclusion is not a source fact: it stands on its own evidence
    refs, and pinning the version keeps an older answer readable unchanged.
    """

    type: Literal["analysis_reference"] = "analysis_reference"
    artifact_id: ArtifactId
    artifact_version: int = Field(ge=1)
    section_id: NonEmptyString | None = None
    label: NonEmptyString | None = None


class ComparisonReferenceBlock(ContractModel):
    """A pointer to a comparison the deterministic layer produced.

    The reference names a stored comparison; it carries no winner and no
    aggregate score, because neither exists.
    """

    type: Literal["comparison_reference"] = "comparison_reference"
    comparison_id: UUID
    """The id of a stored :class:`~counterparty_contracts.reports.Comparison`."""

    company_ids: list[CompanyId] = Field(default_factory=list)
    label: NonEmptyString | None = None


class QuestionBlock(ContractModel):
    """A concrete question the agent needs answered to continue."""

    type: Literal["question"] = "question"
    question_id: NonEmptyString
    text: NonEmptyString


MessageBlock = Annotated[
    TextBlock
    | EvidenceReferenceBlock
    | DocumentReferenceBlock
    | AnalysisReferenceBlock
    | ComparisonReferenceBlock
    | QuestionBlock,
    Field(discriminator="type"),
]
"""The closed set of renderable blocks. A type outside it is not publishable."""


class PublicMessage(ContractModel):
    """One conversation message as the UI renders it."""

    id: NonEmptyString
    role: MessageRole
    blocks: list[MessageBlock] = Field(default_factory=list)
    status: MessageStatus
    created_at: UtcDatetime

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        """Require content once a message claims to have produced any."""
        if not self.blocks and self.status in {MessageStatus.COMPLETE, MessageStatus.PARTIAL}:
            raise ValueError(f"a {self.status.value} message must carry at least one block")
        return self


class SkillInvocation(ContractModel):
    """One skill execution, published by the executor rather than the model.

    The manifest of allowed tools is metadata; what a skill may actually do is
    decided by the server.
    """

    schema_version: SchemaVersion = "0.1"
    id: NonEmptyString
    thread_id: ThreadId
    run_id: RunId
    skill_id: NonEmptyString
    skill_version: NonEmptyString
    source_commit: NonEmptyString | None = None
    display_name: NonEmptyString
    status: SkillInvocationStatus
    input_refs: list[EvidenceRefId] = Field(default_factory=list)
    output_refs: list[EvidenceRefId] = Field(default_factory=list)
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    error: Error | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        """Keep the timestamps and the failure reason consistent with status."""
        _validate_interval(self.started_at, self.finished_at)
        if self.status is SkillInvocationStatus.FAILED and self.error is None:
            raise ValueError("a failed skill invocation must explain itself")
        return self


class PublicActivity(ContractModel):
    """A safe label of what the agent is doing, with what it used.

    This is a product-level trace, not a mirror of every internal callback.
    ``label`` is a caption; it never carries raw tool input or output.
    """

    id: NonEmptyString
    kind: ActivityKind
    label: NonEmptyString
    status: ActivityStatus
    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)
    skill_invocation_id: NonEmptyString | None = None
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def validate_activity(self) -> Self:
        """Order the timestamps and tie a skill activity to its invocation."""
        _validate_interval(self.started_at, self.finished_at)
        if self.kind is ActivityKind.SKILL_INVOCATION and self.skill_invocation_id is None:
            raise ValueError("a skill activity must name the invocation it reports")
        return self


def _validate_interval(started_at: UtcDatetime | None, finished_at: UtcDatetime | None) -> None:
    """Reject an interval that ends before it starts or without starting.

    Raises:
        ValueError: If the interval is finished but never started, or ends
            before it begins.
    """
    if finished_at is None:
        return
    if started_at is None:
        raise ValueError("a finished interval must say when it started")
    if finished_at < started_at:
        raise ValueError("a finished interval must not end before it started")


class PendingQuestion(ContractModel):
    """One open question the agent still needs an answer to.

    A question is a concrete missing fact with its own grounds, never a generic
    disclaimer, and it survives a reconnect: the UI restores it from the
    projection rather than from the stream it missed.
    """

    id: NonEmptyString
    text: NonEmptyString
    asked_at: UtcDatetime
    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)


class PendingCommand(ContractModel):
    """A follow-up accepted while a run is already working.

    It is accepted immediately, independently of any active subscription, so a
    message is never lost because the page was reloading. ``applied`` means it
    entered the conversation context at a safe boundary and was persisted; it
    does not mean the answer is finished. Repeating the same
    ``client_request_id`` returns this same command instead of queueing a
    duplicate.
    """

    schema_version: SchemaVersion = "0.1"
    id: NonEmptyString
    thread_id: ThreadId
    run_id: RunId | None = None
    sequence: NonNegativeCount
    message_id: NonEmptyString
    client_request_id: ClientRequestId
    status: PendingCommandStatus
    received_at: UtcDatetime
    applied_at: UtcDatetime | None = None
    error: Error | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        """Tie the applied instant and the failure reason to the status."""
        if (self.status is PendingCommandStatus.APPLIED) != (self.applied_at is not None):
            raise ValueError("an applied command states when it was applied, and only then")
        if self.status is PendingCommandStatus.FAILED and self.error is None:
            raise ValueError("a failed command must explain itself")
        return self


class PendingCommandsResponse(ContractModel):
    """The follow-up queue of one thread, for restoring the UI after a reload."""

    schema_version: SchemaVersion = "0.1"
    thread_id: ThreadId
    commands: list[PendingCommand] = Field(default_factory=list)


class PublicAgentState(ContractModel):
    """Everything the UI renders for one thread of one project.

    This is the whole public surface of a run. It is the projection restored on
    reconnect, so a client that missed part of the stream is not missing part of
    the result. Replaying every lost token is not required; keeping completed
    messages and artifacts is.

    ``save_status`` is the server's own confirmation that the projection was
    persisted, and ``revision`` orders projections: a late update must not
    overwrite a newer one.
    """

    schema_version: SchemaVersion = "0.1"
    project_id: ProjectId
    thread_id: ThreadId
    run: RunInfo | None = None
    revision: NonNegativeCount
    messages: list[PublicMessage] = Field(default_factory=list)
    activities: list[PublicActivity] = Field(default_factory=list)
    pending_commands: list[PendingCommand] = Field(default_factory=list)
    pending_questions: list[PendingQuestion] = Field(default_factory=list)
    artifact_refs: list[ArtifactAttachment] = Field(default_factory=list)
    context_version: NonNegativeCount
    save_status: SaveStatus = SaveStatus.UNSAVED

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        """Keep the projection internally addressable and correctly scoped."""
        _require_unique(message.id for message in self.messages)
        _require_unique(activity.id for activity in self.activities)
        _require_unique(command.id for command in self.pending_commands)
        _require_unique(question.id for question in self.pending_questions)
        if self.run is not None and (
            self.run.thread_id != self.thread_id or self.run.project_id != self.project_id
        ):
            raise ValueError("the published run must belong to this project and thread")
        for command in self.pending_commands:
            if command.thread_id != self.thread_id:
                raise ValueError("a pending command of another thread is not publishable here")
        return self


class ThreadConversationState(PublicAgentState):
    """The stored projection of one thread, read over REST when a chat opens.

    It is the same public projection a run streams, plus ``active_run_id``: the
    run still executing on the server, which the client reconnects to instead of
    re-sending the message that started it. ``None`` means no run is live, not
    that the history is empty.
    """

    active_run_id: RunId | None = None

    @model_validator(mode="after")
    def validate_active_run(self) -> Self:
        """Keep ``active_run_id`` consistent with the published run."""
        if (
            self.active_run_id is not None
            and self.run is not None
            and self.run.id != self.active_run_id
        ):
            raise ValueError("active_run_id must name the published run")
        return self


def _require_unique(ids: Iterable[str]) -> None:
    """Reject a repeated identifier inside one projection.

    Args:
        ids: Identifiers to check.

    Raises:
        ValueError: If any identifier appears more than once.
    """
    seen: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            raise ValueError(f"duplicate id {identifier!r}")
        seen.add(identifier)


class CommandMessage(ContractModel):
    """The user's message and the material they attached to it.

    Attachments are named by identifier; the server resolves each one inside
    the project scope. No text of a document and no server path travels here.
    """

    id: NonEmptyString
    text: NonEmptyString
    document_ids: list[DocumentId] = Field(default_factory=list)
    artifact_refs: list[ArtifactAttachment] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefId] = Field(default_factory=list)
    company_ids: list[CompanyId] = Field(default_factory=list)


class AddMessageCommand(ContractModel):
    """Add one user message to the thread."""

    type: Literal["add-message"] = "add-message"
    message: CommandMessage


class ReanalyzeCommand(ContractModel):
    """Redo the analysis because the project context changed.

    The command names the context version it reacts to, so an answer built on
    an older version stays identifiable as outdated instead of being silently
    replaced.
    """

    type: Literal["reanalyze"] = "reanalyze"
    changed_context_version: NonNegativeCount
    reason: NonEmptyString


class ContinueCommand(ContractModel):
    """Answer a pending question or resume an interrupted run."""

    type: Literal["continue"] = "continue"
    question_id: NonEmptyString | None = None
    answer: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_answer(self) -> Self:
        """An answer must say which question it answers."""
        if self.question_id is not None and self.answer is None:
            raise ValueError("answering a question requires the answer")
        return self


AgentCommand = Annotated[
    AddMessageCommand | ReanalyzeCommand | ContinueCommand,
    Field(discriminator="type"),
]
"""The closed set of commands the UI may send. Model, system prompt and tool
configuration are not commands and are never executed from a browser."""


class ChatRequest(ContractModel):
    """One command batch for one thread.

    The scope is stated explicitly and verified by the server; the client never
    proves ownership by asserting it. Repeating ``client_request_id`` returns
    the same run instead of starting a second one.
    """

    project_id: ProjectId
    thread_id: ThreadId
    client_request_id: ClientRequestId
    commands: list[AgentCommand] = Field(min_length=1)
    stream: bool = True


class SubscribeRequest(ContractModel):
    """Subscribe to an existing run without starting it again.

    ``known_revision`` says what the client already has, so reconnecting after
    a lost connection does not re-run the original message.
    """

    project_id: ProjectId
    known_revision: NonNegativeCount | None = None


class FollowUpRequest(ContractModel):
    """Send a message while a run is working; it is accepted immediately."""

    project_id: ProjectId
    client_request_id: ClientRequestId
    message: CommandMessage


class CancelRunRequest(ContractModel):
    """Cancel a run. Repeating the same request cancels it once."""

    client_request_id: ClientRequestId


class ContinueRunRequest(ContractModel):
    """Resume a run that is interrupted or awaiting an answer."""

    client_request_id: ClientRequestId
    question_id: NonEmptyString | None = None
    answer: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_answer(self) -> Self:
        """An answer must say which question it answers."""
        if self.question_id is not None and self.answer is None:
            raise ValueError("answering a question requires the answer")
        return self
