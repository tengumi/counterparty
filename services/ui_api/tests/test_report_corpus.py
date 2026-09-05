"""Optional read-only acceptance over an already imported report corpus."""

import os
from uuid import uuid4

import pytest
from counterparty_contracts import GetReportSectionInput, ReportId, ReportSectionName
from counterparty_domain.report_evidence import _references
from counterparty_domain.report_reads import (
    _MISSING,
    _pointer,
    build_company_overview,
    resolve_report_evidence_id,
)
from counterparty_domain.report_sections import build_report_section
from counterparty_storage import AsyncUnitOfWork, TenantScope
from counterparty_storage.reports.models import ReportSnapshot
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from counterparty_ui_api.report_loader import load_report_data


async def test_imported_corpus_has_typed_sections_and_existing_evidence() -> None:
    """Every available source ref resolves in place; no corpus rows are modified."""
    url = os.environ.get("COUNTERPARTY_CORPUS_DATABASE_URL")
    if not url:
        pytest.skip("COUNTERPARTY_CORPUS_DATABASE_URL is not set; corpus smoke was not run")
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine)() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            ids = list((await session.scalars(select(ReportSnapshot.id))).all())
            assert ids, "the acceptance corpus must contain imported snapshots"
            uow = AsyncUnitOfWork(session, TenantScope(tenant_id=uuid4(), actor_user_id=uuid4()))
            for data in await load_report_data(uow, ids):
                outputs = [build_company_overview(data).model_dump(mode="json")]
                for section in ReportSectionName:
                    request = GetReportSectionInput(
                        report_id=ReportId(data.report_id), section=section, limit=100
                    )
                    while True:
                        result = build_report_section(data, request)
                        assert result.availability.value != "invalid", (data.report_id, section)
                        outputs.append(result.model_dump(mode="json"))
                        if result.page.next_cursor is None:
                            break
                        request = request.model_copy(update={"cursor": result.page.next_cursor})
                for output in outputs:
                    for ref, _state in _references(output):
                        locator = resolve_report_evidence_id(ref)
                        assert locator is not None, ref
                        assert locator[0] == data.report_id
                        assert _pointer(data.raw, locator[1]) is not _MISSING, ref
    finally:
        await engine.dispose()
