"""Запуск правил анализа и повторная проверка результата."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Context, localcontext

from counterparty_agent.analytics.common import AnalysisValidationError, _AnalysisBuilder
from counterparty_agent.analytics.company import _analyze_company
from counterparty_agent.analytics.finances import _analyze_finances
from counterparty_agent.analytics.legal import (
    _analyze_arbitration,
    _analyze_enforcement,
    _analyze_licenses,
    _analyze_reputation,
)
from counterparty_agent.models import (
    AnalysisPolicy,
    AnalysisResult,
    CounterpartySnapshot,
    EvidenceKind,
)


def analyze_snapshot(
    snapshot: CounterpartySnapshot,
    *,
    evaluated_at: datetime,
    policy: AnalysisPolicy | None = None,
) -> AnalysisResult:
    """Проанализировать снимок на явно заданную дату; сеть и часы не используются."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise AnalysisValidationError("Дата анализа должна содержать часовой пояс")
    selected_policy = policy if policy is not None else AnalysisPolicy()
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        builder = _AnalysisBuilder(snapshot)
        _analyze_company(builder, evaluated_at.astimezone(UTC), selected_policy)
        _analyze_finances(builder)
        _analyze_arbitration(builder)
        _analyze_enforcement(builder)
        _analyze_reputation(builder)
        _analyze_licenses(builder)
        bank_evidence = builder.inputs(
            "bank_risk", (snapshot.bank_risk.model_dump(mode="python"),)
        )[0]
        result = AnalysisResult(
            company_id=snapshot.company_id,
            snapshot_id=snapshot.snapshot_id,
            report_at=snapshot.report_at,
            evaluated_at=evaluated_at.astimezone(UTC),
            policy=selected_policy,
            bank_risk=snapshot.bank_risk,
            bank_evidence_id=bank_evidence.evidence_id,
            findings=tuple(builder.findings),
            derived_evidence=tuple(builder.derived),
        )
        _validate_references(result, snapshot)
        return result


def validate_analysis(result: AnalysisResult, snapshot: CounterpartySnapshot) -> None:
    """Проверить ссылки и повторить правила, обнаруживая подмену текста и значений.

    Это валидатор детерминированных findings, не универсальная проверка прозы LLM
    и не подтверждение истинности данных поставщика.
    """

    _validate_references(result, snapshot)
    expected = analyze_snapshot(snapshot, evaluated_at=result.evaluated_at, policy=result.policy)
    if result != expected:
        raise AnalysisValidationError("Результат не соответствует версии правил и исходному снимку")


def _validate_references(result: AnalysisResult, snapshot: CounterpartySnapshot) -> None:
    if (
        result.company_id != snapshot.company_id
        or result.snapshot_id != snapshot.snapshot_id
        or result.report_at != snapshot.report_at
        or result.bank_risk != snapshot.bank_risk
    ):
        raise AnalysisValidationError("Нарушена область анализа или изменён банковский сигнал")
    observed = {item.evidence_id: item for item in snapshot.evidence}
    derived = {item.evidence_id: item for item in result.derived_evidence}
    if len(observed) != len(snapshot.evidence) or len(derived) != len(result.derived_evidence):
        raise AnalysisValidationError("Повтор идентификатора доказательства")
    if observed.keys() & derived.keys():
        raise AnalysisValidationError("Производное доказательство заменяет исходное")
    bank = observed.get(result.bank_evidence_id)
    if bank is None or bank.canonical_path != "bank_risk":
        raise AnalysisValidationError("Нет исходного доказательства банковского сигнала")
    for evidence in result.derived_evidence:
        if (
            evidence.kind is not EvidenceKind.DERIVED
            or not evidence.derived_from
            or evidence.company_id != snapshot.company_id
            or evidence.snapshot_id != snapshot.snapshot_id
            or evidence.source_hash != snapshot.source_hash
            or evidence.record_hash != snapshot.record_hash
            or evidence.report_at != snapshot.report_at
            or evidence.source_name != snapshot.source_name
        ):
            raise AnalysisValidationError("Неверное происхождение производного доказательства")
        if any(parent not in observed for parent in evidence.derived_from):
            raise AnalysisValidationError("Производное доказательство содержит неизвестную ссылку")
        expected_paths = {
            path for parent in evidence.derived_from for path in observed[parent].source_paths
        }
        if set(evidence.source_paths) != expected_paths:
            raise AnalysisValidationError("Исходные пути не совпадают с lineage")
    all_ids = observed.keys() | derived.keys()
    for finding in result.findings:
        if (
            finding.company_id != snapshot.company_id
            or finding.snapshot_id != snapshot.snapshot_id
            or not finding.evidence_ids
            or any(identifier not in all_ids for identifier in finding.evidence_ids)
        ):
            raise AnalysisValidationError(
                "Вывод содержит доказательство другой области или без ссылки"
            )
