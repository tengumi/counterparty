"""Pinned report overview and deterministic project comparison endpoints."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Annotated, Any, Final
from uuid import UUID

from counterparty_contracts import (
    SECTION_SOURCE_KEYS,
    Availability,
    BankRiskAssessment,
    CompanyIdentity,
    CompanyOverview,
    CompanyStatusView,
    CompareCompaniesInput,
    ContractWarning,
    DisplayLevel,
    ErrorCode,
    FactValue,
    ProjectComparison,
    ReportId,
    ReportIdentity,
    ReportSectionName,
    SectionAvailabilityView,
    ValueType,
    WarningCode,
    decimal_to_string,
)
from counterparty_contracts import (
    ZskAssessment as ZskAssessmentView,
)
from counterparty_domain import (
    COMPARISON_RULE_VERSION,
    ExecutionProceeding,
    FactSlot,
    build_comparison_rows,
    summarize_proceedings,
)
from counterparty_storage.reports.enums import IngestionStatus, SourceState
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
from fastapi import APIRouter, Path
from sqlalchemy import select

from .dependencies import ScopedProject, TenantWork
from .errors import ApiError

__all__ = ["report_evidence_id", "resolve_report_evidence_id", "router"]

router = APIRouter(prefix="/api/v1", tags=["reports"])

OVERVIEW_RULE_VERSION: Final = "overview/1"
_MISSING = object()
_FINANCIAL_FIELDS: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "proceeds": ("Выручка", ("common", "proceeds")),
    "profit": ("Прибыль", ("common", "profit")),
    "total_assets": ("Активы", ("assets", "totalAssets")),
    "equity": ("Капитал", ("liabilities", "capitals")),
    "cash": ("Денежные средства", ("assets", "currentAssets", "bankroll")),
    "receivables": ("Дебиторская задолженность", ("assets", "currentAssets", "receivables")),
    "accounts_payable": (
        "Кредиторская задолженность",
        ("liabilities", "shortTermLiabilities", "accountsPayable"),
    ),
}


def report_evidence_id(report_id: UUID, source_path: str) -> str:
    """Build the stable opaque id used by report-field facts."""
    return f"report:{report_id}:{source_path}"


def resolve_report_evidence_id(ref_id: str) -> tuple[UUID, str] | None:
    """Decode one id created by :func:`report_evidence_id`.

    This is intentionally strict: an arbitrary string never becomes a source
    locator and can be rejected by the future evidence endpoint.
    """
    prefix, separator, tail = ref_id.partition(":")
    if prefix != "report" or not separator:
        return None
    raw_report_id, separator, source_path = tail.partition(":")
    if not separator or not source_path.startswith("/"):
        return None
    try:
        return UUID(raw_report_id), source_path
    except ValueError:
        return None


def _pointer(payload: Mapping[str, Any], source_path: str) -> object:
    current: object = payload
    for encoded in source_path.removeprefix("/").split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return _MISSING
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return _MISSING
    return current


def _field_availability(
    raw: Mapping[str, Any], source_path: str, invalid_paths: set[str]
) -> Availability:
    if source_path in invalid_paths:
        return Availability.INVALID
    value = _pointer(raw, source_path)
    if value is _MISSING:
        return Availability.MISSING
    if value is None or value == "" or value == [] or value == {}:
        return Availability.PRESENT_EMPTY
    return Availability.AVAILABLE


def _refs(report_id: UUID, path: str, availability: Availability) -> list[str]:
    return [report_evidence_id(report_id, path)] if availability is Availability.AVAILABLE else []


def _usable_availability(value: object | None, availability: Availability) -> Availability:
    """Treat a present raw field with no normalized value as invalid."""
    if value is None and availability is Availability.AVAILABLE:
        return Availability.INVALID
    return availability


def _fact(
    *,
    report_id: UUID,
    raw: Mapping[str, Any],
    invalid_paths: set[str],
    key: str,
    label: str,
    path: str,
    value: Decimal | None,
    period: int,
) -> FactValue:
    availability = _field_availability(raw, path, invalid_paths)
    availability = _usable_availability(value, availability)
    return FactValue(
        key=key,
        label=label,
        value=(
            decimal_to_string(value)
            if value is not None and availability is Availability.AVAILABLE
            else None
        ),
        value_type=ValueType.DECIMAL,
        currency="RUB",
        period=period,
        availability=availability,
        evidence_refs=_refs(report_id, path, availability),
    )


def _proceedings_facts(report_id: UUID, raw: Mapping[str, Any]) -> list[FactValue]:
    """Summarize raw proceedings with domain rules until they get typed tables."""
    source_path = "/executionProceedings"
    raw_records = _pointer(raw, source_path)
    if not isinstance(raw_records, list) or not raw_records:
        return []
    records: list[ExecutionProceeding] = []
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, Mapping):
            continue
        record_path = f"{source_path}/{index}"
        record_ref = report_evidence_id(report_id, record_path)
        active = raw_record.get("active", _MISSING)
        amount = raw_record.get("amount", _MISSING)
        active_slot = (
            FactSlot[bool].available(active, evidence_refs=(record_ref,))
            if isinstance(active, bool)
            else FactSlot[bool].missing("proceeding active flag is unavailable")
        )
        try:
            parsed_amount = Decimal(str(amount))
        except Exception:
            amount_slot = FactSlot[Decimal].missing(
                "proceeding amount is unavailable", evidence_refs=(record_ref,)
            )
        else:
            amount_slot = FactSlot[Decimal].available(
                parsed_amount,
                evidence_refs=(report_evidence_id(report_id, f"{record_path}/amount"),),
            )
        records.append(
            ExecutionProceeding(
                active=active_slot,
                amount=amount_slot,
                evidence_refs=(record_ref,),
            )
        )
    section_ref = report_evidence_id(report_id, source_path)
    summary = summarize_proceedings(
        records,
        availability=(Availability.AVAILABLE if records else Availability.PRESENT_EMPTY),
        confirms_absence=False,
    )
    facts = [
        FactValue(
            key="proceedings.active_count",
            label="Действующие производства",
            value=summary.active_count,
            value_type=ValueType.INTEGER,
            availability=Availability.AVAILABLE,
            evidence_refs=[section_ref],
        ),
        FactValue(
            key="proceedings.amount_unknown_count",
            label="Производства без известной суммы",
            value=0 if summary.active is None else summary.active.unknown_count,
            value_type=ValueType.INTEGER,
            availability=Availability.AVAILABLE,
            evidence_refs=[section_ref],
        ),
    ]
    if summary.active is not None:
        total = summary.active.total
        facts.append(
            FactValue(
                key="proceedings.active_amount",
                label="Известная сумма действующих производств",
                value=(
                    decimal_to_string(total.value)
                    if total.value is not None and total.availability is Availability.AVAILABLE
                    else None
                ),
                value_type=ValueType.DECIMAL,
                currency="RUB",
                availability=total.availability,
                evidence_refs=list(total.evidence_refs),
                warnings=[
                    ContractWarning(code=WarningCode.INCOMPLETE_TOTAL, message=warning)
                    for warning in summary.warnings
                ],
            )
        )
    return facts


def _source_availability(state: SourceState) -> Availability:
    return {
        SourceState.PRESENT: Availability.AVAILABLE,
        SourceState.PRESENT_EMPTY: Availability.PRESENT_EMPTY,
        SourceState.MISSING: Availability.MISSING,
        SourceState.INVALID: Availability.INVALID,
    }[state]


def _section_view(
    report_id: UUID,
    section: ReportSectionName,
    stored: Mapping[str, SectionAvailability],
) -> SectionAvailabilityView:
    entries = [stored[key] for key in SECTION_SOURCE_KEYS[section] if key in stored]
    if not entries:
        return SectionAvailabilityView(section=section, availability=Availability.MISSING)
    states = {entry.source_state for entry in entries}
    if SourceState.INVALID in states:
        availability = Availability.INVALID
        count = None
    elif SourceState.PRESENT in states:
        availability = Availability.AVAILABLE
        count = max(entry.record_count or 0 for entry in entries)
    elif SourceState.PRESENT_EMPTY in states:
        availability = Availability.PRESENT_EMPTY
        count = 0
    else:
        availability = Availability.MISSING
        count = None
    evidence = [
        report_evidence_id(report_id, entry.source_path)
        for entry in entries
        if entry.source_state in {SourceState.PRESENT, SourceState.PRESENT_EMPTY}
    ]
    return SectionAvailabilityView(
        section=section,
        availability=availability,
        record_count=count,
        confirms_absence=False,
        evidence_refs=evidence,
    )


async def _load_overviews(
    uow: TenantWork,
    report_ids: Sequence[UUID],
    *,
    include_invalid: bool = False,
) -> list[CompanyOverview]:
    """Load many overview projections in a fixed number of statements."""
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

    result: list[CompanyOverview] = []
    for snapshot, company, profile, status, zsk in base_rows:
        invalid_snapshot = snapshot.ingestion_status is IngestionStatus.INVALID
        if invalid_snapshot and not include_invalid:
            continue
        invalid_paths = {
            item.source_path
            for item in warnings_by_report[snapshot.id]
            if item.source_path is not None and item.code == WarningCode.PARSE_FAILED.value
        }
        status_path = "/status/status"
        status_availability = (
            Availability.INVALID
            if invalid_snapshot
            else _field_availability(snapshot.raw_jsonb, status_path, invalid_paths)
        )
        status_raw = None if invalid_snapshot or status is None else status.status_raw
        status_availability = _usable_availability(status_raw, status_availability)
        bank_path = "/baseInfo/riskLevel"
        bank_availability = (
            Availability.INVALID
            if invalid_snapshot
            else _field_availability(snapshot.raw_jsonb, bank_path, invalid_paths)
        )
        bank_raw = None if invalid_snapshot or profile is None else profile.bank_risk_raw
        bank_availability = _usable_availability(bank_raw, bank_availability)
        zsk_path = "/zskRiskLevel"
        zsk_availability = (
            Availability.INVALID
            if invalid_snapshot
            else _field_availability(snapshot.raw_jsonb, zsk_path, invalid_paths)
        )
        zsk_raw = None if invalid_snapshot or zsk is None else zsk.raw_value
        zsk_availability = _usable_availability(zsk_raw, zsk_availability)

        facts: list[FactValue] = []
        for period in () if invalid_snapshot else finances_by_report[snapshot.id]:
            for field, (label, suffix) in _FINANCIAL_FIELDS.items():
                path = period.source_path + "".join(f"/{part}" for part in suffix)
                facts.append(
                    _fact(
                        report_id=snapshot.id,
                        raw=snapshot.raw_jsonb,
                        invalid_paths=invalid_paths,
                        key=f"financials.{period.year}.{field}",
                        label=label,
                        path=path,
                        value=getattr(period, field),
                        period=period.year,
                    )
                )
        if not invalid_snapshot:
            facts.extend(_proceedings_facts(snapshot.id, snapshot.raw_jsonb))
        stored_sections = sections_by_report[snapshot.id]
        warnings = [
            ContractWarning(
                code=(
                    WarningCode(item.code)
                    if item.code in WarningCode._value2member_map_
                    else WarningCode.UNSPECIFIED
                ),
                message=item.message,
                source_path=item.source_path,
            )
            for item in warnings_by_report[snapshot.id]
        ]
        display_name = next(
            (
                candidate
                for candidate in (
                    None if invalid_snapshot or profile is None else profile.short_name,
                    None if invalid_snapshot or profile is None else profile.full_name,
                    company.inn,
                )
                if candidate is not None and candidate.strip()
            ),
            company.inn,
        )
        zsk_level = DisplayLevel.POSITIVE if zsk_raw == "GREEN" else DisplayLevel.NEUTRAL
        result.append(
            CompanyOverview(
                company=CompanyIdentity(
                    id=company.id,
                    inn=company.inn,
                    ogrn=company.ogrn,
                    short_name=display_name,
                    full_name=None if invalid_snapshot or profile is None else profile.full_name,
                ),
                report=ReportIdentity(
                    id=snapshot.id,
                    source_report_at=snapshot.source_report_at,
                    ingested_at=snapshot.ingested_at,
                ),
                status=CompanyStatusView(
                    raw_value=status_raw,
                    label=status_raw or "Нет данных",
                    availability=status_availability,
                    status_date=None if status is None else status.status_date,
                    reason_raw=None if status is None else status.reason_raw,
                    evidence_refs=_refs(snapshot.id, status_path, status_availability),
                ),
                bank_risk=BankRiskAssessment(
                    raw_value=bank_raw,
                    label=bank_raw or "Нет данных",
                    display_level=DisplayLevel.NEUTRAL,
                    availability=bank_availability,
                    evidence_refs=_refs(snapshot.id, bank_path, bank_availability),
                ),
                zsk=ZskAssessmentView(
                    raw_value=zsk_raw,
                    display_level=zsk_level,
                    display_note=(
                        None
                        if zsk_level is DisplayLevel.POSITIVE
                        else "Отображение требует уточнения"
                    ),
                    policy_version=("zsk-display/1" if zsk is None else zsk.display_policy_version),
                    availability=zsk_availability,
                    evidence_refs=_refs(snapshot.id, zsk_path, zsk_availability),
                ),
                facts=facts,
                available_sections=(
                    [
                        SectionAvailabilityView(section=section, availability=Availability.INVALID)
                        for section in ReportSectionName
                    ]
                    if invalid_snapshot
                    else [
                        _section_view(snapshot.id, section, stored_sections)
                        for section in ReportSectionName
                    ]
                ),
                warnings=warnings,
                rule_version=OVERVIEW_RULE_VERSION,
            )
        )
    by_id = {item.report.id: item for item in result}
    return [by_id[ReportId(item)] for item in ids if ReportId(item) in by_id]


@router.get("/reports/{report_id}/overview", response_model=CompanyOverview)
async def get_company_overview(
    uow: TenantWork,
    report_id: Annotated[UUID, Path()],
) -> CompanyOverview:
    """Return the typed summary of exactly the requested snapshot."""
    loaded = await _load_overviews(uow, [report_id])
    if not loaded:
        raise ApiError(ErrorCode.NOT_FOUND, "report not found")
    return loaded[0]


@router.post("/projects/{project_id}/comparisons", response_model=ProjectComparison)
async def compare_project_companies(
    payload: CompareCompaniesInput,
    scope: ScopedProject,
    uow: TenantWork,
) -> ProjectComparison:
    """Compare only snapshots pinned in the authenticated project."""
    project_id = UUID(str(scope.project_id))
    active = await uow.project_companies.list_active(uow.scope.project(project_id))
    permitted = {row.report_id for row in active}
    requested = [UUID(str(report_id)) for report_id in payload.report_ids]
    if any(report_id not in permitted for report_id in requested):
        raise ApiError(ErrorCode.NOT_FOUND, "report not found in project")
    overviews = await _load_overviews(uow, requested, include_invalid=True)
    rows, warnings = build_comparison_rows(
        payload.report_ids,
        overviews,
        payload.criteria,
        year_policy=payload.year_policy,
        year=payload.year,
    )
    return ProjectComparison(
        project_id=scope.project_id,
        report_ids=payload.report_ids,
        criteria=payload.criteria,
        year_policy=payload.year_policy,
        year=payload.year,
        rows=rows,
        warnings=warnings,
        rule_version=COMPARISON_RULE_VERSION,
    )
