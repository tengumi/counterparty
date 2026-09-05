"""Typed report sections, deterministic filters and snapshot-bound pagination."""

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from counterparty_contracts import (
    SECTION_RECORD_KINDS,
    SECTION_SOURCE_KEYS,
    Activity,
    ArbitrationAggregate,
    ArbitrationAggregation,
    Availability,
    ContractWarning,
    FactValue,
    FinancialPeriod,
    GetReportSectionInput,
    Inspection,
    License,
    PageInfo,
    PartyRole,
    Proceeding,
    ProcurementAggregate,
    ProfileRecord,
    RelatedEntity,
    ReportId,
    ReportRecord,
    ReportSection,
    ReportSectionName,
    RiskSignal,
    RiskSignalPolarity,
    ValueType,
    WarningCode,
    decimal_to_string,
)
from pydantic import ValidationError

from .report_reads import (
    _FINANCIAL_FIELDS,
    _MISSING,
    ReportReadData,
    _field_availability,
    _pointer,
    _source_decimal,
    report_evidence_id,
    section_availability,
)

SECTION_RULE_VERSION = "report-section/1"
_ADDITIONAL_FINANCIALS = {
    "current_assets": ("Оборотные активы", "/assets/currentAssets/total"),
    "stocks": ("Запасы", "/assets/currentAssets/stocks"),
    "noncurrent_assets": ("Внеоборотные активы", "/assets/uncurrentAssets/total"),
    "fixed_assets": ("Основные средства", "/assets/uncurrentAssets/fixedAssets"),
    "balance_total_liabilities_side": ("Баланс пассивов", "/liabilities/totalLiabilities"),
    "long_term_total": ("Долгосрочные обязательства", "/liabilities/longTermDuties/total"),
    "long_term_other": ("Прочие долгосрочные обязательства", "/liabilities/longTermDuties/others"),
    "short_term_total": ("Краткосрочные обязательства", "/liabilities/shortTermLiabilities/total"),
    "short_term_borrowed": ("Заёмные средства", "/liabilities/shortTermLiabilities/borrowedFunds"),
}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _instant(value: object) -> datetime | None:
    # Calendar-only values cannot be silently promoted to precise UTC instants.
    if isinstance(value, Mapping) and set(value) == {"$date"}:
        value = value["$date"]
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def source_fact(
    data: ReportReadData,
    path: str,
    key: str,
    label: str,
    value_type: ValueType,
    *,
    period: int | None = None,
    normalized: object = _MISSING,
    currency: str | None = None,
) -> FactValue:
    """Project one scalar without equating missing, empty, invalid or zero."""
    availability = _field_availability(data.raw, path, data.invalid_paths)
    raw = _pointer(data.raw, path)
    ref_path = path
    if raw is _MISSING:
        parent_path = path.rsplit("/", 1)[0]
        parent = _pointer(data.raw, parent_path)
        if parent is None or parent == {} or parent == []:
            availability = Availability.PRESENT_EMPTY
            ref_path = parent_path
    value: Any = None
    if availability is Availability.AVAILABLE:
        supplied = raw if normalized is _MISSING else normalized
        if value_type is ValueType.DECIMAL:
            parsed = _source_decimal(supplied)
            value = None if parsed is None else decimal_to_string(parsed)
        elif value_type is ValueType.INTEGER:
            parsed = _source_decimal(supplied)
            value = (
                int(parsed) if parsed is not None and parsed == parsed.to_integral_value() else None
            )
        elif value_type is ValueType.BOOLEAN:
            value = supplied if isinstance(supplied, bool) else None
        elif value_type is ValueType.DATE:
            if isinstance(supplied, str):
                value = supplied
        else:
            value = _text(supplied)
        if value is None:
            availability = Availability.INVALID
    warnings = []
    if availability is Availability.INVALID:
        warnings.append(
            ContractWarning(
                code=WarningCode.PARSE_FAILED,
                message="Поле не удалось прочитать в заявленном формате",
                source_path=path,
            )
        )
    return FactValue(
        key=key,
        label=label,
        value=value,
        value_type=value_type,
        currency=currency,
        period=period,
        availability=availability,
        evidence_refs=(
            []
            if raw is _MISSING and ref_path == path
            else [report_evidence_id(data.report_id, ref_path)]
        ),
        warnings=warnings,
    )


