"""Closed value sets shared by public contracts."""

from enum import StrEnum


class Availability(StrEnum):
    """Whether a fact is available and how a non-value must be interpreted."""

    AVAILABLE = "available"
    MISSING = "missing"
    PRESENT_EMPTY = "present_empty"
    INVALID = "invalid"
    RESTRICTED = "restricted"


class DecisionOutcome(StrEnum):
    """Outcome explicitly recorded by a user."""

    READY = "ready"
    READY_WITH_CONDITIONS = "ready_with_conditions"
    NOT_READY = "not_ready"
    NEED_MORE_INFO = "need_more_info"


class WorkflowStatus(StrEnum):
    """Project workflow state, separate from risk and run status."""

    IN_PROGRESS = "in_progress"
    NEEDS_INFORMATION = "needs_information"
    DECISION_RECORDED = "decision_recorded"


class ThreadStatus(StrEnum):
    """Lifecycle state of a project thread."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    """Lifecycle state of one agent command execution."""

    ACCEPTED = "accepted"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    AWAITING_INPUT = "awaiting_input"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class EvidenceKind(StrEnum):
    """Supported provenance categories."""

    REPORT_FIELD = "report_field"
    DOCUMENT_FRAGMENT = "document_fragment"
    USER_MESSAGE = "user_message"
    ARTIFACT_SECTION = "artifact_section"
    DERIVED = "derived"


class ErrorCode(StrEnum):
    """Stable public error categories."""

    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    LIMIT_EXCEEDED = "limit_exceeded"
    SOURCE_MISSING = "source_missing"
    PARSE_FAILED = "parse_failed"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"
