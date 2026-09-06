"""Closed value sets used by the ``workspace`` schema.

Every value here is written exactly as the public REST DTO writes it, so a row
maps onto ``counterparty_contracts`` without a translation layer. The classes
are declared locally rather than imported: ``counterparty-storage`` stays free
of a dependency on the contracts package (and therefore of pydantic), and the
values are pinned by :mod:`tests.test_workspace_schema` instead.
"""

from enum import StrEnum


class WorkflowStatus(StrEnum):
    """Project workflow state. Not a run status and not a risk assessment."""

    IN_PROGRESS = "in_progress"
    NEEDS_INFORMATION = "needs_information"
    DECISION_RECORDED = "decision_recorded"


class ThreadStatus(StrEnum):
    """Lifecycle state of one chat inside a project."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class CounterpartyRole(StrEnum):
    """Role the counterparty plays in the deal under review."""

    SUPPLIER = "supplier"
    BUYER = "buyer"
    CONTRACTOR = "contractor"
    OTHER = "other"
    UNKNOWN = "unknown"


class IdempotencyState(StrEnum):
    """Lifecycle of one reserved request id.

    A key is reserved before the work starts, so two concurrent copies of the
    same request cannot both proceed; it becomes ``completed`` only together
    with the identity of what was actually created.
    """

    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"


class DecisionOutcome(StrEnum):
    """The variant the user recorded. Values match the public DecisionOutcome."""

    READY = "ready"
    READY_WITH_CONDITIONS = "ready_with_conditions"
    NOT_READY = "not_ready"
    NEED_MORE_INFO = "need_more_info"


class ArtifactFreshness(StrEnum):
    """Whether the context an artifact was drawn from still holds.

    Values match the public ArtifactFreshness. It qualifies a stored conclusion;
    it never edits one.
    """

    CURRENT = "current"
    OUTDATED = "outdated"
    SOURCE_REMOVED = "source_removed"


class AgentRunStatus(StrEnum):
    """Durable execution status; values match the existing public RunStatus."""

    ACCEPTED = "accepted"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    AWAITING_INPUT = "awaiting_input"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
