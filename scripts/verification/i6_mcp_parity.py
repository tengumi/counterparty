"""Independent read-only parity of UI and MCP projections over the imported corpus.

Run from services/mcp using its uv environment; provide MCP_CORPUS_DATABASE_URL.
No test fixture, schema setup or source data writes are performed.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/ui_api/src"))

from counterparty_contracts import (
    GetCompanyOverviewInput,
    GetReportSectionInput,
    ReportSectionName,
)  # noqa: E402
from counterparty_domain.report_reads import build_company_overview  # noqa: E402
from counterparty_domain.report_sections import build_report_section  # noqa: E402
from counterparty_mcp.config import Settings  # noqa: E402
from counterparty_mcp.database import PostgreSQLReportReader  # noqa: E402
from counterparty_mcp.runtime import ServiceResources  # noqa: E402
from counterparty_storage.reports.models import ReportSnapshot  # noqa: E402
from counterparty_storage.repositories.reports import ReportSnapshotReadRepository  # noqa: E402
from counterparty_ui_api.report_loader import load_report_data  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from sqlalchemy import select  # noqa: E402


async def main() -> None:
    """Compare exact overview/section DTOs, using only the reports reader role."""
    settings = Settings(database_url=SecretStr(os.environ["MCP_CORPUS_DATABASE_URL"]))
    reader = PostgreSQLReportReader(settings)
    resources = ServiceResources(settings, reader)
    overview_count = section_count = 0
    try:
        async with reader.read_session() as session:
            ids = list(
                (
                    await session.scalars(
                        select(ReportSnapshot.id).order_by(ReportSnapshot.id)
                    )
                )
            )
            assert len(ids) >= 100
            uow = SimpleNamespace(
                report_snapshots=ReportSnapshotReadRepository(session)
            )
            ui_data = await load_report_data(uow, ids)
        assert [item.report_id for item in ui_data] == ids
        for data in ui_data:
            expected = build_company_overview(data)
            actual = await resources.overview(
                GetCompanyOverviewInput(report_id=data.report_id)
            )
            assert actual.data == expected, f"overview differs: {data.report_id}"
            overview_count += 1
        for data in [ui_data[index] for index in (0, 25, 50, 75, 99)]:
            for section in ReportSectionName:
                request = GetReportSectionInput(
                    report_id=data.report_id, section=section, limit=20
                )
                while True:
                    actual = await resources.section(request)
                    assert actual.data is not None, (
                        data.report_id,
                        section,
                        actual.errors,
                    )
                    # MCP may reduce the limit to fit its configured byte budget.
                    request = request.model_copy(
                        update={"limit": actual.data.page.limit}
                    )
                    expected = build_report_section(data, request)
                    assert actual.data == expected, (
                        f"section differs: {data.report_id}/{section}"
                    )
                    assert (
                        len(actual.model_dump_json().encode())
                        <= settings.max_response_bytes
                    )
                    section_count += 1
                    if not actual.data.page.has_more:
                        break
                    request = request.model_copy(
                        update={"cursor": actual.data.page.next_cursor}
                    )
        print(
            json.dumps(
                {
                    "overviews": overview_count,
                    "section_pages": section_count,
                    "verdict": "pass",
                    "mode": "read-only UI-loader/MCP DTO parity",
                }
            )
        )
    finally:
        await resources.aclose()
    assert reader.engine.pool.checkedout() == 0


if __name__ == "__main__":
    asyncio.run(main())
