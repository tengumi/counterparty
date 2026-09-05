"""How the UI backend refuses a request.

Every refusal leaves as the shared :class:`~counterparty_contracts.Error`: a
stable code, a safe sentence and the ``request_id`` that ties it to the server
log. No traceback, SQL, storage key or internal path is ever part of it.

A resource of another tenant is answered ``not_found`` rather than
``forbidden``, so a probe cannot learn that a project exists by being denied it.
"""

from typing import Any

from counterparty_contracts import Error, ErrorCode
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

__all__ = ["ApiError", "install_error_handlers", "request_id_of"]

_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.UNAUTHORIZED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.LIMIT_EXCEEDED: status.HTTP_409_CONFLICT,
    ErrorCode.SOURCE_MISSING: status.HTTP_404_NOT_FOUND,
    ErrorCode.PARSE_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.DEPENDENCY_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
    ErrorCode.CANCELLED: status.HTTP_409_CONFLICT,
    ErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


class ApiError(Exception):
    """A refusal that already knows its public shape."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record the public code, message and safe details of the refusal."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details

    @property
    def status_code(self) -> int:
        """HTTP status this error is reported with."""
        return _STATUS_BY_CODE[self.code]

    def to_contract(self, request_id: str) -> Error:
        """Render the refusal as the shared public error DTO."""
        return Error(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            request_id=request_id,
            details=self.details,
        )


def request_id_of(request: Request) -> str:
    """Return the correlation id assigned to this request."""
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else "unknown"


def install_error_handlers(app: FastAPI) -> None:
    """Make every refusal of this application leave as an ``Error`` DTO."""

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        """Render a deliberate refusal."""
        return JSONResponse(
            status_code=error.status_code,
            content=error.to_contract(request_id_of(request)).model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        """Report an invalid request without echoing what was sent.

        Only the field locations and the validation messages are returned. The
        submitted values are not: a rejected body may contain a credential.
        """
        invalid_fields = [
            {"loc": [str(part) for part in item.get("loc", ())], "message": str(item.get("msg"))}
            for item in error.errors()
        ]
        refusal = ApiError(
            ErrorCode.VALIDATION_ERROR,
            "the request did not pass validation",
            details={"invalid_fields": invalid_fields},
        )
        return JSONResponse(
            status_code=refusal.status_code,
            content=refusal.to_contract(request_id_of(request)).model_dump(mode="json"),
        )
