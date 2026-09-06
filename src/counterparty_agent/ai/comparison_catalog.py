"""Каталог тем и проверенных ответов по всей группе."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal

from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim
from counterparty_agent.analytics.comparison import validate_comparison
from counterparty_agent.analytics.core import validate_analysis
from counterparty_agent.models import (
    AnalysisResult,
    ComparisonResult,
    CounterpartySnapshot,
    FindingDataStatus,
)


def build_enforcement_focus(
    snapshots: Sequence[CounterpartySnapshot], analyses: Sequence[AnalysisResult]
) -> ApprovedFact | None:
    """Сравнить один явный критерий; число записей не становится рейтингом надёжности."""
    if not 2 <= len(snapshots) <= 6 or len(snapshots) != len(analyses):
        return None
    counts: list[int] = []
    ids: list[str] = []
    for snapshot, analysis in zip(snapshots, analyses, strict=True):
        validate_analysis(analysis, snapshot)
        finding = next(f for f in analysis.findings if f.code == "enforcement_summary")
        counts.append(sum(item.is_active for item in snapshot.enforcement_proceedings))
        ids.extend(finding.evidence_ids)
        ids.extend(e.evidence_id for e in snapshot.evidence if e.canonical_path == "identity")
    highest = max(counts)
    if highest == 0 or counts.count(highest) != 1:
        return None
    leader = snapshots[counts.index(highest)]
    text = (
        "Для первоочередной проверки взысканий по числу активных записей выделяется "
        f"{leader.identity.short_name} (ИНН {leader.identity.inn}): {highest}. "
        "В остальных отчётах: "
        + "; ".join(
            f"{s.identity.short_name} (ИНН {s.identity.inn}) — {count}"
            for s, count in zip(snapshots, counts, strict=True)
            if s is not leader
        )
        + ". Сравнивается число записей в выгрузках, не вероятность неоплаты и не "
        "надёжность компаний. Это не основание выбрать или отклонить исполнителя."
    )
    if len(text) > 1100:
        return None
    evidence = tuple(dict.fromkeys(ids))
    digest = hashlib.sha256(json.dumps([text, evidence], ensure_ascii=False).encode()).hexdigest()[
        :24
    ]
    return ApprovedFact(
        f"fact_{digest}",
        GroundedClaim(text=text, evidence_ids=evidence),
        "comparison_enforcement_focus",
    )


def build_comparison_fact_catalog(
    snapshots: Sequence[CounterpartySnapshot], comparison: ComparisonResult
) -> tuple[ApprovedFact, ...]:
    """Краткие групповые факты сохраняют каждую позицию и проверенные ссылки матрицы."""

    validate_comparison(comparison, snapshots)
    facts: list[ApprovedFact] = []

    def add(
        topic: str,
        text: str,
        evidence_ids: Sequence[str],
        *,
        period: int | None = None,
        metric: str | None = None,
    ) -> None:
        ids = tuple(dict.fromkeys(evidence_ids))
        digest = hashlib.sha256(
            json.dumps(
                ["comparison-facts-v1", comparison.snapshot_ids, topic, period, metric, ids],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()[:24]
        facts.append(
            ApprovedFact(
                f"fact_{digest}", GroundedClaim(text=text, evidence_ids=ids), topic, period, metric
            )
        )

    for row in comparison.rows:
        parts = []
        for position, cell in enumerate(row.cells, start=1):
            if row.key == "company_status" and cell.value != "CURRENT":
                value = "значение статуса не интерпретировано"
            elif row.key == "data_gaps":
                value = f"ограничений в проверенных выводах: {cell.value}"
            elif row.key == "attention_signals":
                value = f"сигналов внимания в поддержанных проверках: {cell.value}"
            else:
                value = cell.display_value
            parts.append(f"Компания №{position}: {value}." + _comparison_quality(cell.data_status))
        topic = "comparison_bank_signal" if row.key == "bank_risk" else f"comparison_{row.key}"
        metric = None
        if row.category == "finance":
            topic, metric = "comparison_financial", row.key.removeprefix("financial_")
        title = f"{row.label}" + (f" за {row.period} год" if row.period else "") + "."
        note = row.comparison_note
        if row.key == "bank_risk":
            note += " Цвет не гарантирует безопасность сделки."
        add(
            topic,
            "\n".join((title, *parts, note)),
            [key for cell in row.cells for key in cell.evidence_ids],
            period=row.period,
            metric=metric,
        )
        if row.key == "bank_risk":
            add(
                "comparison_bank_signal",
                "\n".join(
                    f"Компания №{position}: "
                    + (
                        "Причина этой оценки в отчёте не указана."
                        if snapshot.bank_risk.recognized_level is not None
                        else "В отчёте нет распознанной оценки, "
                        "причину её отсутствия определить нельзя."
                    )
                    for position, snapshot in enumerate(snapshots, start=1)
                ),
                [key for cell in row.cells for key in cell.evidence_ids],
                metric="reason_unavailable",
            )

    profit = next(row for row in comparison.rows if row.key == "financial_profit")
    parts = []
    for position, cell in enumerate(profit.cells, start=1):
        if cell.value is None:
            text = "прибыль неизвестна; убыток по этому показателю не определён"
        else:
            profit_value = Decimal(str(cell.value))
            text = (
                f"переданное значение прибыли отрицательно ({cell.value}); "
                "за период указан убыток по этому показателю"
                if profit_value < 0
                else f"переданное значение прибыли неотрицательно ({cell.value}); "
                "это не гарантия устойчивости"
            )
        parts.append(f"Компания №{position}: {text}." + _comparison_quality(cell.data_status))
    period_text = (
        f"за {comparison.financial_year} год"
        if comparison.financial_year
        else "при отсутствии завершённых финансовых периодов"
    )
    add(
        "comparison_loss",
        "\n".join(
            (
                f"Проверка знака прибыли {period_text}.",
                *parts,
                "Значения указаны в рублях без дополнительного множителя; "
                "денежное ранжирование не выполняется.",
            )
        ),
        [key for cell in profit.cells for key in cell.evidence_ids],
        period=comparison.financial_year,
        metric="profit",
    )

    supported = tuple(
        row
        for row in comparison.rows
        if row.category in {"finance", "arbitration", "enforcement"} or row.key == "bank_risk"
    )
    parts = []
    for position in range(len(comparison.snapshot_ids)):
        applicable = [
            row
            for row in supported
            if row.cells[position].data_status is not FindingDataStatus.INAPPLICABLE
        ]
        missing = [
            row
            for row in applicable
            if row.cells[position].value is None
            or (
                row.key == "bank_risk"
                and row.cells[position].data_status is FindingDataStatus.INSUFFICIENT
            )
        ]
        text = (
            f"Компания №{position + 1}: заполнено {len(applicable) - len(missing)} "
            f"из {len(applicable)} применимых показателей; неизвестно {len(missing)}, "
            f"неприменимо по данным источника {len(supported) - len(applicable)}."
        )
        if missing:
            text += " Пропуски: " + ", ".join(row.label for row in missing) + "."
        parts.append(text)
    add(
        "comparison_coverage",
        "\n".join(
            (
                f"Ограниченное покрытие {len(supported)} показателей текущей таблицы: финансы, "
                "суды по ролям, взыскания и банковская оценка.",
                *parts,
                "Заполнено означает наличие значения, не его достоверность. Неприменимые поля "
                "не считаются пропусками. Знаменатели могут различаться, в том числе у ЮЛ и ИП; "
                "общая полнота исходных отчётов и рейтинг надёжности "
                "по этим числам не определяются.",
            )
        ),
        [key for row in supported for cell in row.cells for key in cell.evidence_ids],
    )
    return tuple(facts)


def _comparison_quality(status: FindingDataStatus) -> str:
    """Не скрывать качество исходной ячейки при кратком групповом изложении."""

    return {
        FindingDataStatus.CONFIRMED: "",
        FindingDataStatus.PARTIAL: " Данные неполные или покрытие не подтверждено.",
        FindingDataStatus.CONFLICTING: " Есть противоречия; показатель требует проверки.",
        FindingDataStatus.INSUFFICIENT: " Данных недостаточно.",
        FindingDataStatus.INAPPLICABLE: " Неприменимо по сведениям источника.",
    }[status]
