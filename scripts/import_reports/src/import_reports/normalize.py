"""Turning one source record into the rows of the ``reports`` schema.

This module is pure: it reads a decoded record and returns row payloads and
diagnostics. It opens nothing, writes nothing and decides nothing about
transactions, so every rule below is testable without a database.

Four rules shape it:

* absence, emptiness, a reported zero and an unparsable value stay four
  different observations. A column is ``NULL`` for all but the zero, and
  ``section_availability`` says which one it was;
* nothing is guessed. ``entity_type`` is not derived from the length of the
  INN, a missing year is not filled from the neighbouring period, and an
  external token (``riskLevel``, ``status``, ``zskRiskLevel``) is stored as
  provided;
* whatever the typed columns do not carry is kept — the remainder of a block in
  ``extra_jsonb``, the whole ``report`` in ``raw_jsonb`` — and whatever is not
  understood becomes a diagnostic instead of a default;
* every child row names the RFC 6901 path it came from, so evidence resolves
  back into the source object.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from counterparty_contracts import WarningCode
from counterparty_domain.identifiers import validate_inn, validate_ogrn
from counterparty_storage.reports import IngestionStatus, SourceState, WarningSeverity

from .diagnostics import Diagnostic, diagnostic
from .extended_json import (
    FieldProbe,
    decode,
    json_pointer,
    probe_field,
    probe_section,
)
from .fingerprint import canonical_json, snapshot_digest
from .inspection import REPORT_SECTIONS

__all__ = [
    "FAILURE_SOURCE_PATH",
    "FINANCIAL_COLUMNS",
    "ZSK_DISPLAY_POLICY_VERSION",
    "FailedRecord",
    "NormalizedSnapshot",
    "normalize",
]

#: Version of the ZSK presentation policy in force when a row was written. It
#: is bookkeeping, not a score: the methodology is closed, so nothing here maps
#: a token to a colour. Stored so a later policy change stays distinguishable
#: from a change in the source.
ZSK_DISPLAY_POLICY_VERSION: Final = "zsk-display/1"

#: Pointer used when a record failed before any field could be addressed.
FAILURE_SOURCE_PATH: Final = "/report"

#: ``financial_statements`` column -> path inside one ``finReports`` element,
#: exactly as fixed by Specs §02. ``totalLiabilities`` is the balance total of
#: the liabilities side and ``capitals`` is reported equity; neither is a debt
#: amount, and neither is the share capital.
FINANCIAL_COLUMNS: Final[Mapping[str, tuple[str, ...]]] = {
    "proceeds": ("common", "proceeds"),
    "profit": ("common", "profit"),
    "total_assets": ("assets", "totalAssets"),
    "current_assets": ("assets", "currentAssets", "total"),
    "stocks": ("assets", "currentAssets", "stocks"),
    "receivables": ("assets", "currentAssets", "receivables"),
    "cash": ("assets", "currentAssets", "bankroll"),
    "noncurrent_assets": ("assets", "uncurrentAssets", "total"),
    "fixed_assets": ("assets", "uncurrentAssets", "fixedAssets"),
    "balance_total_liabilities_side": ("liabilities", "totalLiabilities"),
    "equity": ("liabilities", "capitals"),
    "long_term_total": ("liabilities", "longTermDuties", "total"),
    "long_term_other": ("liabilities", "longTermDuties", "others"),
    "short_term_total": ("liabilities", "shortTermLiabilities", "total"),
    "short_term_borrowed": ("liabilities", "shortTermLiabilities", "borrowedFunds"),
    "accounts_payable": ("liabilities", "shortTermLiabilities", "accountsPayable"),
}

_BASE_INFO_CONSUMED: Final = frozenset(
    {
        "inn",
        "ogrn",
        "shortName",
        "fullName",
        "kpp",
        "okpo",
        "address",
        "email",
        "website",
        "companySize",
        "riskLevel",
        "registrationInfo",
    }
)
_REGISTRATION_CONSUMED: Final = frozenset({"registrationDate", "yearsFromRegistration"})
_STATUS_CONSUMED: Final = frozenset({"status", "date", "reasonName"})
_FINANCIAL_GROUPS: Final = frozenset({"common", "assets", "liabilities"})

#: Tokens whose ZSK presentation is confirmed. Everything else is kept and
#: reported, never read as the favourable one.
_ZSK_CONFIRMED: Final = frozenset({"GREEN"})


@dataclass(frozen=True, slots=True)
class NormalizedSnapshot:
    """Row payloads of one snapshot, ready to be written in one transaction."""

    source_record_id: str
    source_record_jsonb: dict[str, Any]
    source_report_at: datetime
    hash: str
    raw_jsonb: dict[str, Any]
    ingestion_status: IngestionStatus
    inn: str
    ogrn: str | None
    profile: dict[str, Any]
    status: dict[str, Any]
    activities: tuple[dict[str, Any], ...]
    financials: tuple[dict[str, Any], ...]
    zsk: dict[str, Any]
    availability: tuple[dict[str, Any], ...]
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class FailedRecord:
    """A record that could not be stored as a snapshot at all.

    It is not dropped: the diagnostics say why, addressed by whatever identity
    the record still carried.
    """

    source_record_id: str | None
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)


def _json_safe(value: object, path: str, collected: list[Diagnostic]) -> Any:
    """Render a source value as something JSONB can hold without distorting it.

    The approved file carries no fractional number, so this never fires on it.
    If one ever appears, an exact integer stays an integer and anything else
    becomes its exact decimal text with a warning, rather than being pushed
    through a binary float.
    """
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, path + json_pointer(str(key)), collected)
            for key, item in value.items()
        }
    if isinstance(value, str | bytes):
        return value.decode() if isinstance(value, bytes) else value
    if isinstance(value, Sequence):
        return [
            _json_safe(item, path + json_pointer(index), collected)
            for index, item in enumerate(value)
        ]
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        collected.append(
            diagnostic(
                WarningCode.PRECISION_REDUCED,
                "a fractional source number is stored as its exact decimal text in JSONB",
                severity=WarningSeverity.INFO,
                source_path=path or None,
                kind="decimal_as_text",
            )
        )
        return format(value, "f")
    if isinstance(value, float):
        collected.append(
            diagnostic(
                WarningCode.PARSE_FAILED,
                "a binary float reached the writer; it is stored as text rather than as money",
                severity=WarningSeverity.ERROR,
                source_path=path or None,
                kind="unsupported_float",
            )
        )
        return repr(value)
    return value


def _decode_diagnostics(issues: Sequence[Any]) -> list[Diagnostic]:
    """Map decoder issues onto the published warning vocabulary."""
    mapped: list[Diagnostic] = []
    for issue in issues:
        code = (
            WarningCode.UNSPECIFIED
            if issue.code.value == "unknown_wrapper"
            else WarningCode.PARSE_FAILED
        )
        mapped.append(
            diagnostic(
                code,
                issue.detail,
                severity=WarningSeverity.ERROR,
                source_path=issue.source_path or None,
                kind=issue.code.value,
            )
        )
    return mapped


def _text(probe: FieldProbe) -> str | None:
    """Return a present string value, or ``None`` for anything else."""
    value = probe.as_value()
    return value if isinstance(value, str) else None


def _integer(probe: FieldProbe) -> int | None:
    """Return a present whole number, or ``None``. ``True`` is not a number."""
    value = probe.as_value()
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    return None


def _instant(probe: FieldProbe) -> datetime | None:
    """Return a present timestamp, or ``None``."""
    value = probe.as_value()
    return value if isinstance(value, datetime) else None


def _unreadable(probe: FieldProbe, expected: str, collected: list[Diagnostic]) -> None:
    """Record that a field was present but could not be read as its type."""
    collected.append(
        diagnostic(
            WarningCode.PARSE_FAILED,
            f"{probe.source_path} is present but is not a readable {expected}",
            severity=WarningSeverity.ERROR,
            source_path=probe.source_path,
            state=probe.state.value,
        )
    )


def _extras(raw: object, consumed: frozenset[str], path: str, collected: list[Diagnostic]) -> Any:
    """Return whatever the typed columns of a block did not take."""
    if not isinstance(raw, Mapping):
        return {}
    remainder = {str(key): item for key, item in raw.items() if str(key) not in consumed}
    return _json_safe(remainder, path, collected)


def _amount(
    element: object, column: str, keys: tuple[str, ...], base: str, collected: list[Diagnostic]
) -> Decimal | None:
    probe = probe_field(element, *keys, base_path=base)
    if not probe.is_present:
        return None
    amount = probe.as_decimal()
    if amount is None:
        _unreadable(probe, f"amount for {column}", collected)
    return amount


def _normalize_activities(report: object, collected: list[Diagnostic]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    main = probe_field(report, "kindsOfActivityInfo", "mainKindOfActivity")
    if main.is_present:
        rows.append(
            {
                "ordinal": 0,
                "code": _text(probe_field(main.value, "code", base_path=main.source_path)),
                "description": _text(
                    probe_field(main.value, "description", base_path=main.source_path)
                ),
                "is_primary": True,
                "source_path": main.source_path,
            }
        )
    others = probe_section(report, "kindsOfActivityInfo", "otherKindsOfActivity")
    for index, element in enumerate(others.records):
        path = f"{others.source_path}{json_pointer(index)}"
        rows.append(
            {
                "ordinal": len(rows),
                "code": _text(probe_field(element, "code", base_path=path)),
                "description": _text(probe_field(element, "description", base_path=path)),
                "is_primary": False,
                "source_path": path,
            }
        )
    for row in rows:
        if row["code"] is None and row["description"] is None:
            collected.append(
                diagnostic(
                    WarningCode.PARSE_FAILED,
                    "an activity entry carries neither a code nor a description",
                    severity=WarningSeverity.ERROR,
                    source_path=row["source_path"],
                )
            )
    return rows


def _normalize_financials(report: object, collected: list[Diagnostic]) -> list[dict[str, Any]]:
    section = probe_section(report, "finReports")
    rows: list[dict[str, Any]] = []
    years: dict[int, str] = {}
    for index, element in enumerate(section.records):
        path = f"{section.source_path}{json_pointer(index)}"
        year_probe = probe_field(element, "common", "year", base_path=path)
        year = _integer(year_probe)
        if year is None:
            # The array position is not the period. Without a year the row
            # cannot be addressed, so it is reported rather than guessed.
            severity = WarningSeverity.ERROR if year_probe.is_present else WarningSeverity.WARNING
            code = WarningCode.PARSE_FAILED if year_probe.is_present else WarningCode.SOURCE_MISSING
            collected.append(
                diagnostic(
                    code,
                    "a financial period without a readable year is not stored as a period",
                    severity=severity,
                    source_path=year_probe.source_path,
                    ordinal=index,
                )
            )
            continue
        if year in years:
            collected.append(
                diagnostic(
                    WarningCode.PERIOD_AMBIGUOUS,
                    f"more than one financial period claims {year}; "
                    f"the first one at {years[year]} is kept and this one is not stored",
                    severity=WarningSeverity.ERROR,
                    source_path=path,
                    year=year,
                    kept_source_path=years[year],
                )
            )
            continue
        years[year] = path
        row: dict[str, Any] = {"year": year, "ordinal": index, "source_path": path}
        for column, keys in FINANCIAL_COLUMNS.items():
            row[column] = _amount(element, column, keys, path, collected)
        extras: dict[str, Any] = {}
        for group in sorted(_FINANCIAL_GROUPS):
            leftover = _extras(
                probe_field(element, group, base_path=path).as_value(),
                _consumed_in(group),
                f"{path}{json_pointer(group)}",
                collected,
            )
            if leftover:
                extras[group] = leftover
        row["extra_jsonb"] = extras
        rows.append(row)
    return rows


def _consumed_in(group: str) -> frozenset[str]:
    """First-level keys of one ``finReports`` group that typed columns take."""
    return frozenset(keys[1] for keys in FINANCIAL_COLUMNS.values() if keys[0] == group) | (
        frozenset({"year"}) if group == "common" else frozenset()
    )


def _normalize_availability(report: object, collected: list[Diagnostic]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in REPORT_SECTIONS:
        probe = probe_section(report, section)
        rows.append(
            {
                "section": section,
                "source_state": probe.state,
                "record_count": probe.record_count,
                "source_path": probe.source_path,
                "warnings_jsonb": (
                    {"issue": probe.issue.code.value, "detail": probe.issue.detail}
                    if probe.issue is not None
                    else {}
                ),
            }
        )
    if isinstance(report, Mapping):
        for key in report:
            if str(key) not in REPORT_SECTIONS:
                collected.append(
                    diagnostic(
                        WarningCode.UNSPECIFIED,
                        f"the source carries a report section this import does not map: {key}",
                        severity=WarningSeverity.WARNING,
                        source_path=json_pointer(str(key)),
                        kind="unknown_section",
                        section=str(key),
                    )
                )
    return rows


def _ingestion_status(
    collected: Sequence[Diagnostic], availability: Sequence[Mapping[str, Any]]
) -> IngestionStatus:
    """Say how completely the snapshot normalized.

    ``complete`` means every recognized section normalized. ``partial`` means
    the raw snapshot is trustworthy but at least one section is not.
    ``invalid`` is kept for a snapshot whose identity sections are unusable, so
    that nothing typed is served from it.
    """
    identity = {
        row["section"]: row["source_state"]
        for row in availability
        if row["section"] in {"baseInfo", "status"}
    }
    if identity and all(state is SourceState.INVALID for state in identity.values()):
        return IngestionStatus.INVALID
    if any(item.is_error for item in collected):
        return IngestionStatus.PARTIAL
    return IngestionStatus.COMPLETE


def _identifier_diagnostics(inn: str, ogrn: str | None, collected: list[Diagnostic]) -> None:
    """Report a registry identifier that does not validate, never repair it."""
    inn_check = validate_inn(inn)
    if not inn_check.is_valid:
        collected.append(
            diagnostic(
                WarningCode.UNSPECIFIED,
                "the reported INN does not pass format or checksum validation; "
                "it is stored as provided and the record is not dropped",
                severity=WarningSeverity.WARNING,
                source_path="/baseInfo/inn",
                kind="identifier_invalid",
                identifier="inn",
                problems=[problem.value for problem in inn_check.problems],
            )
        )
    if ogrn is None:
        return
    ogrn_check = validate_ogrn(ogrn)
    if not ogrn_check.is_valid:
        collected.append(
            diagnostic(
                WarningCode.UNSPECIFIED,
                "the reported OGRN does not pass format or checksum validation; "
                "it is stored as provided",
                severity=WarningSeverity.WARNING,
                source_path="/baseInfo/ogrn",
                kind="identifier_invalid",
                identifier="ogrn",
                problems=[problem.value for problem in ogrn_check.problems],
            )
        )


def _zsk_row(report: object, collected: list[Diagnostic]) -> dict[str, Any]:
    probe = probe_field(report, "zskRiskLevel")
    raw_value = _text(probe)
    if probe.is_present and raw_value is None:
        _unreadable(probe, "external ZSK token", collected)
    if raw_value is not None and raw_value not in _ZSK_CONFIRMED:
        collected.append(
            diagnostic(
                WarningCode.UNKNOWN_ENUM_VALUE,
                f"the ZSK token {raw_value!r} has no confirmed presentation mapping; "
                "it is stored verbatim and must not be read as a favourable signal",
                severity=WarningSeverity.INFO,
                source_path=probe.source_path,
                raw_value=raw_value,
                policy_version=ZSK_DISPLAY_POLICY_VERSION,
            )
        )
    return {
        "raw_value": raw_value,
        "display_policy_version": ZSK_DISPLAY_POLICY_VERSION,
        "source_path": probe.source_path,
    }


def _identity_diagnostics(
    identifier: object, report: object, ogrn: str | None, collected: list[Diagnostic]
) -> None:
    """Check that ``_id`` agrees with the report it is attached to."""
    id_ogrn = _text(probe_field(identifier, "ogrn"))
    if id_ogrn is not None and ogrn is not None and id_ogrn != ogrn:
        collected.append(
            diagnostic(
                WarningCode.AGGREGATE_MISMATCH,
                "the record key names a different OGRN than the report body does",
                severity=WarningSeverity.WARNING,
                source_path="/baseInfo/ogrn",
                kind="identity_mismatch",
                record_key_ogrn=id_ogrn,
                report_ogrn=ogrn,
            )
        )
    id_date = _instant(probe_field(identifier, "date"))
    report_date = _instant(probe_field(report, "reportDate"))
    if id_date is not None and report_date is not None and id_date != report_date:
        collected.append(
            diagnostic(
                WarningCode.AGGREGATE_MISMATCH,
                "the record key names a different report date than the report body does",
                severity=WarningSeverity.WARNING,
                source_path="/reportDate",
                kind="identity_mismatch",
                record_key_date=id_date.isoformat(),
                report_date=report_date.isoformat(),
            )
        )


def normalize(record: object) -> NormalizedSnapshot | FailedRecord:
    """Turn one raw source record into row payloads, or say why it cannot be.

    ``record`` is the record exactly as read from the file: the hash and the
    stored raw JSONB are taken from it before decoding, so neither depends on
    the version of this parser.
    """
    collected: list[Diagnostic] = []
    raw_identifier = probe_field(record, "_id").as_value()
    source_record_id = (
        canonical_json(raw_identifier) if isinstance(raw_identifier, Mapping) else None
    )
    raw_report = probe_field(record, "report").as_value()
    if not isinstance(raw_report, Mapping):
        collected.append(
            diagnostic(
                WarningCode.PARSE_FAILED,
                "the record carries no usable report object and cannot be stored as a snapshot",
                severity=WarningSeverity.ERROR,
                source_path=FAILURE_SOURCE_PATH,
                kind="record_unusable",
            )
        )
        return FailedRecord(source_record_id=source_record_id, diagnostics=tuple(collected))

    decoded = decode(record)
    collected.extend(_decode_diagnostics(decoded.issues))
    report = probe_field(decoded.value, "report").as_value()
    identifier = probe_field(decoded.value, "_id").as_value()

    inn_probe = probe_field(report, "baseInfo", "inn")
    inn = _text(inn_probe)
    report_at = _instant(probe_field(report, "reportDate"))
    if inn is None or report_at is None:
        collected.append(
            diagnostic(
                WarningCode.PARSE_FAILED,
                "a snapshot needs a reported INN and a report date; "
                f"inn={inn_probe.state.value}, reportDate="
                f"{probe_field(report, 'reportDate').state.value}",
                severity=WarningSeverity.ERROR,
                source_path=FAILURE_SOURCE_PATH,
                kind="identity_missing",
            )
        )
        return FailedRecord(source_record_id=source_record_id, diagnostics=tuple(collected))

    base_info = probe_field(report, "baseInfo").as_value()
    ogrn = _text(probe_field(report, "baseInfo", "ogrn"))
    _identifier_diagnostics(inn, ogrn, collected)
    _identity_diagnostics(identifier, report, ogrn, collected)

    registration = probe_field(report, "baseInfo", "registrationInfo")
    registration_extras = _extras(
        registration.as_value(),
        _REGISTRATION_CONSUMED,
        registration.source_path,
        collected,
    )
    profile_extras: dict[str, Any] = _extras(base_info, _BASE_INFO_CONSUMED, "/baseInfo", collected)
    if registration_extras:
        profile_extras["registrationInfo"] = registration_extras

    profile = {
        "short_name": _text(probe_field(report, "baseInfo", "shortName")),
        "full_name": _text(probe_field(report, "baseInfo", "fullName")),
        "kpp": _text(probe_field(report, "baseInfo", "kpp")),
        "okpo": _text(probe_field(report, "baseInfo", "okpo")),
        "address": _text(probe_field(report, "baseInfo", "address")),
        "registration_date": _instant(
            probe_field(report, "baseInfo", "registrationInfo", "registrationDate")
        ),
        "years_from_registration": _integer(
            probe_field(report, "baseInfo", "registrationInfo", "yearsFromRegistration")
        ),
        "email": _text(probe_field(report, "baseInfo", "email")),
        "website": _text(probe_field(report, "baseInfo", "website")),
        "company_size": _text(probe_field(report, "baseInfo", "companySize")),
        "bank_risk_raw": _text(probe_field(report, "baseInfo", "riskLevel")),
        "extra_jsonb": profile_extras,
    }

    status = {
        "status_raw": _text(probe_field(report, "status", "status")),
        "status_date": _instant(probe_field(report, "status", "date")),
        "reason_raw": _text(probe_field(report, "status", "reasonName")),
        "extra_jsonb": _extras(
            probe_field(report, "status").as_value(), _STATUS_CONSUMED, "/status", collected
        ),
    }

    availability = _normalize_availability(report, collected)
    activities = tuple(_normalize_activities(report, collected))
    financials = tuple(_normalize_financials(report, collected))
    zsk = _zsk_row(report, collected)
    raw_identifier_jsonb = _json_safe(raw_identifier, "", collected)
    raw_report_jsonb = _json_safe(raw_report, "", collected)

    # Computed last on purpose: the status has to see every diagnostic the
    # sections above produced, not only the ones raised while reading identity.
    ingestion_status = _ingestion_status(collected, availability)

    return NormalizedSnapshot(
        source_record_id=source_record_id or canonical_json(None),
        source_record_jsonb=(
            raw_identifier_jsonb if isinstance(raw_identifier_jsonb, dict) else {}
        ),
        source_report_at=report_at,
        hash=snapshot_digest(record),
        raw_jsonb=raw_report_jsonb,
        ingestion_status=ingestion_status,
        inn=inn,
        ogrn=ogrn,
        profile=profile,
        status=status,
        activities=activities,
        financials=financials,
        zsk=zsk,
        availability=tuple(availability),
        diagnostics=tuple(collected),
    )