def _record_refs(data: ReportReadData, path: str) -> list[str]:
    return [report_evidence_id(data.report_id, path)]


def _items(data: ReportReadData, path: str) -> list[tuple[str, Mapping[str, Any]]]:
    value = _pointer(data.raw, path)
    if value is _MISSING or value is None or value == []:
        return []
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise ValueError("source records must be objects in an array")
    return [(f"{path}/{index}", row) for index, row in enumerate(value) if isinstance(row, Mapping)]


def _financials(data: ReportReadData) -> list[ReportRecord]:
    records: list[ReportRecord] = []
    for row in data.financials:
        path = row["source_path"]
        year = row["year"]
        headline: dict[str, Any] = {
            name: source_fact(
                data,
                path + "".join(f"/{part}" for part in suffix),
                name,
                label,
                ValueType.DECIMAL,
                period=year,
                normalized=row.get(name),
                currency="RUB",
            )
            for name, (label, suffix) in _FINANCIAL_FIELDS.items()
        }
        additional = [
            source_fact(
                data,
                path + suffix,
                name,
                label,
                ValueType.DECIMAL,
                period=year,
                normalized=row.get(name),
                currency="RUB",
            )
            for name, (label, suffix) in _ADDITIONAL_FINANCIALS.items()
        ]
        records.append(
            FinancialPeriod(
                year=year,
                **headline,
                additional_facts=additional,
                evidence_refs=_record_refs(data, path),
            )
        )
    return records


