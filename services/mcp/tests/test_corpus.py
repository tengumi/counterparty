"""Read-only sweep of the approved imported corpus; this module performs no setup writes."""

import os
from collections.abc import Mapping
from typing import Any

import pytest
from counterparty_contracts import ReportSectionEnvelope, ReportSectionName
from counterparty_storage.reports.models import ReportSnapshot
from fastmcp import Client
from pydantic import SecretStr
from sqlalchemy import select
from test_app import http_transport

from counterparty_mcp.app import create_app
from counterparty_mcp.config import Settings
from counterparty_mcp.database import PostgreSQLReportReader


def _check_refs(value: Any, raw: Mapping[str, Any], report_id: str) -> int:
    """Resolve every published evidence id through its pinned original JSON pointer."""
    count = 0
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence_refs":
                for ref in item:
                    prefix = f"report:{report_id}:"
                    assert ref.startswith(prefix)
                    current: Any = raw
                    for token in ref.removeprefix(prefix).removeprefix("/").split("/"):
                        token = token.replace("~1", "/").replace("~0", "~")
                        current = (
                            current[int(token)] if isinstance(current, list) else current[token]
                        )
                    count += 1
            else:
                count += _check_refs(item, raw, report_id)
    elif isinstance(value, list):
        for item in value:
            count += _check_refs(item, raw, report_id)
    return count


async def test_representative_sections_of_approved_imported_corpus(settings: Settings) -> None:
    """Exercise all 17 schemas and grounded refs through authenticated MCP HTTP calls."""
    url = os.environ.get("MCP_CORPUS_DATABASE_URL")
    if not url:
        pytest.skip("MCP_CORPUS_DATABASE_URL missing; imported-corpus sweep not executed")
    db_settings = settings.model_copy(update={"database_url": SecretStr(url)})
    reader = PostgreSQLReportReader(db_settings)
    async with reader.read_session() as session:
        snapshots = (
            await session.execute(
                select(ReportSnapshot.id, ReportSnapshot.raw_jsonb).order_by(ReportSnapshot.id)
            )
        ).all()
    assert len(snapshots) >= 100
    selected = {}
    for key in (
        "licenses",
        "inspections",
        "procurements",
        "executionProceedings",
        "relatedCompanies",
    ):
        richest = max(
            snapshots,
            key=lambda item: len(item[1].get(key, [])) if isinstance(item[1].get(key), list) else 0,
        )
        selected[richest[0]] = richest
    for index in (0, 25, 50, 75, 99):
        if len(selected) >= 5:
            break
        selected[snapshots[index][0]] = snapshots[index]
    application = create_app(db_settings, reader=reader)
    inspected_refs = 0
    errors: list[str] = []
    async with (
        application.router.lifespan_context(application),
        Client(http_transport(application)) as client,
    ):
        for report_id, raw in selected.values():
            for section in ReportSectionName:
                arguments = {"report_id": str(report_id), "section": section.value, "limit": 100}
                while True:
                    result = await client.call_tool("get_report_section", arguments)
                    assert not result.is_error and result.structured_content is not None
                    envelope = ReportSectionEnvelope.model_validate(result.structured_content)
                    if envelope.data is None:
                        errors.append(f"{report_id}/{section}: {envelope.errors}")
                        break
                    data = envelope.data
                    if data.availability == "invalid":
                        errors.append(f"{report_id}/{section}: invalid projection")
                    if data.availability == "available" and not data.records and not data.facts:
                        errors.append(f"{report_id}/{section}: available without content")
                    inspected_refs += _check_refs(data.model_dump(mode="json"), raw, str(report_id))
                    if not data.page.has_more:
                        break
                    assert data.page.next_cursor is not None
                    arguments["cursor"] = data.page.next_cursor
    assert not errors, "\n".join(errors[:20])
    assert inspected_refs > 100
    print(
        f"MCP corpus: {len(selected)} snapshots, {len(ReportSectionName)} sections each, "
        f"{inspected_refs} evidence refs resolved"
    )
    assert application.state.resources.closed is True
