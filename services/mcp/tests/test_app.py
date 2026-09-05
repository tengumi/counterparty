"""Standard Streamable HTTP MCP discovery, authentication and async cleanup."""

from typing import Any

import httpx
import pytest
from conftest import ABSENT_REPORT_ID, PEER_REPORT_ID, REPORT_ID, TEST_TOKEN, FixtureReader
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.utilities.logging import get_logger

from counterparty_mcp.app import create_app
from counterparty_mcp.config import Settings
from counterparty_mcp.runtime import ServiceResources


def http_transport(application: FastAPI) -> StreamableHttpTransport:
    """Use the standard client with an ASGI socket substitute, not protocol stubs."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        follow_redirects: bool = True,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=follow_redirects,
        )

    return StreamableHttpTransport("http://test/mcp", auth=TEST_TOKEN, httpx_client_factory=factory)


async def test_standard_http_discovery_calls_and_cleanup(
    settings: Settings, reader: FixtureReader
) -> None:
    """A real Streamable HTTP client discovers schemas, calls tools and closes."""
    application = create_app(settings, reader=reader)
    async with (
        application.router.lifespan_context(application),
        Client(http_transport(application)) as client,
    ):
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            "get_company_overview",
            "get_report_section",
            "compare_companies",
        }
        for tool in tools:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.openWorldHint is False
            assert tool.outputSchema is not None
        result = await client.call_tool("get_company_overview", {"inn": "7449088645"})
        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["source_report_ids"] == [str(REPORT_ID)]
        assert result.structured_content["data"]["company"]["inn"] == "7449088645"
        section = await client.call_tool(
            "get_report_section",
            {"report_id": str(REPORT_ID), "section": "activities", "limit": 100},
        )
        assert section.structured_content is not None
        data = section.structured_content
        assert data["status"] == "partial"
        assert len(data["data"]["records"]) == 100
        assert data["data"]["page"]["has_more"] is True
        assert data["warnings"][0]["code"] == "result_truncated"
        assert reader.closed is False
    assert reader.closed is True
    resources: ServiceResources = application.state.resources
    assert resources.closed is True


@pytest.mark.parametrize("token", [None, "wrong-synthetic-token"])
async def test_http_rejects_missing_and_invalid_credentials(
    settings: Settings, reader: FixtureReader, token: str | None
) -> None:
    """Credentials are enforced before parsing or invoking a report tool."""
    application = create_app(settings, reader=reader)
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client,
    ):
        response = await client.post("/mcp", json={}, headers=headers)
        assert response.status_code == 401
        assert "Bearer" in response.headers["www-authenticate"]
        health = await client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "service": "mcp"}
    assert reader.calls == 0


async def test_no_configured_digest_never_opens_access(reader: FixtureReader) -> None:
    """There is no silent no-auth mode when an environment variable is absent."""
    application = create_app(Settings(), reader=reader)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/mcp", json={}, headers={"Authorization": f"Bearer {TEST_TOKEN}"}
        )
    assert response.status_code == 401
    assert reader.calls == 0


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_company_overview", {}),
        ("get_company_overview", {"inn": "7449088645", "report_id": str(REPORT_ID)}),
        (
            "get_report_section",
            {"report_id": str(REPORT_ID), "section": "licenses", "filters": {"active": True}},
        ),
    ],
)
async def test_business_input_errors_are_typed(
    settings: Settings, reader: FixtureReader, name: str, arguments: dict[str, Any]
) -> None:
    """Valid MCP calls with contradictory business inputs have shared errors."""
    application = create_app(settings, reader=reader)
    async with Client(application.state.mcp) as client:
        result = await client.call_tool(name, arguments)
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["errors"][0]["code"] == "validation_error"
    assert reader.calls == 0


@pytest.mark.parametrize(
    "arguments",
    [
        {"section": "workspace"},
        {"section": "activities", "filters": {"sql": "select * from workspace.projects"}},
        {"section": "activities", "limit": 101},
        {"section": "activities", "limit": 0},
        {"section": "activities", "cursor": "x" * 4097},
    ],
)
async def test_unknown_fields_sections_and_limits_are_protocol_validation_errors(
    settings: Settings, reader: FixtureReader, arguments: dict[str, Any]
) -> None:
    """Pydantic schemas enforce the whitelist before report code runs."""
    application = create_app(settings, reader=reader)
    async with Client(application.state.mcp) as client:
        result = await client.call_tool(
            "get_report_section", {"report_id": str(REPORT_ID), **arguments}, raise_on_error=False
        )
    assert result.is_error is True
    assert reader.calls == 0


async def test_unknown_inn_and_unconfigured_store_are_distinct(settings: Settings) -> None:
    """Unknown corpus identifiers are not outages or external lookups."""
    for reader, expected in [(FixtureReader(), "not_found"), (None, "dependency_unavailable")]:
        application = create_app(settings, reader=reader)
        async with Client(application.state.mcp) as client:
            result = await client.call_tool("get_company_overview", {"inn": "0000000000"})
        assert result.structured_content is not None
        assert result.structured_content["errors"][0]["code"] == expected
        assert result.structured_content["data"] is None


async def test_library_validation_diagnostics_do_not_log_input_values(
    reader: FixtureReader,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Even invalid unknown filters cannot place arbitrary sensitive text in logs."""
    application = create_app(settings, reader=reader)
    logger = get_logger("fastmcp.server.server")
    logger.addHandler(caplog.handler)
    try:
        async with Client(application.state.mcp) as client:
            result = await client.call_tool(
                "get_report_section",
                {
                    "report_id": str(REPORT_ID),
                    "section": "activities",
                    "filters": {"secret": "sensitive-input-sentinel"},
                },
                raise_on_error=False,
            )
    finally:
        logger.removeHandler(caplog.handler)
    assert result.is_error
    assert "Report tool argument validation failed" in caplog.text
    assert "sensitive-input-sentinel" not in caplog.text