def _raw_records(data: ReportReadData, section: ReportSectionName) -> list[ReportRecord]:
    records: list[ReportRecord] = []
    if not SECTION_RECORD_KINDS[section]:
        return []
    if section is ReportSectionName.FINANCIALS:
        return _financials(data)
    if section is ReportSectionName.PROFILE:
        profile_keys = {
            "short_name",
            "full_name",
            "kpp",
            "okpo",
            "address",
            "registration_date",
            "years_from_registration",
            "email",
            "website",
            "company_size",
        }
        return [
            ProfileRecord(
                **{key: value for key, value in data.profile.items() if key in profile_keys},
                inn=data.inn,
                evidence_refs=_record_refs(data, "/baseInfo"),
            )
        ]
    if section is ReportSectionName.ACTIVITIES:
        main = _pointer(data.raw, "/kindsOfActivityInfo/mainKindOfActivity")
        activities = _items(data, "/kindsOfActivityInfo/otherKindsOfActivity")
        if isinstance(main, Mapping) and main:
            activities.insert(0, ("/kindsOfActivityInfo/mainKindOfActivity", main))
        return [
            Activity(
                code=_text(row.get("code")),
                description=_text(row.get("description")),
                is_primary=path.endswith("/mainKindOfActivity"),
                evidence_refs=_record_refs(data, path),
            )
            for path, row in activities
        ]
    if section is ReportSectionName.RISK_SIGNALS:
        for polarity in RiskSignalPolarity:
            for path, row in _items(data, f"/reputationalRisks/{polarity.value}"):
                code = _text(row.get("code"))
                if code is None:
                    raise ValueError("risk signal has no source code")
                records.append(
                    RiskSignal(
                        code=code,
                        source_name=_text(row.get("name")),
                        polarity=polarity,
                        chapter=_text(row.get("chapter")),
                        interpretation_note=(
                            "Формулировка источника; не самостоятельный проверенный вывод"
                        ),
                        evidence_refs=_record_refs(data, path),
                    )
                )
        return records
    if section is ReportSectionName.ARBITRATION:
        return _arbitration(data)
    for path, row in _items(data, f"/{SECTION_SOURCE_KEYS[section][0]}"):
        refs = _record_refs(data, path)
        if section is ReportSectionName.EXECUTION_PROCEEDINGS:
            records.append(
                Proceeding(
                    id=uuid5(NAMESPACE_URL, refs[0]),
                    number=_text(row.get("number")),
                    started_at=_instant(row.get("date")),
                    active=source_fact(
                        data, path + "/active", "active", "Действующее", ValueType.BOOLEAN
                    ),
                    amount=source_fact(
                        data, path + "/amount", "amount", "Сумма", ValueType.DECIMAL, currency="RUB"
                    ),
                    evidence_refs=refs,
                )
            )
        elif section is ReportSectionName.PROCUREMENTS:
            records.append(
                ProcurementAggregate(
                    year=row["procurementsYear"],
                    law_code=row["federalLawCode"],
                    winners_count=source_fact(
                        data,
                        path + "/tenderWinnerCnt",
                        "winners_count",
                        "Победы",
                        ValueType.INTEGER,
                    ),
                    contracts_count=source_fact(
                        data,
                        path + "/contractSignedCnt",
                        "contracts_count",
                        "Контракты",
                        ValueType.INTEGER,
                    ),
                    contracts_amount=source_fact(
                        data,
                        path + "/contractSignedAmt",
                        "contracts_amount",
                        "Сумма контрактов",
                        ValueType.DECIMAL,
                        currency="RUB",
                    ),
                    evidence_refs=refs,
                )
            )
        elif section is ReportSectionName.LICENSES:
            records.append(
                License(
                    number=_text(row.get("number")),
                    name=_text(row.get("name")),
                    authority=_text(row.get("issuingAuthority")),
                    issue_date=_instant(row.get("issueDate")),
                    status_raw=_text(row.get("status")),
                    evidence_refs=refs,
                )
            )
        elif section is ReportSectionName.INSPECTIONS:
            records.append(
                Inspection(
                    external_id=_text(row.get("erpId")),
                    form=_text(row.get("form")),
                    authority=_text(row.get("authorityName")),
                    start_date=_instant(row.get("startDate")),
                    end_date=_instant(row.get("endDate")),
                    status_raw=_text(row.get("inspectionStatus")),
                    evidence_refs=refs,
                )
            )
        elif section is ReportSectionName.RELATED_COMPANIES:
            records.append(
                RelatedEntity(
                    inn=_text(row.get("inn")),
                    ogrn=_text(row.get("ogrn")),
                    name=_text(row.get("name")),
                    available_company_id=None,
                    evidence_refs=refs,
                )
            )
    return records


