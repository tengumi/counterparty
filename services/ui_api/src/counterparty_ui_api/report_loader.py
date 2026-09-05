"""Load normalized report rows for the shared pure read projection."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from counterparty_contracts import ContractWarning, WarningCode
from counterparty_domain.report_reads import ReportReadData
from counterparty_storage.reports.models import (
    Company,
    CompanyProfile,
    CompanyStatus,
    FinancialStatement,
    ImportWarning,
    ReportSnapshot,
    SectionAvailability,
    ZskAssessment,
)
from sqlalchemy import inspect, select

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
    ids = list(dict.fromkeys(report_ids))
    if not ids:
        return []
    base_rows = (
        await uow.session.execute(
            select(ReportSnapshot, Company, CompanyProfile, CompanyStatus, ZskAssessment)
            .join(Company, Company.id == ReportSnapshot.company_id)
            .outerjoin(CompanyProfile, CompanyProfile.report_id == ReportSnapshot.id)
            .outerjoin(CompanyStatus, CompanyStatus.report_id == ReportSnapshot.id)
            .outerjoin(ZskAssessment, ZskAssessment.report_id == ReportSnapshot.id)
            .where(ReportSnapshot.id.in_(ids))
        )
    ).all()
    sections_by_report: dict[UUID, dict[str, SectionAvailability]] = {item: {} for item in ids}
    for section_entry in (
        await uow.session.execute(
            select(SectionAvailability).where(SectionAvailability.report_id.in_(ids))
        )
    ).scalars():
        sections_by_report[section_entry.report_id][section_entry.section] = section_entry
    finances_by_report: dict[UUID, list[FinancialStatement]] = {item: [] for item in ids}
    for financial_entry in (
        await uow.session.execute(
            select(FinancialStatement)
            .where(FinancialStatement.report_id.in_(ids))
            .order_by(
                FinancialStatement.report_id, FinancialStatement.year, FinancialStatement.ordinal
            )
        )
    ).scalars():
        finances_by_report[financial_entry.report_id].append(financial_entry)
    warnings_by_report: dict[UUID, list[ImportWarning]] = {item: [] for item in ids}
    for warning_entry in (
        await uow.session.execute(
            select(ImportWarning)
            .where(ImportWarning.report_id.in_(ids))
            .order_by(ImportWarning.report_id, ImportWarning.created_at, ImportWarning.id)
        )
    ).scalars():
        if warning_entry.report_id is not None:
            warnings_by_report[warning_entry.report_id].append(warning_entry)

    by_id = {
        snapshot.id: ReportReadData(
            report_id=snapshot.id,
            company_id=company.id,
            inn=company.inn,
            ogrn=company.ogrn,
            source_report_at=snapshot.source_report_at,
            ingested_at=snapshot.ingested_at,
            raw=snapshot.raw_jsonb,
            ingestion_status=snapshot.ingestion_status.value,
            profile=_columns(profile),
            status=_columns(status),
            zsk=_columns(zsk),
            financials=[_columns(row) for row in finances_by_report[snapshot.id]],
            sections={key: _columns(row) for key, row in sections_by_report[snapshot.id].items()},
            warnings=[
                ContractWarning(
                    code=WarningCode(row.code)
                    if row.code in WarningCode._value2member_map_
                    else WarningCode.UNSPECIFIED,
                    message=row.message,
                    source_path=row.source_path,
                )
                for row in warnings_by_report[snapshot.id]
            ],
        )
        for snapshot, company, profile, status, zsk in base_rows
    }
    return [by_id[report_id] for report_id in ids if report_id in by_id]
