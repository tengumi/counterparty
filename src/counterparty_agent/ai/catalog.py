"""Разрешённый каталог фактов одной компании."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from zoneinfo import ZoneInfo

from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim
from counterparty_agent.analytics.common import AnalysisValidationError, _money
from counterparty_agent.analytics.core import validate_analysis
from counterparty_agent.models import (
    AnalysisResult,
    BankTrafficLight,
    CounterpartySnapshot,
    FindingSeverity,
)


def build_fact_catalog(
    snapshot: CounterpartySnapshot, analysis: AnalysisResult
) -> tuple[ApprovedFact, ...]:
    """Собрать белый список после повторной проверки всех расчётов и lineage."""

    validate_analysis(analysis, snapshot)
    facts: list[ApprovedFact] = []

    def add(
        key: str,
        text: str,
        evidence_ids: tuple[str, ...],
        period: int | None = None,
        metric: str | None = None,
        signal_code: str | None = None,
    ) -> None:
        digest = hashlib.sha256(
            json.dumps([snapshot.snapshot_id, key, evidence_ids], ensure_ascii=False).encode()
        ).hexdigest()[:24]
        facts.append(
            ApprovedFact(
                f"fact_{digest}",
                GroundedClaim(text=text, evidence_ids=evidence_ids),
                key.split(":", 1)[0],
                period,
                metric,
                signal_code,
            )
        )

    ledger = {item.evidence_id: item for item in analysis.derived_evidence}
    latest_financial_year = max(
        (
            item.period
            for item in analysis.findings
            if item.code == "financial_period" and isinstance(item.period, int)
        ),
        default=None,
    )
    for finding in analysis.findings:
        attention = finding.severity is FindingSeverity.ATTENTION
        add(
            f"{'attention_signal' if attention else finding.code}:{finding.finding_id}",
            finding.statement,
            finding.evidence_ids,
            finding.period if isinstance(finding.period, int) else None,
            finding.code if attention else None,
            str(finding.period) if finding.code == "provider_negative_signal" else None,
        )
        if finding.code == "negative_equity":
            add(
                f"capital_status_boundary:{finding.period}",
                f"Отрицательный капитал за {finding.period} сам по себе не подтверждает "
                "банкротство компании. Это значение финансового показателя, не подтверждение "
                "юридического статуса. Наличие дела о банкротстве этим полем не установлено.",
                finding.evidence_ids,
                finding.period if isinstance(finding.period, int) else None,
                "capital_status_boundary",
            )
        if finding.code == "financial_period" and isinstance(finding.period, int):
            values = ledger[finding.evidence_ids[0]].typed_value
            for name, label in (
                ("proceeds", "Выручка"),
                ("profit", "Прибыль"),
                ("assets_total", "Активы"),
                ("liabilities_total", "Итог пассивов"),
                ("equity", "Капитал и резервы"),
            ):
                value = values[name]
                if value is not None and not isinstance(value, Decimal):
                    raise AnalysisValidationError("Финансовое доказательство имеет неверный тип")
                text = (
                    f"{label} за {finding.period}: нет данных в финансовом периоде отчёта."
                    if value is None
                    else f"{label} за {finding.period}: {_money(value)} рублей."
                )
                if name == "liabilities_total":
                    text += " Итог пассивов не равен сумме долга."
                add(
                    f"granular_metric:{finding.period}:{name}",
                    text,
                    finding.evidence_ids,
                    finding.period,
                    name,
                )
                if name == "profit" and value is not None and value < 0:
                    # Величина убытка — модуль отрицательной прибыли, а не смена её знака.
                    # Отдельное основание позволяет написать «убыток X» без вычисления LLM.
                    add(
                        f"granular_metric:{finding.period}:loss_amount",
                        f"Убыток за {finding.period}: {_money(abs(value))} рублей. "
                        "Это величина отрицательной прибыли, не положительная прибыль.",
                        finding.evidence_ids,
                        finding.period,
                        "loss_amount",
                    )
                if name == "proceeds" and value == 0 and finding.period == latest_financial_year:
                    add(
                        "financial_zero_revenue",
                        f"Выручка за последний доступный год ({finding.period}): 0 рублей. "
                        "Причина нулевого значения не указана. Оно не доказывает прекращение "
                        "работы компании и не определяет её прибыль.",
                        finding.evidence_ids,
                        finding.period,
                        "financial_zero_revenue",
                    )
                if name == "profit" and value is None and finding.period == latest_financial_year:
                    add(
                        "profitability_unknown",
                        f"Прибыль за {finding.period} в отчёте не указана. "
                        "Выручка не равна прибыли: даже большее значение выручки "
                        "не подтверждает прибыльность компании. Неизвестную прибыль "
                        "нельзя считать ни нулевой, ни положительной.",
                        finding.evidence_ids,
                        finding.period,
                        "profitability_unknown",
                    )

    if not any(item.severity is FindingSeverity.ATTENTION for item in analysis.findings):
        add(
            "attention_signal:none",
            "В выполненных проверках этого отчёта отдельных сигналов внимания не выявлено. "
            "Это не означает отсутствия риска или полноты данных.",
            tuple(
                dict.fromkeys(key for finding in analysis.findings for key in finding.evidence_ids)
            ),
            metric="none",
        )

    report_evidence = next(item for item in snapshot.evidence if item.canonical_path == "report_at")
    add(
        "report_date",
        f"Отчёт от {snapshot.report_at.astimezone(ZoneInfo('Europe/Moscow')):%d.%m.%Y}. "
        "Изменения после этой даты здесь не проверены.",
        (report_evidence.evidence_id,),
    )
    bank_labels = {
        BankTrafficLight.GREEN: "надёжный контрагент",
        BankTrafficLight.YELLOW: "требует внимания",
        BankTrafficLight.RED: "в зоне риска",
        BankTrafficLight.GREY: "нет данных для оценки",
    }
    bank = analysis.bank_risk
    bank_text = (
        f"Оценка в отчёте от {bank.assessed_at.astimezone(ZoneInfo('Europe/Moscow')):%d.%m.%Y}: "
        f"{bank_labels[bank.recognized_level]}. "
        if bank.recognized_level is not None
        else "Оценка в отчёте отсутствует. "
        if bank.raw_level is None
        else "Значение оценки в отчёте не распознано. "
    )
    add("bank_signal", bank_text.strip(), (analysis.bank_evidence_id,))
    add(
        "bank_signal:assessment_limits",
        "Самой оценки в отчёте недостаточно для подтверждения безопасности конкретной сделки. "
        "Она не гарантирует выполнение обязательств или получение оплаты. Другие сведения "
        "нужно рассматривать отдельно: они не пересчитывают оценку и не объясняют её причину.",
        (analysis.bank_evidence_id,),
        metric="assessment_limits",
    )
    add(
        "bank_signal:reason_unavailable",
        "Причина этой оценки в отчёте не указана."
        if bank.recognized_level is not None
        else "В отчёте нет распознанной оценки, причину её отсутствия определить нельзя.",
        (analysis.bank_evidence_id,),
        metric="reason_unavailable",
    )
    return tuple(facts)
