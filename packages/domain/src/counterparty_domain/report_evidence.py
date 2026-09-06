"""Resolve only references issued by deterministic report projections."""

import json
from collections.abc import Iterator, Mapping
from typing import cast

from counterparty_contracts import (
    Availability,
    CompanyId,
    ContractWarning,
    EvidenceKind,
    EvidenceRef,
    FactValue,
    FinancialPeriod,
    GetReportSectionInput,
    ReportEvidence,
    ReportId,
    ReportSectionName,
    WarningCode,
)
from pydantic import BaseModel, JsonValue

from .report_reads import (
    _MISSING,
    ReportReadData,
    _field_availability,
    _pointer,
    build_company_overview,
    resolve_report_evidence_id,
)
from .report_sections import build_report_section

MAX_EVIDENCE_BYTES = 65_536


def _references(value: object) -> Iterator[tuple[str, Availability | None]]:
    if isinstance(value, Mapping):
        availability = value.get("availability")
        state = Availability(availability) if isinstance(availability, str) else None
        for ref in value.get("evidence_refs", []):
            if isinstance(ref, str):
                yield ref, state
        for child in value.values():
            yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def _reference_periods(value: object) -> Iterator[tuple[str, int | str]]:
    """Read periods only from validated facts and financial records with exact refs."""
    if isinstance(value, (FactValue, FinancialPeriod)):
        period = value.period if isinstance(value, FactValue) else value.year
        if period is not None:
            for ref in value.evidence_refs:
                yield ref, period
    if isinstance(value, BaseModel):
        for field in type(value).model_fields:
            yield from _reference_periods(getattr(value, field))
    elif isinstance(value, list):
        for child in value:
            yield from _reference_periods(child)


def build_report_evidence(data: ReportReadData, ref_id: str) -> ReportEvidence | None:
    """Resolve an issued source ref after the caller has authorized its report.

    Unknown or forged paths return None. A legitimate but oversized source
    block raises ValueError, allowing the service to refuse it explicitly.
    """
    locator = resolve_report_evidence_id(ref_id)
    if locator is None or locator[0] != data.report_id or data.ingestion_status == "invalid":
        return None
    overview = build_company_overview(data)
    issued = dict(_references(overview.model_dump(mode="json")))
    periods = dict(_reference_periods(overview))
    # Include all pages: an old reference stays resolvable after navigation to
    # a different page, without trusting a path supplied by the client.
    for section in ReportSectionName:
        request = GetReportSectionInput(
            report_id=ReportId(data.report_id), section=section, limit=100
        )
        while True:
            page = build_report_section(data, request)
            issued.update(_references(page.model_dump(mode="json")))
            periods.update(_reference_periods(page))
            if page.page.next_cursor is None:
                break
            request = request.model_copy(update={"cursor": page.page.next_cursor})
    if ref_id not in issued:
        return None
    path = locator[1]
    value = _pointer(data.raw, path)
    if value is _MISSING:
        return None
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_EVIDENCE_BYTES:
        raise ValueError("source fragment exceeds the evidence response limit")
    availability = issued[ref_id] or _field_availability(data.raw, path, data.invalid_paths)
    warnings = [warning for warning in data.warnings if warning.source_path == path]
    if availability is Availability.PRESENT_EMPTY:
        warnings.append(
            ContractWarning(
                code=WarningCode.EMPTY_NOT_CONFIRMED,
                message="Пустое значение источника не подтверждает отсутствие риска",
                source_path=path,
            )
        )
    return ReportEvidence(
        evidence=EvidenceRef(
            id=ref_id,
            kind=EvidenceKind.REPORT_FIELD,
            report_id=ReportId(data.report_id),
            company_id=CompanyId(data.company_id),
            source_path=path,
            period=periods.get(ref_id),
        ),
        report=data.report,
        availability=availability,
        value=cast(JsonValue, value),
        warnings=warnings,
    )
