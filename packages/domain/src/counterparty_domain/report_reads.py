"""Pure projections of pinned reports shared by REST and MCP.

Callers load normalized columns and the original raw payload. This module opens
no files, database sessions or network connections.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from counterparty_contracts import (
    SECTION_SOURCE_KEYS,
    Availability,
    BankRiskAssessment,
    CompanyId,
    CompanyIdentity,
    CompanyOverview,
    CompanyStatusView,
    ContractWarning,
    DisplayLevel,
    FactValue,
    ReportId,
    ReportIdentity,
    ReportSectionName,
    SectionAvailabilityView,
    ValueType,
    WarningCode,
    ZskAssessment,
    decimal_to_string,
)

from .facts import FactSlot
from .proceedings import ExecutionProceeding, summarize_proceedings


@dataclass(frozen=True, slots=True)
class ReportReadData:
    """Loaded immutable report data; mappings use normalized storage column names."""

    report_id: UUID
    company_id: UUID
    inn: str
    ogrn: str | None
    source_report_at: datetime
    ingested_at: datetime
    raw: Mapping[str, Any]
    ingestion_status: str = "complete"
    profile: Mapping[str, Any] = field(default_factory=dict)
    status: Mapping[str, Any] = field(default_factory=dict)
    zsk: Mapping[str, Any] = field(default_factory=dict)
    financials: Sequence[Mapping[str, Any]] = ()
    sections: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    warnings: Sequence[ContractWarning] = ()

    @property
    def invalid_paths(self) -> set[str]:
        """Paths the importer explicitly failed to parse."""
        return {
            warning.source_path
            for warning in self.warnings
            if warning.source_path is not None and warning.code is WarningCode.PARSE_FAILED
        }

    @property
    def report(self) -> ReportIdentity:
        """The source snapshot identity, with no current-date substitution."""
        return ReportIdentity(
            id=ReportId(self.report_id),
            source_report_at=self.source_report_at,
            ingested_at=self.ingested_at,
        )


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


def section_availability(
    data: ReportReadData, section: ReportSectionName
) -> SectionAvailabilityView:
    """Combine the stored availability of the source blocks of one section."""
    if data.ingestion_status == "invalid":
        return SectionAvailabilityView(section=section, availability=Availability.INVALID)
    entries = [data.sections[key] for key in SECTION_SOURCE_KEYS[section] if key in data.sections]
    if not entries:
        return SectionAvailabilityView(section=section, availability=Availability.MISSING)
    states = {entry["source_state"] for entry in entries}
    if "invalid" in states:
        availability, count = Availability.INVALID, None
    elif "present" in states:
        availability, count = (
            Availability.AVAILABLE,
            sum(entry.get("record_count") or 0 for entry in entries),
        )
    elif "present_empty" in states:
        availability, count = Availability.PRESENT_EMPTY, 0
    else:
        availability, count = Availability.MISSING, None
    return SectionAvailabilityView(
        section=section,
        availability=availability,
        record_count=count,
        confirms_absence=False,
        evidence_refs=[
            report_evidence_id(data.report_id, entry["source_path"])
            for entry in entries
            if entry["source_state"] in {"present", "present_empty"}
        ],
    )


def build_company_overview(data: ReportReadData) -> CompanyOverview:
    """Build the same normalized overview for both read surfaces."""
    invalid = data.ingestion_status == "invalid"

    def assessment(path: str, value: Any) -> tuple[Any, Availability]:
        availability = (
            Availability.INVALID
            if invalid
            else _field_availability(data.raw, path, data.invalid_paths)
        )
        value = None if invalid or availability is not Availability.AVAILABLE else value
        return value, _usable_availability(value, availability)

    status_raw, status_availability = assessment("/status/status", data.status.get("status_raw"))
    bank_raw, bank_availability = assessment(
        "/baseInfo/riskLevel", data.profile.get("bank_risk_raw")
    )
    zsk_raw, zsk_availability = assessment("/zskRiskLevel", data.zsk.get("raw_value"))
    facts = []
    for period in () if invalid else data.financials:
        for name, (label, suffix) in _FINANCIAL_FIELDS.items():
            facts.append(
                _fact(
                    report_id=data.report_id,
                    raw=data.raw,
                    invalid_paths=data.invalid_paths,
                    key=f"financials.{period['year']}.{name}",
                    label=label,
                    path=period["source_path"] + "".join(f"/{part}" for part in suffix),
                    value=period.get(name),
                    period=period["year"],
                )
            )
    if not invalid:
        facts.extend(_proceedings_facts(data.report_id, data.raw))
    display_name = next(
        (
            value
            for value in (
                None if invalid else data.profile.get("short_name"),
                None if invalid else data.profile.get("full_name"),
                data.inn,
            )
            if isinstance(value, str) and value.strip()
        ),
        data.inn,
    )
    zsk_level = DisplayLevel.POSITIVE if zsk_raw == "GREEN" else DisplayLevel.NEUTRAL
    return CompanyOverview(
        company=CompanyIdentity(
            id=CompanyId(data.company_id),
            inn=data.inn,
            ogrn=data.ogrn,
            short_name=display_name,
            full_name=None if invalid else data.profile.get("full_name"),
        ),
        report=data.report,
        status=CompanyStatusView(
            raw_value=status_raw,
            label=status_raw or "Нет данных",
            availability=status_availability,
            status_date=None if invalid else data.status.get("status_date"),
            reason_raw=None if invalid else data.status.get("reason_raw"),
            evidence_refs=_refs(data.report_id, "/status/status", status_availability),
        ),
        bank_risk=BankRiskAssessment(
            raw_value=bank_raw,
            label=bank_raw or "Нет данных",
            display_level=DisplayLevel.NEUTRAL,
            availability=bank_availability,
            evidence_refs=_refs(data.report_id, "/baseInfo/riskLevel", bank_availability),
        ),
        zsk=ZskAssessment(
            raw_value=zsk_raw,
            display_level=zsk_level,
            display_note=None
            if zsk_level is DisplayLevel.POSITIVE
            else "Отображение требует уточнения",
            policy_version=data.zsk.get("display_policy_version", "zsk-display/1"),
            availability=zsk_availability,
            evidence_refs=_refs(data.report_id, "/zskRiskLevel", zsk_availability),
        ),
        facts=facts,
        available_sections=[section_availability(data, section) for section in ReportSectionName],
        warnings=list(data.warnings),
        rule_version=OVERVIEW_RULE_VERSION,
    )
