"""Bounded report reads, safe business outcomes and payload-free telemetry."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import monotonic

from counterparty_contracts import (
    Availability,
    CompanyOverview,
    CompanyOverviewEnvelope,
    ContractWarning,
    ErrorCode,
    GetCompanyOverviewInput,
    GetReportSectionInput,
    McpEnvelope,
    McpStatus,
    ReportSection,
    ReportSectionEnvelope,
    ToolError,
    WarningCode,
)
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .config import Settings
from .reader import ReportReader

_LOG = logging.getLogger(__name__)
_RULE_VERSION = "mcp-read-v1"


class ServiceResources:
    """Own a bounded reader and close it when the HTTP application stops."""

    def __init__(self, settings: Settings, reader: ReportReader | None = None) -> None:
        """Bind dependencies without opening the database during import."""
        self.settings = settings
        self.reader = reader
        self.closed = False
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_reads)

    async def aclose(self) -> None:
        """Dispose the owned reader once, including during failed requests."""
        if not self.closed:
            self.closed = True
            if self.reader is not None:
                await self.reader.aclose()

    async def _read[DataT](
        self, operation: Callable[[], Awaitable[DataT | None]]
    ) -> tuple[DataT | None, ToolError | None]:
        try:
            async with asyncio.timeout(self.settings.read_timeout_seconds), self._semaphore:
                result = await operation()
            if result is None:
                return None, ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message="The requested imported report was not found; no external search ran.",
                )
            return result, None
        except TimeoutError:
            return None, ToolError(
                code=ErrorCode.TIMEOUT, message="Report read timed out.", retryable=True
            )
        except ValidationError:
            return None, ToolError(
                code=ErrorCode.PARSE_FAILED,
                message="Stored report data could not be projected into the report contract.",
            )
        except ValueError:
            return None, ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message="The cursor is invalid or belongs to another report, section or filter.",
            )
        except SQLAlchemyError:
            return None, ToolError(
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="The imported reports store is unavailable.",
                retryable=True,
            )

    def _unavailable(self) -> ToolError:
        return ToolError(
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The imported reports store is not configured.",
            retryable=True,
        )

    async def overview(self, request: GetCompanyOverviewInput) -> CompanyOverviewEnvelope:
        """Publish the shared projection, never a placeholder company."""
        started = monotonic()
        data: CompanyOverview | None = None
        error = self._unavailable() if self.reader is None else None
        if self.reader is not None:
            data, error = await self._read(lambda: self._overview(request))
        if error is not None:
            result = CompanyOverviewEnvelope(
                status=_error_status(error), errors=[error], rule_version=_RULE_VERSION
            )
        else:
            assert data is not None
            result = CompanyOverviewEnvelope(
                status=McpStatus.PARTIAL if data.warnings else McpStatus.OK,
                data=data,
                warnings=data.warnings,
                source_report_ids=[data.report.id],
                rule_version=data.rule_version,
            )
        if _size(result) > self.settings.max_response_bytes:
            result = CompanyOverviewEnvelope(
                status=McpStatus.UNAVAILABLE, errors=[_size_error()], rule_version=_RULE_VERSION
            )
        _log("get_company_overview", started, result)
        return result

    async def _overview(self, request: GetCompanyOverviewInput) -> CompanyOverview | None:
        assert self.reader is not None
        return await self.reader.overview(request)

    async def section(self, request: GetReportSectionInput) -> ReportSectionEnvelope:
        """Reduce pages at record boundaries when a byte budget is exhausted."""
        started = monotonic()
        if self.reader is None:
            result = ReportSectionEnvelope(
                status=McpStatus.UNAVAILABLE,
                errors=[self._unavailable()],
                rule_version=_RULE_VERSION,
            )
        else:
            data, error = await self._read(lambda: self._bounded_section(request))
            if error is not None:
                result = ReportSectionEnvelope(
                    status=_error_status(error), errors=[error], rule_version=_RULE_VERSION
                )
            elif data is None:
                raise AssertionError("a successful section read must carry data")
            else:
                result = _section_envelope(data)
                if _size(result) > self.settings.max_response_bytes:
                    result = ReportSectionEnvelope(
                        status=McpStatus.UNAVAILABLE,
                        errors=[_size_error()],
                        rule_version=data.rule_version,
                    )
        _log("get_report_section", started, result)
        return result

    async def _bounded_section(self, request: GetReportSectionInput) -> ReportSection | None:
        assert self.reader is not None
        current = request
        while True:
            data = await self.reader.section(current)
            if data is None or _size(_section_envelope(data)) <= self.settings.max_response_bytes:
                return data
            if current.limit == 1 or len(data.records) <= 1:
                return data
            current = current.model_copy(update={"limit": max(1, current.limit // 2)})


def _error_status(error: ToolError) -> McpStatus:
    return McpStatus.NOT_FOUND if error.code is ErrorCode.NOT_FOUND else McpStatus.UNAVAILABLE


def _size_error() -> ToolError:
    return ToolError(
        code=ErrorCode.LIMIT_EXCEEDED,
        message="The result exceeds the response budget. Narrow the section filters or limit.",
    )


def _section_envelope(data: ReportSection) -> ReportSectionEnvelope:
    warnings = list(data.warnings)
    if data.availability is not Availability.AVAILABLE and not warnings:
        warnings.append(
            ContractWarning(
                code=WarningCode.PARTIAL_DATA,
                message=f"Section availability is {data.availability.value}; this is not no risk.",
            )
        )
    if data.page.has_more and not any(w.code is WarningCode.RESULT_TRUNCATED for w in warnings):
        warnings.append(
            ContractWarning(
                code=WarningCode.RESULT_TRUNCATED,
                message="More records are available. Continue with data.page.next_cursor.",
            )
        )
    return ReportSectionEnvelope(
        status=McpStatus.PARTIAL if warnings else McpStatus.OK,
        data=data,
        warnings=warnings,
        source_report_ids=[data.report_id],
        rule_version=data.rule_version,
    )


def _size[DataT](envelope: McpEnvelope[DataT]) -> int:
    return len(envelope.model_dump_json().encode("utf-8"))


def _log[DataT](name: str, started: float, result: McpEnvelope[DataT]) -> None:
    _LOG.info(
        "report_tool name=%s status=%s latency_ms=%.2f bytes=%s",
        name,
        result.status,
        (monotonic() - started) * 1000,
        _size(result),
    )
