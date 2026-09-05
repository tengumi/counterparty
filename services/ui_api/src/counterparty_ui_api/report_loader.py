"""Load normalized report rows for the shared pure read projection."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from counterparty_contracts import ContractWarning, WarningCode
from counterparty_domain.report_reads import ReportReadData
from sqlalchemy import inspect

from .dependencies import TenantWork


def _columns(row: Any) -> dict[str, Any]:
    """Copy loaded scalar columns without relationships or database access."""
    return (
        {}
        if row is None
        else {
            attribute.key: getattr(row, attribute.key)
            for attribute in inspect(type(row)).column_attrs
        }
    )


async def load_report_data(uow: TenantWork, report_ids: Sequence[UUID]) -> list[ReportReadData]:
    """Read reports in a fixed number of queries, preserving requested order."""
    return [
        ReportReadData(
            report_id=bundle.snapshot.id,
            company_id=bundle.company.id,
            inn=bundle.company.inn,
            ogrn=bundle.company.ogrn,
            source_report_at=bundle.snapshot.source_report_at,
            ingested_at=bundle.snapshot.ingested_at,
            raw=bundle.snapshot.raw_jsonb,
            ingestion_status=bundle.snapshot.ingestion_status.value,
            profile=_columns(bundle.profile),
            status=_columns(bundle.status),
            zsk=_columns(bundle.zsk),
            financials=[_columns(row) for row in bundle.financials],
            sections={row.section: _columns(row) for row in bundle.sections},
            warnings=[
                ContractWarning(
                    code=WarningCode(row.code)
                    if row.code in WarningCode._value2member_map_
                    else WarningCode.UNSPECIFIED,
                    message=row.message,
                    source_path=row.source_path,
                )
                for row in bundle.warnings
            ],
        )
        for bundle in await uow.report_snapshots.get_read_bundles(report_ids)
    ]
