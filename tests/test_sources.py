"""Интеграционные проверки JSON-источника на выданном реальном snapshot."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from counterparty_agent.config import Settings
from counterparty_agent.data.identifiers import (
    is_valid_inn,
    is_valid_ogrn,
    parse_bank_traffic_light,
)
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import (
    BankRiskAssessment,
    BankTrafficLight,
    EvidenceCoverage,
    PartyType,
    ResolutionStatus,
    SourceOutcome,
)

EXPECTED_SOURCE_HASH = "34bdf82e3286bfbb1c2b0e4d441dde25c90fd58b1d623d6192f2653dd6641f55"


@pytest.fixture(scope="module")
def source() -> JsonCounterpartySource:
    """Загрузить локально настроенный snapshot, не копируя его в репозиторий."""

    snapshot_path = Path(Settings().snapshot_json_path)
    if not snapshot_path.is_file():
        pytest.skip("Реальный snapshot не настроен в COUNTERPARTY_SNAPSHOT_JSON_PATH")
    return JsonCounterpartySource.from_path(snapshot_path)


def test_real_snapshot_is_loaded_completely(source: JsonCounterpartySource) -> None:
    assert source.outcome is SourceOutcome.SUCCESS
    assert source.source_hash == EXPECTED_SOURCE_HASH
    assert len(source.snapshots) == 100

    party_types = Counter(snapshot.identity.party_type for snapshot in source.snapshots)
    assert party_types == {
        PartyType.LEGAL_ENTITY: 75,
        PartyType.INDIVIDUAL_ENTREPRENEUR: 25,
    }


def test_optional_sections_preserve_missing_and_empty(
    source: JsonCounterpartySource,
) -> None:
    statements_missing = sum(item.financial_statements is None for item in source.snapshots)
    statements_empty = sum(item.financial_statements == () for item in source.snapshots)
    arbitration_missing = sum(item.arbitration_by_year is None for item in source.snapshots)
    enforcement_empty = sum(not item.enforcement_proceedings for item in source.snapshots)
    licenses_missing = sum(item.licenses is None for item in source.snapshots)

    assert statements_missing == 25
    assert statements_empty == 8
    assert arbitration_missing == 56
    assert enforcement_empty == 47
    assert licenses_missing == 91

    for index, snapshot in enumerate(source.snapshots, start=1):
        if snapshot.identity.party_type is PartyType.INDIVIDUAL_ENTREPRENEUR:
            gap = next(
                evidence
                for evidence in snapshot.evidence
                if evidence.canonical_path == "financial_statements"
            )
            if gap.coverage is not EvidenceCoverage.NOT_APPLICABLE:
                pytest.fail(f"Неверная применимость финансов у записи {index}")


def test_extended_json_is_decoded_and_money_is_decimal(
    source: JsonCounterpartySource,
) -> None:
    decimal_count = 0
    for record_index, snapshot in enumerate(source.snapshots, start=1):
        if _contains_extended_json(snapshot.report):
            pytest.fail(f"Extended JSON остался в записи {record_index}")
        if snapshot.report_at.tzinfo is None or snapshot.status.effective_at.tzinfo is None:
            pytest.fail(f"Дата без часового пояса в записи {record_index}")

        for statement in snapshot.financial_statements or ():
            values = (
                statement.proceeds,
                statement.profit,
                statement.assets.total,
                statement.assets.current_total,
                statement.assets.stocks,
                statement.assets.receivables,
                statement.assets.cash_and_equivalents,
                statement.assets.non_current_total,
                statement.assets.fixed_assets,
                statement.liabilities.total,
                statement.liabilities.capital_and_reserves,
                statement.liabilities.long_term_total,
                statement.liabilities.other_long_term,
                statement.liabilities.short_term_total,
                statement.liabilities.borrowed_funds,
                statement.liabilities.accounts_payable,
            )
            for value in values:
                if value is not None:
                    decimal_count += 1
                    if not isinstance(value, Decimal):
                        pytest.fail(f"Денежное поле не Decimal в записи {record_index}")

        for proceeding in snapshot.enforcement_proceedings:
            if proceeding.opened_at.tzinfo is None:
                pytest.fail(f"Дата производства без часового пояса в записи {record_index}")
            if proceeding.amount is not None and not isinstance(proceeding.amount, Decimal):
                pytest.fail(f"Сумма производства не Decimal в записи {record_index}")

    assert decimal_count > 0


def test_known_source_aliases_are_canonicalized(source: JsonCounterpartySource) -> None:
    non_current_values = sum(
        statement.assets.non_current_total is not None
        for snapshot in source.snapshots
        for statement in snapshot.financial_statements or ()
    )
    defendant_counts = sum(
        (snapshot.arbitration_summary.as_defendant.finished_count or 0)
        + (snapshot.arbitration_summary.as_defendant.pending_count or 0)
        + (snapshot.arbitration_summary.as_defendant.appealed_count or 0)
        for snapshot in source.snapshots
    )
    normalized_codes = [
        signal
        for snapshot in source.snapshots
        for signal in (*snapshot.reputation.positive, *snapshot.reputation.negative)
        if signal.raw_code != signal.canonical_code
    ]

    assert non_current_values > 0
    assert defendant_counts > 0
    assert normalized_codes
    assert all(signal.canonical_code == "arbitrationDefendant" for signal in normalized_codes)


def test_bank_traffic_light_is_preserved_without_recalculation(
    source: JsonCounterpartySource,
) -> None:
    levels = Counter(snapshot.bank_risk.raw_level for snapshot in source.snapshots)
    assert levels == {"GREEN": 81, "YELLOW": 18, "RED": 1}

    for index, snapshot in enumerate(source.snapshots, start=1):
        risk = snapshot.bank_risk
        if risk.recognized_level is None:
            if risk.display_level is not BankTrafficLight.GREY:
                pytest.fail(f"Некорректный fallback светофора в записи {index}")
        elif risk.display_level is not risk.recognized_level:
            pytest.fail(f"Банковский цвет изменён в записи {index}")

    assert parse_bank_traffic_light("FUTURE_SOURCE_VALUE") is None
    unknown = BankRiskAssessment(
        raw_level="FUTURE_SOURCE_VALUE",
        recognized_level=None,
        display_level=BankTrafficLight.GREY,
        assessed_at=source.snapshots[0].report_at,
    )
    assert unknown.raw_level == "FUTURE_SOURCE_VALUE"

    with pytest.raises(ValidationError):
        BankRiskAssessment(
            raw_level="RED",
            recognized_level=BankTrafficLight.GREEN,
            display_level=BankTrafficLight.GREEN,
            assessed_at=source.snapshots[0].report_at,
        )


def test_identifiers_pass_checksums_and_resolve_exactly(
    source: JsonCounterpartySource,
) -> None:
    for index, snapshot in enumerate(source.snapshots, start=1):
        identity = snapshot.identity
        if not is_valid_inn(identity.inn) or not is_valid_ogrn(identity.ogrn):
            pytest.fail(f"Некорректная контрольная сумма в записи {index}")

        by_inn = source.find_by_inn(identity.inn)
        by_ogrn = source.find_by_ogrn(identity.ogrn)
        for result in (by_inn, by_ogrn):
            if result.status is not ResolutionStatus.RESOLVED:
                pytest.fail(f"Точный идентификатор не разрешён для записи {index}")
            if result.candidates[0].snapshot_id != snapshot.snapshot_id:
                pytest.fail(f"Точный поиск вернул другую запись для индекса {index}")

    first = source.snapshots[0]
    assert source.find_by_inn(f"ИНН {first.identity.inn}").status is (
        ResolutionStatus.INVALID_IDENTIFIER
    )
    assert source.find_by_ogrn(f"ОГРН {first.identity.ogrn}").status is (
        ResolutionStatus.INVALID_IDENTIFIER
    )
    assert source.find_by_inn(_change_checksum(first.identity.inn)).status is (
        ResolutionStatus.INVALID_IDENTIFIER
    )
    assert source.find_by_ogrn(_change_checksum(first.identity.ogrn)).status is (
        ResolutionStatus.INVALID_IDENTIFIER
    )


def test_exact_name_search_never_hides_ambiguity(source: JsonCounterpartySource) -> None:
    ambiguous_results = 0
    for index, snapshot in enumerate(source.snapshots, start=1):
        for name in {snapshot.identity.full_name, snapshot.identity.short_name}:
            result = source.find_by_name_exact(name)
            if snapshot.snapshot_id not in {
                candidate.snapshot_id for candidate in result.candidates
            }:
                pytest.fail(f"Название не нашло исходную запись {index}")
            if result.status is ResolutionStatus.AMBIGUOUS:
                ambiguous_results += 1
            elif result.status is not ResolutionStatus.RESOLVED:
                pytest.fail(f"Неожиданный статус точного названия у записи {index}")

    assert ambiguous_results > 0


def test_evidence_has_provenance_and_raw_report_is_not_serialized(
    source: JsonCounterpartySource,
) -> None:
    for index, snapshot in enumerate(source.snapshots, start=1):
        serialized = snapshot.model_dump()
        if "report" in serialized or "evidence" in serialized:
            pytest.fail(f"Raw или полный evidence сериализован для записи {index}")
        if not snapshot.evidence:
            pytest.fail(f"Нет evidence у записи {index}")

        evidence_ids = {item.evidence_id for item in snapshot.evidence}
        if len(evidence_ids) != len(snapshot.evidence):
            pytest.fail(f"Повтор evidence_id в записи {index}")
        for item in snapshot.evidence:
            if item.company_id != snapshot.company_id:
                pytest.fail(f"Evidence относится к другой компании в записи {index}")
            if item.snapshot_id != snapshot.snapshot_id:
                pytest.fail(f"Evidence относится к другому snapshot в записи {index}")
            if item.source_hash != source.source_hash:
                pytest.fail(f"Evidence содержит другой source hash в записи {index}")
            if not all(path.startswith("/") for path in item.source_paths):
                pytest.fail(f"Evidence содержит не JSON Pointer в записи {index}")
            if "typed_value" in item.model_dump():
                pytest.fail(f"Значение evidence сериализовано для записи {index}")


def _contains_extended_json(value: object) -> bool:
    if isinstance(value, list):
        return any(_contains_extended_json(item) for item in value)
    if isinstance(value, dict):
        if set(value) in ({"$date"}, {"$numberLong"}, {"$numberDecimal"}, {"$oid"}):
            return True
        return any(_contains_extended_json(item) for item in value.values())
    return False


def _change_checksum(identifier: str) -> str:
    replacement = str((int(identifier[-1]) + 1) % 10)
    return f"{identifier[:-1]}{replacement}"
