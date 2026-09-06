"""Failures the persistence layer reports to its caller.

Each one names a decision the caller has to make. None of them is a generic
"database error": a repository never turns a refused write into a silent
no-op, and never turns a missing row into an empty result that reads as "no
risk".
"""

from uuid import UUID

__all__ = [
    "ContextVersionConflictError",
    "IdempotencyConflictError",
    "NotFoundError",
    "ProjectCompanyLimitError",
    "ProjectDeletedError",
    "StorageError",
]


class StorageError(Exception):
    """Base class for every failure raised by this package."""


class NotFoundError(StorageError):
    """The row does not exist, or it exists outside the caller's scope.

    The two cases are deliberately reported the same way: telling a caller that
    a project exists in another tenant is already a leak.
    """

    def __init__(self, kind: str, identifier: UUID | str) -> None:
        """Name the kind of row and the identifier that was looked up."""
        super().__init__(f"{kind} {identifier} was not found in this scope")
        self.kind = kind
        self.identifier = identifier


class ProjectDeletedError(StorageError):
    """The project is deleted; it accepts no further writes."""

    def __init__(self, project_id: UUID) -> None:
        """Name the deleted project."""
        super().__init__(f"project {project_id} is deleted and accepts no writes")
        self.project_id = project_id


class ContextVersionConflictError(StorageError):
    """Someone else changed the deal context since the caller last read it."""

    def __init__(self, project_id: UUID, expected: int, actual: int) -> None:
        """Report both the expected and the current context version."""
        super().__init__(f"project {project_id} is at context version {actual}, not {expected}")
        self.project_id = project_id
        self.expected = expected
        self.actual = actual


class ProjectCompanyLimitError(StorageError):
    """The project already holds the maximum number of counterparties."""

    def __init__(self, project_id: UUID, limit: int) -> None:
        """Report the project and the limit it reached."""
        super().__init__(f"project {project_id} already holds {limit} companies")
        self.project_id = project_id
        self.limit = limit


class IdempotencyConflictError(StorageError):
    """The request id was already used for a different request payload.

    Replaying the first result would silently discard this request, so the
    caller is told instead.
    """

    def __init__(self, scope: str, client_request_id: UUID) -> None:
        """Name the operation and the reused request id."""
        super().__init__(
            f"request id {client_request_id} was already used for a different {scope} request"
        )
        self.scope = scope
        self.client_request_id = client_request_id
