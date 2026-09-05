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


class ValueType(StrEnum):
    """Declared type of a :class:`FactValue` payload.

    A non-null value matches its type exactly. ``DECIMAL`` travels as a plain
    string, ``DATE`` as a display-layer ``YYYY-MM-DD`` day, and ``ENUM`` as the
    raw external token, which is never rewritten into a known member.
    """

    DECIMAL = "decimal"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    STRING = "string"
    DATE = "date"
    ENUM = "enum"


class DisplayLevel(StrEnum):
    """How a raw external assessment may be presented.

    The level is a presentation decision over a value we did not compute. An
    unmapped or unknown raw value is ``NEUTRAL`` with an explanation; it never
    falls back to a favourable level.
    """

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    ATTENTION = "attention"
    NEGATIVE = "negative"


class ReportSectionName(StrEnum):
    """Addressable section of one report snapshot.

    Names are public and stable; the source keys they were parsed from are in
    :data:`counterparty_contracts.reports.SECTION_SOURCE_KEYS`.
    """

    PROFILE = "profile"
    STATUS = "status"
    ACTIVITIES = "activities"
    FINANCIALS = "financials"
    COEFFICIENTS = "coefficients"
    FOUNDERS = "founders"
    TAX_SYSTEMS = "tax_systems"
    CONTACTS = "contacts"
    EXECUTION_PROCEEDINGS = "execution_proceedings"
    ARBITRATION = "arbitration"
    PROCUREMENTS = "procurements"
    LICENSES = "licenses"
    INSPECTIONS = "inspections"
    RELATED_COMPANIES = "related_companies"
    BRANCHES = "branches"
    RISK_SIGNALS = "risk_signals"
    ZSK = "zsk"


class PartyRole(StrEnum):
    """Side a company took in an arbitration aggregate."""

    PLAINTIFF = "plaintiff"
    DEFENDANT = "defendant"


class ArbitrationAggregation(StrEnum):
    """Dimension one arbitration aggregate is grouped by.

    Status and year aggregates describe the same cases from two angles and are
    never summed together: doing so double counts.
    """

    BY_STATUS = "status"
    BY_YEAR = "year"


class RiskSignalPolarity(StrEnum):
    """Direction of a reputational signal as published by the source."""

    NEGATIVE = "negative"
    POSITIVE = "positive"


class ComparisonCriterion(StrEnum):
    """Whitelisted comparison criterion. No free-form expression is accepted."""

    BANK_RISK = "bank_risk"
    STATUS = "status"
    FINANCIALS = "financials"
    PROCEEDINGS = "proceedings"
    ARBITRATION = "arbitration"
    ACTIVITIES = "activities"
    LICENSES = "licenses"
    PROCUREMENT = "procurement"
    COMPLETENESS = "completeness"


class YearPolicy(StrEnum):
    """How comparable financial periods are chosen across companies."""

    COMMON_LATEST = "common_latest"
    LATEST_AVAILABLE = "latest_available"
    EXPLICIT = "explicit"


class ComparisonRowStatus(StrEnum):
    """Per-company outcome of one comparison row.

    A partial or unavailable row is reported as such; an unknown value is never
    ranked as the worst number.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class CounterpartyRole(StrEnum):
    """Role the counterparty plays in the deal under review."""

    SUPPLIER = "supplier"
    BUYER = "buyer"
    CONTRACTOR = "contractor"
    OTHER = "other"
    UNKNOWN = "unknown"


class ProjectFactKey(StrEnum):
    """Whitelisted deal-term keys of the project context."""

    COUNTERPARTY_ROLE = "counterparty_role"
    SUBJECT = "subject"
    AMOUNT = "amount"
    PAYMENT_TYPE = "payment_type"
    ADVANCE_PERCENT = "advance_percent"
    DELIVERY_DEADLINE = "delivery_deadline"
    DELIVERY_TERMS = "delivery_terms"
    USER_PRIORITY = "user_priority"


class ConfirmationStatus(StrEnum):
    """How trustworthy one deal term is."""

    USER_CONFIRMED = "user_confirmed"
    EXTRACTED_UNCONFIRMED = "extracted_unconfirmed"
    INFERRED = "inferred"


class ArtifactFreshness(StrEnum):
    """Whether an AI artifact still matches the project context it used."""

    CURRENT = "current"
    OUTDATED = "outdated"
    SOURCE_REMOVED = "source_removed"


class CompanyAddOutcome(StrEnum):
    """Per-item result of adding companies to a project."""

    ADDED = "added"
    ALREADY_PRESENT = "already_present"
    NOT_FOUND = "not_found"
    INVALID = "invalid"


class ProjectDeletionState(StrEnum):
    """Progress of an accepted project deletion."""

    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class WarningCode(StrEnum):
    """Category of a non-fatal diagnostic attached to a published payload.

    A warning explains an incompleteness; it never turns into a value. A client
    that does not know a code still shows its message rather than dropping it.
    """

    UNSPECIFIED = "unspecified"
    """A diagnostic carried over from a lower layer that has no category yet."""

    SOURCE_MISSING = "source_missing"
    """The source did not carry the field or section at all."""

    PARSE_FAILED = "parse_failed"
    """The source carried something that could not be read as its type."""

    PARTIAL_DATA = "partial_data"
    """Part of the requested result could not be built."""

    UNKNOWN_ENUM_VALUE = "unknown_enum_value"
    """A raw external token was kept as is because it has no confirmed meaning."""

    PRECISION_REDUCED = "precision_reduced"
    """A value was rounded, truncated or narrowed for presentation."""

    STALE_SNAPSHOT = "stale_snapshot"
    """The snapshot the answer was read from is old enough to matter."""

    PERIOD_MISMATCH = "period_mismatch"
    """The compared periods are not adjacent or not the same across companies."""

    PERIOD_AMBIGUOUS = "period_ambiguous"
    """More than one source record claims the same period."""

    AGGREGATE_MISMATCH = "aggregate_mismatch"
    """Two reported aggregates of the same facts disagree; neither is corrected."""

    INCOMPLETE_TOTAL = "incomplete_total"
    """The known part of a total is a lower bound, not the total."""

    EMPTY_NOT_CONFIRMED = "empty_not_confirmed"
    """An empty container was returned and does not prove that nothing exists."""

    NOT_COMPARABLE = "not_comparable"
    """Values could not be put side by side without changing their meaning."""

    RESULT_TRUNCATED = "result_truncated"
    """The response hit a server size or record limit and is continued elsewhere."""
