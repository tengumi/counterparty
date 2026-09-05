"""Error, concurrency, cancellation and byte-budget behaviour at the tool boundary."""

import asyncio

import pytest
from conftest import REPORT_ID, FixtureReader
from counterparty_contracts import GetCompanyOverviewInput, GetReportSectionInput, ReportSectionName
from sqlalchemy.exc import OperationalError

from counterparty_mcp.config import Settings
from counterparty_mcp.runtime import ServiceResources


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), "timeout"),
        (
            OperationalError("secret SQL", None, Exception("credential secret")),
            "dependency_unavailable",
        ),
        (ValueError("tampered cursor"), "validation_error"),
    ],
)
async def test_failure_outcomes_do_not_expose_internal_errors(
    reader: FixtureReader, settings: Settings, error: Exception, expected: str
) -> None:
    """Expected errors retain stable categories without SQL or exception details."""
    reader.error = error
    result = await ServiceResources(settings, reader).overview(
        GetCompanyOverviewInput(inn="7449088645")
    )
    assert result.errors[0].code == expected
    assert "secret" not in result.model_dump_json()
    assert result.data is None


async def test_timeout_includes_waiting_for_concurrency_slot(reader: FixtureReader) -> None:
    """Queued reads do not wait indefinitely behind slow work."""
    reader.delay = 0.1
    resources = ServiceResources(
        Settings(read_timeout_seconds=0.02, max_concurrent_reads=1), reader
    )
    results = await asyncio.gather(
        *[resources.overview(GetCompanyOverviewInput(inn="7449088645")) for _ in range(3)]
    )
    assert all(result.errors[0].code == "timeout" for result in results)
    assert reader.max_active_reads == 1
    assert reader.active_reads == 0


async def test_cancellation_releases_capacity(reader: FixtureReader, settings: Settings) -> None:
    """Client cancellation is propagated and cannot retain a read slot."""
    reader.delay = 10
    resources = ServiceResources(settings, reader)
    task = asyncio.create_task(resources.overview(GetCompanyOverviewInput(inn="7449088645")))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert reader.active_reads == 0
    reader.delay = 0
    assert not (await resources.overview(GetCompanyOverviewInput(inn="7449088645"))).errors


async def test_byte_budget_reduces_page_without_losing_continuation(reader: FixtureReader) -> None:
    """Large records shrink the page at record boundaries, never inside JSON."""
    reader.record_text = "z" * 1000
    resources = ServiceResources(Settings(max_response_bytes=4096), reader)
    result = await resources.section(
        GetReportSectionInput(report_id=REPORT_ID, section=ReportSectionName.ACTIVITIES)
    )
    assert len(result.model_dump_json().encode()) <= 4096
    assert result.data is not None
    assert 1 <= len(result.data.records) < 20
    assert result.data.page.next_cursor == str(len(result.data.records))
    assert any(warning.code == "result_truncated" for warning in result.warnings)
    assert all(
        record.description == reader.record_text
        for record in result.data.records
        if record.kind == "activity"
    )


async def test_single_oversized_record_has_safe_limit_error(reader: FixtureReader) -> None:
    """An indivisible record larger than the budget is never silently clipped."""
    reader.record_text = "z" * 5000
    result = await ServiceResources(Settings(max_response_bytes=4096), reader).section(
        GetReportSectionInput(report_id=REPORT_ID, section=ReportSectionName.ACTIVITIES)
    )
    assert result.data is None
    assert result.errors[0].code == "limit_exceeded"
    assert len(result.model_dump_json()) < 4096
