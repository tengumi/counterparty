"""Чтение судебных, реестровых и репутационных разделов."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from counterparty_agent.data.values import (
    _mapping,
    _optional_datetime,
    _optional_decimal,
    _optional_int,
    _required_bool,
    _required_datetime,
    _required_decimal,
    _required_int,
    _required_string,
    _sequence,
)
from counterparty_agent.models import (
    ActivityProfile,
    ArbitrationRoleSummary,
    ArbitrationSummary,
    ArbitrationYearSummary,
    EconomicActivity,
    EnforcementProceeding,
    LicenseRecord,
    ReputationPolarity,
    ReputationProfile,
    ReputationSignal,
)


def _map_arbitration_summary(report: Mapping[str, Any], record_number: int) -> ArbitrationSummary:
    prefix = "report.arbitrationByStatus"
    raw_summary = _mapping(report.get("arbitrationByStatus"), prefix, record_number)
    plaintiff = _mapping(
        raw_summary.get("plaintiffArbitration"),
        f"{prefix}.plaintiffArbitration",
        record_number,
    )
    defendant = _mapping(
        raw_summary.get("defandantArbitration"),
        f"{prefix}.defandantArbitration",
        record_number,
    )
    return ArbitrationSummary(
        total_count=_optional_int(
            raw_summary, "commonCount", f"{prefix}.commonCount", record_number
        ),
        total_amount=_optional_decimal(
            raw_summary, "commonAmount", f"{prefix}.commonAmount", record_number
        ),
        as_plaintiff=_map_arbitration_role(
            plaintiff,
            role_path=f"{prefix}.plaintiffArbitration",
            field_prefix="plaintiffArbitration",
            count_prefixes=("pf", "pp", "pa"),
            record_number=record_number,
        ),
        as_defendant=_map_arbitration_role(
            defendant,
            role_path=f"{prefix}.defandantArbitration",
            field_prefix="defandantArbitration",
            count_prefixes=("df", "dp", "da"),
            record_number=record_number,
        ),
    )


def _map_arbitration_role(
    role: Mapping[str, Any],
    *,
    role_path: str,
    field_prefix: str,
    count_prefixes: tuple[str, str, str],
    record_number: int,
) -> ArbitrationRoleSummary:
    stages = ("Finished", "Pending", "Appealed")
    buckets: list[Mapping[str, Any]] = []
    paths: list[str] = []
    for stage in stages:
        key = f"{field_prefix}{stage}"
        path = f"{role_path}.{key}"
        buckets.append(_mapping(role.get(key), path, record_number))
        paths.append(path)

    return ArbitrationRoleSummary(
        finished_count=_optional_int(
            buckets[0], f"{count_prefixes[0]}Count", f"{paths[0]}.count", record_number
        ),
        finished_amount=_optional_decimal(
            buckets[0], f"{count_prefixes[0]}Amount", f"{paths[0]}.amount", record_number
        ),
        pending_count=_optional_int(
            buckets[1], f"{count_prefixes[1]}Count", f"{paths[1]}.count", record_number
        ),
        pending_amount=_optional_decimal(
            buckets[1], f"{count_prefixes[1]}Amount", f"{paths[1]}.amount", record_number
        ),
        appealed_count=_optional_int(
            buckets[2], f"{count_prefixes[2]}Count", f"{paths[2]}.count", record_number
        ),
        appealed_amount=_optional_decimal(
            buckets[2], f"{count_prefixes[2]}Amount", f"{paths[2]}.amount", record_number
        ),
    )


def _map_arbitration_by_year(
    report: Mapping[str, Any], record_number: int
) -> tuple[ArbitrationYearSummary, ...] | None:
    if "arbitrationCases" not in report:
        return None
    raw_years = _sequence(report["arbitrationCases"], "report.arbitrationCases", record_number)
    results: list[ArbitrationYearSummary] = []
    for index, raw_year in enumerate(raw_years):
        prefix = f"report.arbitrationCases[{index}]"
        year = _mapping(raw_year, prefix, record_number)
        results.append(
            ArbitrationYearSummary(
                year=_required_int(year.get("year"), f"{prefix}.year", record_number),
                plaintiff_count=_required_int(
                    year.get("plaintiffCount"), f"{prefix}.plaintiffCount", record_number
                ),
                plaintiff_amount=_required_decimal(
                    year.get("plaintiffAmount"), f"{prefix}.plaintiffAmount", record_number
                ),
                defendant_count=_required_int(
                    year.get("defendantCount"), f"{prefix}.defendantCount", record_number
                ),
                defendant_amount=_required_decimal(
                    year.get("defendantAmount"), f"{prefix}.defendantAmount", record_number
                ),
            )
        )
    return tuple(results)


def _map_enforcement_proceedings(
    report: Mapping[str, Any], record_number: int
) -> tuple[EnforcementProceeding, ...]:
    path = "report.executionProceedings"
    raw_proceedings = _sequence(report.get("executionProceedings"), path, record_number)
    results: list[EnforcementProceeding] = []
    for index, raw_proceeding in enumerate(raw_proceedings):
        prefix = f"{path}[{index}]"
        proceeding = _mapping(raw_proceeding, prefix, record_number)
        results.append(
            EnforcementProceeding(
                number=_required_string(
                    proceeding.get("number"), f"{prefix}.number", record_number
                ),
                opened_at=_required_datetime(
                    proceeding.get("date"), f"{prefix}.date", record_number
                ),
                is_active=_required_bool(
                    proceeding.get("active"), f"{prefix}.active", record_number
                ),
                amount=_optional_decimal(proceeding, "amount", f"{prefix}.amount", record_number),
            )
        )
    return tuple(results)


def _map_activities(report: Mapping[str, Any], record_number: int) -> ActivityProfile:
    prefix = "report.kindsOfActivityInfo"
    raw_activities = _mapping(report.get("kindsOfActivityInfo"), prefix, record_number)
    main = _map_activity(
        raw_activities.get("mainKindOfActivity"),
        f"{prefix}.mainKindOfActivity",
        record_number,
    )
    if "otherKindsOfActivity" not in raw_activities:
        others = None
    else:
        raw_others = _sequence(
            raw_activities["otherKindsOfActivity"],
            f"{prefix}.otherKindsOfActivity",
            record_number,
        )
        others = tuple(
            _map_activity(
                raw_activity,
                f"{prefix}.otherKindsOfActivity[{index}]",
                record_number,
            )
            for index, raw_activity in enumerate(raw_others)
        )
    return ActivityProfile(main=main, others=others)


def _map_activity(value: object, path: str, record_number: int) -> EconomicActivity:
    activity = _mapping(value, path, record_number)
    return EconomicActivity(
        code=_required_string(activity.get("code"), f"{path}.code", record_number),
        description=_required_string(
            activity.get("description"), f"{path}.description", record_number
        ),
    )


def _map_licenses(
    report: Mapping[str, Any], record_number: int
) -> tuple[LicenseRecord, ...] | None:
    if "licenses" not in report:
        return None
    raw_licenses = _sequence(report["licenses"], "report.licenses", record_number)
    results: list[LicenseRecord] = []
    for index, raw_license in enumerate(raw_licenses):
        prefix = f"report.licenses[{index}]"
        license_record = _mapping(raw_license, prefix, record_number)
        results.append(
            LicenseRecord(
                number=_required_string(
                    license_record.get("number"), f"{prefix}.number", record_number
                ),
                name=_required_string(license_record.get("name"), f"{prefix}.name", record_number),
                raw_status=_required_string(
                    license_record.get("status"), f"{prefix}.status", record_number
                ),
                issued_at=_required_datetime(
                    license_record.get("issueDate"), f"{prefix}.issueDate", record_number
                ),
                ends_at=_optional_datetime(
                    license_record, "endDate", f"{prefix}.endDate", record_number
                ),
                issuing_authority=_required_string(
                    license_record.get("issuingAuthority"),
                    f"{prefix}.issuingAuthority",
                    record_number,
                ),
            )
        )
    return tuple(results)


def _map_reputation(report: Mapping[str, Any], record_number: int) -> ReputationProfile:
    prefix = "report.reputationalRisks"
    raw_profile = _mapping(report.get("reputationalRisks"), prefix, record_number)
    positive = _map_reputation_signals(
        raw_profile.get("positive"),
        path=f"{prefix}.positive",
        polarity=ReputationPolarity.POSITIVE,
        record_number=record_number,
    )
    negative = _map_reputation_signals(
        raw_profile.get("negative"),
        path=f"{prefix}.negative",
        polarity=ReputationPolarity.NEGATIVE,
        record_number=record_number,
    )
    return ReputationProfile(positive=positive, negative=negative)


def _map_reputation_signals(
    value: object,
    *,
    path: str,
    polarity: ReputationPolarity,
    record_number: int,
) -> tuple[ReputationSignal, ...]:
    raw_signals = _sequence(value, path, record_number)
    results: list[ReputationSignal] = []
    for index, raw_signal in enumerate(raw_signals):
        prefix = f"{path}[{index}]"
        signal = _mapping(raw_signal, prefix, record_number)
        raw_code = _required_string(signal.get("code"), f"{prefix}.code", record_number)
        results.append(
            ReputationSignal(
                raw_code=raw_code,
                canonical_code=_canonical_reputation_code(raw_code),
                name=_required_string(signal.get("name"), f"{prefix}.name", record_number),
                chapter=_required_string(signal.get("chapter"), f"{prefix}.chapter", record_number),
                polarity=polarity,
            )
        )
    return tuple(results)


def _canonical_reputation_code(raw_code: str) -> str:
    aliases = {"аrbitrationDefendant": "arbitrationDefendant"}
    return aliases.get(raw_code, raw_code)
