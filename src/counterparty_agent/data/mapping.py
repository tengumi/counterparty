"""Преобразование входного отчёта в каноническую модель."""

from __future__ import annotations

import hashlib

from counterparty_agent.data.decoding import decode_extended_json
from counterparty_agent.data.evidence import _build_evidence
from counterparty_agent.data.finances import _map_financial_coefficients, _map_financial_statements
from counterparty_agent.data.identifiers import (
    is_valid_inn,
    is_valid_ogrn,
    parse_bank_traffic_light,
)
from counterparty_agent.data.sections import (
    _map_activities,
    _map_arbitration_by_year,
    _map_arbitration_summary,
    _map_enforcement_proceedings,
    _map_licenses,
    _map_reputation,
)
from counterparty_agent.data.values import (
    _mapping,
    _optional_string,
    _record_error,
    _required_datetime,
    _required_string,
    _stable_hash,
)
from counterparty_agent.models import (
    BankRiskAssessment,
    BankTrafficLight,
    CompanyIdentity,
    CompanyStatus,
    CounterpartySnapshot,
    PartyType,
)


def _map_record(
    raw_record: object,
    *,
    record_number: int,
    source_name: str,
    source_hash: str,
) -> CounterpartySnapshot:
    record_hash = _stable_hash(raw_record)
    decoded_record = decode_extended_json(raw_record)
    root = _mapping(decoded_record, "корневая запись", record_number)
    source_id = _mapping(root.get("_id"), "_id", record_number)
    report = _mapping(root.get("report"), "report", record_number)
    base_info = _mapping(report.get("baseInfo"), "report.baseInfo", record_number)
    raw_status = _mapping(report.get("status"), "report.status", record_number)

    inn = _required_string(base_info.get("inn"), "report.baseInfo.inn", record_number)
    ogrn = _required_string(base_info.get("ogrn"), "report.baseInfo.ogrn", record_number)
    if not is_valid_inn(inn) or not is_valid_ogrn(ogrn):
        raise _record_error("invalid_identifier", "Запись содержит некорректный идентификатор")

    source_ogrn = _required_string(source_id.get("ogrn"), "_id.ogrn", record_number)
    report_at = _required_datetime(report.get("reportDate"), "report.reportDate", record_number)
    source_date = _required_datetime(source_id.get("date"), "_id.date", record_number)
    if source_ogrn != ogrn or source_date != report_at:
        raise _record_error(
            "inconsistent_source_id",
            "Идентификатор записи не совпадает с реквизитами отчёта",
        )

    party_type = _party_type(inn, ogrn, record_number)
    registration_info = _mapping(
        base_info.get("registrationInfo"),
        "report.baseInfo.registrationInfo",
        record_number,
    )
    status_at = _required_datetime(raw_status.get("date"), "report.status.date", record_number)
    raw_bank_level = _optional_string(report.get("zskRiskLevel"))
    recognized_bank_level = parse_bank_traffic_light(raw_bank_level)
    base_risk_level_raw = _optional_string(base_info.get("riskLevel"))
    company_id = f"company_{hashlib.sha256(f'ogrn:{ogrn}'.encode()).hexdigest()[:24]}"
    snapshot_id = f"snapshot_{record_hash[:24]}"
    identity = CompanyIdentity(
        inn=inn,
        ogrn=ogrn,
        kpp=_optional_string(base_info.get("kpp")),
        full_name=_required_string(
            base_info.get("fullName"), "report.baseInfo.fullName", record_number
        ),
        short_name=_required_string(
            base_info.get("shortName"), "report.baseInfo.shortName", record_number
        ),
        party_type=party_type,
        address=_optional_string(base_info.get("address")),
        registration_at=_required_datetime(
            registration_info.get("registrationDate"),
            "report.baseInfo.registrationInfo.registrationDate",
            record_number,
        ),
        okpo=_optional_string(base_info.get("okpo")),
        email=_optional_string(base_info.get("email")),
        website=_optional_string(base_info.get("website")),
        company_size=_optional_string(base_info.get("companySize")),
    )
    status = CompanyStatus(
        raw_status=_required_string(
            raw_status.get("status"), "report.status.status", record_number
        ),
        effective_at=status_at,
        reason=_optional_string(raw_status.get("reasonName")),
    )
    bank_risk = BankRiskAssessment(
        raw_level=raw_bank_level,
        recognized_level=recognized_bank_level,
        display_level=recognized_bank_level or BankTrafficLight.GREY,
        assessed_at=report_at,
    )
    financial_statements = _map_financial_statements(report, record_number)
    financial_coefficients = _map_financial_coefficients(report, record_number)
    arbitration_summary = _map_arbitration_summary(report, record_number)
    arbitration_by_year = _map_arbitration_by_year(report, record_number)
    enforcement_proceedings = _map_enforcement_proceedings(report, record_number)
    activities = _map_activities(report, record_number)
    licenses = _map_licenses(report, record_number)
    reputation = _map_reputation(report, record_number)
    evidence = _build_evidence(
        company_id=company_id,
        snapshot_id=snapshot_id,
        report_at=report_at,
        source_name=source_name,
        source_hash=source_hash,
        record_hash=record_hash,
        identity=identity,
        status=status,
        bank_risk=bank_risk,
        base_risk_level_raw=base_risk_level_raw,
        financial_statements=financial_statements,
        financial_coefficients=financial_coefficients,
        arbitration_summary=arbitration_summary,
        arbitration_by_year=arbitration_by_year,
        enforcement_proceedings=enforcement_proceedings,
        activities=activities,
        licenses=licenses,
        reputation=reputation,
    )

    return CounterpartySnapshot(
        company_id=company_id,
        snapshot_id=snapshot_id,
        report_at=report_at,
        source_name=source_name,
        source_hash=source_hash,
        record_hash=record_hash,
        identity=identity,
        status=status,
        bank_risk=bank_risk,
        base_risk_level_raw=base_risk_level_raw,
        financial_statements=financial_statements,
        financial_coefficients=financial_coefficients,
        arbitration_summary=arbitration_summary,
        arbitration_by_year=arbitration_by_year,
        enforcement_proceedings=enforcement_proceedings,
        activities=activities,
        licenses=licenses,
        reputation=reputation,
        evidence=evidence,
        report=dict(report),
    )


def _party_type(inn: str, ogrn: str, record_number: int) -> PartyType:
    if len(inn) == 10 and len(ogrn) == 13:
        return PartyType.LEGAL_ENTITY
    if len(inn) == 12 and len(ogrn) == 15:
        return PartyType.INDIVIDUAL_ENTREPRENEUR
    raise _record_error(
        "inconsistent_party_type",
        f"Запись {record_number} содержит несогласованные типы ИНН и ОГРН",
    )
