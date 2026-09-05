"""Live parity of MCP compare_companies with the UI backend comparison.

The two surfaces are supposed to answer with the same numbers on the same
snapshots. That is an architectural intention until something checks it, so this
module checks it against two running processes over HTTP and compares the
answers cell by cell.

Nothing here imports the UI backend. MCP must not depend on it, and a parity
check that imported it would prove only that one function returns what it
returns. Both services are addressed exactly as their real clients address them:
the UI backend through its REST session and project, the MCP through the standard
Streamable HTTP client with a service credential.

The check is skipped when the stack is not running, and it never writes to the
reports schema: it creates one demo project in the workspace, which is what the
UI backend requires before it will compare anything.
"""

import os
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

UI_API_URL = os.environ.get("MCP_PARITY_UI_API_URL")
MCP_URL = os.environ.get("MCP_PARITY_MCP_URL")
TOKEN = os.environ.get("MCP_PARITY_TOKEN")
INNS = [inn for inn in os.environ.get("MCP_PARITY_INNS", "1684017097,7449088645").split(",") if inn]
CRITERIA = ["status", "bank_risk", "financials", "proceedings", "arbitration"]


def _comparable(row: dict[str, Any]) -> dict[str, Any]:
    """Keep the parts of a row both surfaces claim to answer identically."""
    return {
        "company": row["company"],
        "report": row["report"],
        "status": row["status"],
        "cells": row["cells"],
        "warnings": row["warnings"],
    }


@pytest.mark.parametrize("year_policy", ["latest_available", "common_latest"])
async def test_mcp_and_ui_api_compare_the_same_reports_identically(year_policy: str) -> None:
    """The same snapshots and criteria produce the same rows, values and periods."""
    if not (UI_API_URL and MCP_URL and TOKEN):
        pytest.skip("MCP_PARITY_UI_API_URL, _MCP_URL and _TOKEN missing; live parity not executed")

    async with httpx.AsyncClient(base_url=UI_API_URL, timeout=30.0) as ui:
        session = await ui.post("/api/v1/auth/session", json={"login": "demo-analyst"})
        assert session.status_code == 201, session.text
        project = await ui.post(
            "/api/v1/projects",
            json={"title": "MCP parity", "client_request_id": str(uuid4())},
        )
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]
        added = await ui.post(
            f"/api/v1/projects/{project_id}/companies",
            json={"items": [{"inn": inn} for inn in INNS], "expected_context_version": 0},
        )
        assert added.status_code == 200, added.text
        companies = added.json()["companies"]
        assert len(companies) == len(INNS), added.text
        report_ids = [company["report_id"] for company in companies]
        comparison = await ui.post(
            f"/api/v1/projects/{project_id}/comparisons",
            json={"report_ids": report_ids, "criteria": CRITERIA, "year_policy": year_policy},
        )
        assert comparison.status_code == 200, comparison.text
        ui_payload = comparison.json()

    transport = StreamableHttpTransport(f"{MCP_URL.rstrip('/')}/mcp", auth=TOKEN)
    async with Client(transport) as client:
        result = await client.call_tool(
            "compare_companies",
            {"report_ids": report_ids, "criteria": CRITERIA, "year_policy": year_policy},
        )
    assert result.structured_content is not None
    mcp_payload = result.structured_content["data"]

    assert [_comparable(row) for row in mcp_payload["rows"]] == [
        _comparable(row) for row in ui_payload["rows"]
    ]
    assert mcp_payload["warnings"] == ui_payload["warnings"]
    assert mcp_payload["rule_version"] == ui_payload["rule_version"]
    assert mcp_payload["year_policy"] == ui_payload["year_policy"]
    assert mcp_payload["report_ids"] == ui_payload["report_ids"]
    # The MCP answer is report facts only; the workspace extension is absent.
    assert "project_id" not in mcp_payload
    assert "proposal_facts" not in mcp_payload
    assert mcp_payload["rows"], "the parity check must compare a non-empty result"