async def test_compare_companies_places_reports_side_by_side(
    settings: Settings, reader: FixtureReader
) -> None:
    """Two pinned reports produce two rows, no score and no winner."""
    application = create_app(settings, reader=reader)
    async with Client(application.state.mcp) as client:
        result = await client.call_tool(
            "compare_companies",
            {
                "report_ids": [str(REPORT_ID), str(PEER_REPORT_ID)],
                "criteria": ["status", "financials"],
            },
        )
    assert result.structured_content is not None
    payload = result.structured_content
    assert payload["status"] == "ok"
    data = payload["data"]
    assert [row["company"]["inn"] for row in data["rows"]] == ["7449088645", "1684017097"]
    assert {cell["key"] for cell in data["rows"][0]["cells"]} == {"status", "revenue"}
    assert [cell["value"] for cell in data["rows"][1]["cells"] if cell["key"] == "revenue"] == [
        "250"
    ]
    assert "score" not in data and "winner" not in data
    assert all("score" not in row and "winner" not in row for row in data["rows"])
    assert payload["source_report_ids"] == [str(REPORT_ID), str(PEER_REPORT_ID)]


async def test_compare_companies_reports_incomplete_and_missing_reports(
    settings: Settings, reader: FixtureReader
) -> None:
    """Incomplete data and an unknown snapshot are distinct, named gaps."""
    reader.peer_financials_missing = True
    application = create_app(settings, reader=reader)
    async with Client(application.state.mcp) as client:
        incomplete = await client.call_tool(
            "compare_companies",
            {
                "report_ids": [str(REPORT_ID), str(PEER_REPORT_ID)],
                "criteria": ["financials"],
                "year_policy": "common_latest",
            },
        )
        absent = await client.call_tool(
            "compare_companies",
            {
                "report_ids": [str(REPORT_ID), str(ABSENT_REPORT_ID)],
                "criteria": ["status"],
            },
        )
    assert incomplete.structured_content is not None
    assert incomplete.structured_content["status"] == "partial"
    assert incomplete.structured_content["data"]["rows"][1]["status"] == "unavailable"
    assert {warning["code"] for warning in incomplete.structured_content["warnings"]} == {
        "not_comparable"
    }
    assert absent.structured_content is not None
    assert absent.structured_content["status"] == "partial"
    assert len(absent.structured_content["data"]["rows"]) == 1
    assert absent.structured_content["source_report_ids"] == [str(REPORT_ID)]


@pytest.mark.parametrize(
    "arguments",
    [
        {"report_ids": [str(REPORT_ID)], "criteria": ["status"]},
        {"report_ids": [str(REPORT_ID), str(PEER_REPORT_ID)], "criteria": ["revenue_growth"]},
        {"report_ids": [str(REPORT_ID), str(PEER_REPORT_ID)], "criteria": []},
        {
            "report_ids": [str(REPORT_ID), str(PEER_REPORT_ID)],
            "criteria": ["financials"],
            "sort_by": "score",
        },
    ],
)
async def test_compare_companies_rejects_selections_outside_the_whitelist(
    settings: Settings, reader: FixtureReader, arguments: dict[str, Any]
) -> None:
    """Too few reports, unknown criteria and invented ranking inputs are refused."""
    application = create_app(settings, reader=reader)
    async with Client(application.state.mcp) as client:
        result = await client.call_tool("compare_companies", arguments, raise_on_error=False)
    assert result.is_error is True
    assert reader.calls == 0


async def test_compare_companies_refuses_a_duplicated_report(
    settings: Settings, reader: FixtureReader
) -> None:
    """Comparing a report with itself is a typed business error, not a row."""
    application = create_app(settings, reader=reader)
    async with Client(application.state.mcp) as client:
        result = await client.call_tool(
            "compare_companies",
            {"report_ids": [str(REPORT_ID), str(REPORT_ID)], "criteria": ["status"]},
        )
    assert result.structured_content is not None
    assert result.structured_content["errors"][0]["code"] == "validation_error"
    assert reader.calls == 0
