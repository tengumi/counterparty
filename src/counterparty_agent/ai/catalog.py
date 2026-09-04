"""Разрешённый каталог фактов одной компании."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim
from counterparty_agent.analytics.common import AnalysisValidationError
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
            )
        )

    ledger = {item.evidence_id: item for item in analysis.derived_evidence}
    for finding in analysis.findings:
        attention = finding.severity is FindingSeverity.ATTENTION
        add(
            f"{'attention_signal' if attention else finding.code}:{finding.finding_id}",
            ("Отдельный сигнал внимания по данным отчёта:\n" if attention else "")
            + finding.statement,
            finding.evidence_ids,
            finding.period if isinstance(finding.period, int) else None,
            finding.code if attention else None,
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
                    else f"{label} за {finding.period}: {value} в единицах источника. "
                    "Валюта и масштаб единиц в источнике не указаны."
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

    if not any(item.severity is FindingSeverity.ATTENTION for item in analysis.findings):
        add(
            "attention_signal:none",
            "В выполненных проверках этого отчёта отдельных сигналов внимания не выявлено. "
            "Это не означает отсутствия риска или полноты данных и не объясняет "
            "банковский цвет. Причина банковской оценки остаётся неизвестной.",
            tuple(
                dict.fromkeys(key for finding in analysis.findings for key in finding.evidence_ids)
            ),
            metric="none",
        )

    report_evidence = next(item for item in snapshot.evidence if item.canonical_path == "report_at")
    add(
        "report_date",
        f"Дата отчёта: {snapshot.report_at.isoformat()}. "
        "Сведения относятся к этому снимку и не обновляются из интернета.",
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
        f"Банковский светофор на дату {bank.assessed_at.isoformat()}: "
        f"{bank.recognized_level.value} — {bank_labels[bank.recognized_level]}. "
        if bank.recognized_level is not None
        else "Банковская оценка отсутствует или не распознана; GREY показан как «нет данных». "
    )
    bank_text += (
        "Это готовый внешний сигнал закрытого банковского скоринга. Его методика и причины "
        "не раскрыты; агент не пересчитывает цвет. Цвет не гарантирует безопасность сделки."
        " Отдельные сигналы по данным отчёта — не объяснение банковского цвета."
    )
    add("bank_signal", bank_text, (analysis.bank_evidence_id,))
    return tuple(facts)