def _arbitration(data: ReportReadData) -> list[ReportRecord]:
    records: list[ReportRecord] = []
    for path, row in _items(data, "/arbitrationCases"):
        for role in PartyRole:
            records.append(
                ArbitrationAggregate(
                    aggregation=ArbitrationAggregation.BY_YEAR,
                    role=role,
                    year=row.get("year"),
                    count=source_fact(
                        data, path + f"/{role.value}Count", "count", "Количество", ValueType.INTEGER
                    ),
                    amount=source_fact(
                        data,
                        path + f"/{role.value}Amount",
                        "amount",
                        "Сумма",
                        ValueType.DECIMAL,
                        currency="RUB",
                    ),
                    evidence_refs=_record_refs(data, path),
                )
            )
    for role, prefix in ((PartyRole.PLAINTIFF, "plaintiff"), (PartyRole.DEFENDANT, "defandant")):
        group_path = f"/arbitrationByStatus/{prefix}Arbitration"
        group = _pointer(data.raw, group_path)
        if not isinstance(group, Mapping):
            continue
        for key, row in sorted(group.items()):
            if not isinstance(row, Mapping) or not key.startswith(prefix + "Arbitration"):
                continue
            path = f"{group_path}/{key}"
            case_status = key.removeprefix(prefix + "Arbitration")
            code = {"Finished": "f", "Appealed": "a", "Pending": "p"}.get(case_status)
            if code is None:
                raise ValueError("unknown status aggregate layout")
            field_prefix = ("p" if role is PartyRole.PLAINTIFF else "d") + code
            records.append(
                ArbitrationAggregate(
                    aggregation=ArbitrationAggregation.BY_STATUS,
                    role=role,
                    case_status_raw=case_status,
                    count=source_fact(
                        data,
                        path + f"/{field_prefix}Count",
                        "count",
                        "Количество",
                        ValueType.INTEGER,
                    ),
                    amount=source_fact(
                        data,
                        path + f"/{field_prefix}Amount",
                        "amount",
                        "Сумма",
                        ValueType.DECIMAL,
                        currency="RUB",
                    ),
                    evidence_refs=_record_refs(data, path),
                )
            )
    return records


def _scalar_facts(data: ReportReadData, section: ReportSectionName) -> list[FactValue]:
    facts: list[FactValue] = []

    def visit(value: object, path: str, period: int | None = None) -> None:
        if isinstance(value, Mapping) and not any(str(key).startswith("$") for key in value):
            raw_year = value.get("year")
            year = (
                raw_year if isinstance(raw_year, int) and not isinstance(raw_year, bool) else period
            )
            for key, child in sorted(value.items()):
                visit(child, path + "/" + str(key).replace("~", "~0").replace("/", "~1"), year)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}/{index}", period)
        else:
            kind = (
                ValueType.BOOLEAN
                if isinstance(value, bool)
                else ValueType.INTEGER
                if isinstance(value, int)
                else ValueType.STRING
            )
            if isinstance(value, Mapping) and "$date" in value:
                instant = _instant(value)
                if instant is not None:
                    facts.append(
                        FactValue(
                            key=path,
                            label=path.split("/")[-1],
                            value=instant.isoformat(),
                            value_type=ValueType.STRING,
                            period=period,
                            availability=Availability.AVAILABLE,
                            evidence_refs=_record_refs(data, path),
                        )
                    )
                else:
                    facts.append(
                        source_fact(
                            data,
                            path,
                            path,
                            path.split("/")[-1],
                            ValueType.STRING,
                            normalized=None,
                            period=period,
                        )
                    )
                return
            facts.append(source_fact(data, path, path, path.split("/")[-1], kind, period=period))

    for source in SECTION_SOURCE_KEYS[section]:
        raw = _pointer(data.raw, "/" + source)
        if raw is not _MISSING:
            visit(raw, "/" + source)
    return facts


def _matches(record: ReportRecord | FactValue, request: GetReportSectionInput) -> bool:
    filters = request.filters
    if filters is None:
        return True
    if (
        filters.years is not None
        and getattr(record, "year", getattr(record, "period", None)) not in filters.years
    ):
        return False
    if filters.active is not None and (
        not isinstance(record, Proceeding) or record.active.value is not filters.active
    ):
        return False
    if filters.role is not None and getattr(record, "role", None) is not filters.role:
        return False
    return (
        filters.status_raw is None or getattr(record, "case_status_raw", None) == filters.status_raw
    )


def _scope(request: GetReportSectionInput) -> str:
    payload = request.model_dump(mode="json", exclude={"cursor", "limit"}, exclude_none=True)
    if request.filters is not None and request.filters.years is not None:
        payload["filters"]["years"] = sorted(request.filters.years)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _position(request: GetReportSectionInput, count: int) -> int:
    if request.cursor is None:
        return 0
    try:
        cursor = request.cursor
        decoded = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        ).decode()
        scope, raw_position = decoded.split(":")
        position = int(raw_position)
        if scope != _scope(request) or not 0 < position < count:
            raise ValueError("invalid cursor position")
        return position
    except (ValueError, binascii.Error, UnicodeError) as error:
        raise ValueError("the report section cursor is not valid for this request") from error


def build_report_section(data: ReportReadData, request: GetReportSectionInput) -> ReportSection:
    """Build one typed page, validating all filters and the continuation scope."""
    if data.report_id != request.report_id:
        raise ValueError("requested report does not match loaded snapshot")
    # Revalidate even inputs created through model_construct by an internal caller.
    request = GetReportSectionInput.model_validate(request.model_dump())
    availability = section_availability(data, request.section).availability
    warnings = [
        warning
        for warning in data.warnings
        if warning.source_path is None
        or any(
            warning.source_path == "/" + key or warning.source_path.startswith("/" + key + "/")
            for key in SECTION_SOURCE_KEYS[request.section]
        )
    ]
    records: list[ReportRecord] = []
    facts: list[FactValue] = []
    if availability is Availability.AVAILABLE:
        try:
            records = _raw_records(data, request.section)
            if not SECTION_RECORD_KINDS[request.section]:
                facts = _scalar_facts(data, request.section)
        except (ValueError, KeyError, TypeError, ValidationError):
            availability = Availability.INVALID
            warnings.append(
                ContractWarning(
                    code=WarningCode.PARSE_FAILED,
                    message="Раздел не соответствует ожидаемой структуре источника",
                )
            )
        records = [record for record in records if _matches(record, request)]
        facts = [fact for fact in facts if _matches(fact, request)]
    if availability is Availability.PRESENT_EMPTY:
        warnings.append(
            ContractWarning(
                code=WarningCode.EMPTY_NOT_CONFIRMED,
                message="Пустой раздел не подтверждает отсутствие событий или риска",
            )
        )
    if availability is Availability.MISSING:
        warnings.append(
            ContractWarning(
                code=WarningCode.SOURCE_MISSING,
                message="Раздел отсутствует в предоставленном отчёте",
            )
        )
    if request.section is ReportSectionName.INSPECTIONS and records:
        warnings.append(
            ContractWarning(
                code=WarningCode.PRECISION_REDUCED,
                message=(
                    "Календарные даты без времени доступны в исходном фрагменте; "
                    "точный UTC момент не задан"
                ),
            )
        )

    def has_unknown(value: object) -> bool:
        if isinstance(value, Mapping):
            if "availability" in value and value["availability"] != "available":
                return True
            return any(has_unknown(child) for child in value.values())
        return isinstance(value, list) and any(has_unknown(child) for child in value)

    if any(has_unknown(item.model_dump(mode="json")) for item in [*records, *facts]):
        warnings.append(
            ContractWarning(
                code=WarningCode.PARTIAL_DATA,
                message=(
                    "Раздел содержит поля без подтверждённых значений; они не считаются нулевыми"
                ),
            )
        )
    count = len(records) if records else len(facts)
    start = _position(request, count)
    end = min(start + request.limit, count)
    has_more = end < count
    cursor = (
        base64.urlsafe_b64encode(f"{_scope(request)}:{end}".encode()).decode().rstrip("=")
        if has_more
        else None
    )
    if has_more:
        warnings.append(
            ContractWarning(
                code=WarningCode.RESULT_TRUNCATED,
                message="Раздел продолжается на следующей странице",
            )
        )
    return ReportSection(
        report_id=ReportId(data.report_id),
        section=request.section,
        availability=availability,
        records=records[start:end],
        facts=facts[start:end],
        page=PageInfo(limit=request.limit, next_cursor=cursor, has_more=has_more),
        total_records=count
        if availability in {Availability.AVAILABLE, Availability.PRESENT_EMPTY}
        else None,
        warnings=warnings,
        rule_version=SECTION_RULE_VERSION,
    )
