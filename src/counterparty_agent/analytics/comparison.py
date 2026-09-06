"""Единая матрица N компаний и проверка сопоставимости."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from counterparty_agent.analytics.common import AnalysisValidationError, _number
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.models import (
    AnalysisResult,
    ComparisonCell,
    ComparisonResult,
    ComparisonRow,
    CounterpartySnapshot,
    Finding,
    FindingDataStatus,
    FindingSeverity,
    PartyType,
)


@dataclass(frozen=True, slots=True)
class _ComparisonColumn:
    """Временный контекст столбца; полный снимок не входит в результат сравнения."""

    snapshot: CounterpartySnapshot
    analysis: AnalysisResult

    def finding(self, code: str, period: int | None = None) -> Finding:
        for item in self.analysis.findings:
            if item.code == code and (period is None or item.period == period):
                return item
        raise AnalysisValidationError("Для ячейки сравнения нет проверенного вывода")

    def observed(self, path: str) -> tuple[str, ...]:
        ids = tuple(
            item.evidence_id for item in self.snapshot.evidence if item.canonical_path == path
        )
        if not ids:
            raise AnalysisValidationError("Для ячейки сравнения нет исходного доказательства")
        return ids

    def values(self, finding: Finding) -> dict[str, object]:
        evidence = next(
            item
            for item in self.analysis.derived_evidence
            if item.evidence_id == finding.evidence_ids[0]
        )
        if not isinstance(evidence.typed_value, dict):
            raise AnalysisValidationError("Некорректное доказательство показателя сравнения")
        return dict(evidence.typed_value)

    def cell(
        self,
        value: str | int | Decimal | None,
        ids: tuple[str, ...],
        status: FindingDataStatus = FindingDataStatus.CONFIRMED,
        *,
        display: str | None = None,
    ) -> ComparisonCell:
        return ComparisonCell(
            snapshot_id=self.snapshot.snapshot_id,
            value=str(value) if isinstance(value, Decimal) else value,
            display_value=display if display is not None else _number(value),
            evidence_ids=ids,
            data_status=status,
        )


def compare_snapshots(
    snapshots: Sequence[CounterpartySnapshot], *, evaluated_at: datetime
) -> ComparisonResult:
    """Сопоставить N выбранных компаний в одном периоде без рейтинга и LLM."""

    selected = tuple(snapshots)
    if len(selected) < 2:
        raise AnalysisValidationError("Для сравнения нужны хотя бы 2 компании")
    if len({item.snapshot_id for item in selected}) != len(selected) or len(
        {item.company_id for item in selected}
    ) != len(selected):
        raise AnalysisValidationError("В сравнении не должно быть повторяющихся компаний")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise AnalysisValidationError("Дата сравнения должна содержать часовой пояс")
    columns = tuple(
        _ComparisonColumn(snapshot, analyze_snapshot(snapshot, evaluated_at=evaluated_at))
        for snapshot in selected
    )
    years = [
        {
            item.period
            for item in column.analysis.findings
            if item.code == "financial_period" and isinstance(item.period, int)
        }
        for column in columns
    ]
    common = set.intersection(*years)
    available = set.union(*years)
    # Только завершённые и проверенные годы; один год для всей строки, включая пропуски.
    financial_year = max(common or available) if available else None
    if financial_year is not None and not isinstance(financial_year, int):
        raise AnalysisValidationError("Финансовый период сравнения имеет неверный тип")
    rows: list[ComparisonRow] = []
    same_dates = len({item.report_at for item in selected}) == 1
    limitations = [
        "Матрица показывает факты и пробелы, не назначает победителя, рейтинг "
        "или решение о сделке.",
        "Отсутствие данных не означает отсутствие риска; нули показываются только из источника.",
        "Денежные значения указаны в рублях без дополнительного множителя. "
        "Разные показатели нельзя подменять друг другом при ранжировании компаний.",
    ]
    if len({item.identity.party_type for item in selected}) > 1:
        limitations.append(
            "Выбраны ЮЛ и ИП: это неоднородная группа, финансовое покрытие различается."
        )
    if not same_dates:
        limitations.append(
            "Даты снимков различаются; сравнение не является проверкой на единую дату."
        )
    if not common:
        limitations.append(
            f"Общего завершённого финансового года нет. Показан {financial_year} год "
            "с явными пропусками у остальных компаний."
            if financial_year is not None
            else "Завершённых финансовых периодов нет; финансовое положение не сравнивается."
        )

    def add(
        key: str,
        label: str,
        category: str,
        cells: Sequence[ComparisonCell],
        note: str,
        *,
        comparable: bool = False,
        period: int | None = None,
    ) -> None:
        rows.append(
            ComparisonRow(
                key=key,
                label=label,
                category=category,
                period=period,
                comparable=comparable,
                comparison_note=note,
                cells=tuple(cells),
            )
        )

    add(
        "party_type",
        "Тип контрагента",
        "company",
        [
            column.cell(
                column.snapshot.identity.party_type.value,
                column.observed("identity"),
                display="ЮЛ"
                if column.snapshot.identity.party_type is PartyType.LEGAL_ENTITY
                else "ИП",
            )
            for column in columns
        ],
        "Тип субъекта — справочная характеристика, не оценка надёжности.",
        comparable=True,
    )
    add(
        "company_status",
        "Статус источника",
        "company",
        [
            column.cell(
                column.snapshot.status.raw_status,
                column.finding("company_status").evidence_ids,
                column.finding("company_status").data_status,
            )
            for column in columns
        ],
        "Исходный статус на дату соответствующего снимка; "
        "неизвестные значения не интерпретируются.",
        comparable=same_dates
        and all(
            column.snapshot.status.raw_status == "CURRENT"
            and column.finding("company_status").data_status is FindingDataStatus.CONFIRMED
            for column in columns
        ),
    )
    add(
        "report_date",
        "Дата отчёта",
        "company",
        [
            column.cell(
                column.snapshot.report_at.isoformat(),
                column.observed("report_at"),
                FindingDataStatus.CONFLICTING
                if column.snapshot.report_at > evaluated_at
                else FindingDataStatus.CONFIRMED,
            )
            for column in columns
        ],
        "Даты актуальности исходных снимков, не дата обновления государственных реестров.",
        comparable=True,
    )
    bank_labels = {
        "GREEN": "надёжный контрагент",
        "YELLOW": "требует внимания",
        "RED": "в зоне риска",
        "GREY": "нет данных для оценки",
    }
    add(
        "bank_risk",
        "Оценка в отчёте",
        "company",
        [
            column.cell(
                column.snapshot.bank_risk.raw_level,
                (column.analysis.bank_evidence_id,),
                FindingDataStatus.CONFIRMED
                if column.snapshot.bank_risk.recognized_level
                and column.snapshot.bank_risk.recognized_level.value != "GREY"
                else FindingDataStatus.INSUFFICIENT,
                display=(
                    bank_labels[column.snapshot.bank_risk.recognized_level.value]
                    if column.snapshot.bank_risk.recognized_level
                    else "Оценка отсутствует"
                    if column.snapshot.bank_risk.raw_level is None
                    else "Значение оценки не распознано"
                ),
            )
            for column in columns
        ],
        "Оценки приведены на даты соответствующих отчётов. "
        "Обстоятельства, требующие проверки, показаны отдельно.",
    )
    for metric, label in (
        ("proceeds", "Выручка"),
        ("profit", "Прибыль"),
        ("assets_total", "Активы"),
        ("liabilities_total", "Итог пассивов"),
        ("equity", "Капитал и резервы"),
    ):
        add(
            f"financial_{metric}",
            label,
            "finance",
            [_financial_cell(column, metric, financial_year) for column in columns],
            "Один финансовый год для всех компаний. Значения указаны в рублях; "
            "числовое ранжирование само по себе недопустимо. Итог пассивов не равен долгу.",
            period=financial_year,
        )
    for role, role_label in (("as_plaintiff", "Истец"), ("as_defendant", "Ответчик")):
        for field_name, label in (
            ("finished_count", "завершённые дела"),
            ("pending_count", "незавершённые дела"),
            ("appealed_count", "обжалованные дела"),
        ):
            cells = []
            for column in columns:
                finding = column.finding("arbitration_summary")
                value = getattr(getattr(column.snapshot.arbitration_summary, role), field_name)
                cells.append(
                    column.cell(
                        value,
                        finding.evidence_ids,
                        FindingDataStatus.INSUFFICIENT if value is None else finding.data_status,
                    )
                )
            add(
                f"arbitration_{role}_{field_name}",
                f"{role_label}: {label}",
                "arbitration",
                cells,
                "Роли и статусы не складываются. Покрытие сводок неизвестно; "
                "количество дел не означает проигрыш или долг.",
            )
    for key, label in (
        ("total_count", "Всего исполнительных производств"),
        ("active_count", "Помечены как активные"),
        ("known_amount", "Известные суммы всех производств"),
        ("active_known_amount", "Известные суммы активных производств"),
        ("missing_amount_count", "Производств без указанной суммы"),
    ):
        cells = []
        for column in columns:
            finding = column.finding("enforcement_summary")
            values = column.values(finding)
            value = values[key]
            if value is not None and not isinstance(value, (int, Decimal)):
                raise AnalysisValidationError("Некорректный показатель производств")
            status = FindingDataStatus.INSUFFICIENT if value is None else finding.data_status
            display = _number(value)
            if key in {"known_amount", "active_known_amount"}:
                prefix = "active_" if key == "active_known_amount" else ""
                total = values["active_count" if prefix else "total_count"]
                missing = values[f"{prefix}missing_amount_count"]
                display += f"; записей: {total}, без суммы: {missing}. Единицы источника."
            cells.append(column.cell(value, finding.evidence_ids, status, display=display))
        add(
            f"enforcement_{key}",
            label,
            "enforcement",
            cells,
            "Только переданная коллекция на дату снимка. Известная сумма не равна общему долгу; "
            "пропуски и неизвестное покрытие исключают ранжирование.",
        )
    cells = []
    for column in columns:
        gaps = tuple(
            item
            for item in column.analysis.findings
            if item.data_status
            in {
                FindingDataStatus.INSUFFICIENT,
                FindingDataStatus.INAPPLICABLE,
                FindingDataStatus.CONFLICTING,
                FindingDataStatus.PARTIAL,
            }
        )
        ids = tuple(dict.fromkeys(key for item in gaps for key in item.evidence_ids))
        if not ids:
            ids = tuple(key for item in column.analysis.findings for key in item.evidence_ids)
        display = f"Ограничений в проверенных выводах: {len(gaps)}."
        if gaps:
            display += " " + " ".join(item.statement for item in gaps[:3])
            if len(gaps) > 3:
                display += f" Ещё ограничений: {len(gaps) - 3}; подробности — в карточке."
        else:
            display += " Это не подтверждение полноты исходного отчёта."
        cells.append(
            column.cell(
                len(gaps),
                ids,
                FindingDataStatus.PARTIAL if gaps else FindingDataStatus.CONFIRMED,
                display=display,
            )
        )
    add(
        "data_gaps",
        "Пробелы и ограничения",
        "data_quality",
        cells,
        "Число ограничений отражает покрытие и проверки, не балл риска; "
        "меньше не означает надёжнее.",
    )
    cells = []
    for column in columns:
        attention = tuple(
            item for item in column.analysis.findings if item.severity is FindingSeverity.ATTENTION
        )
        cited = attention or column.analysis.findings
        ids = tuple(dict.fromkeys(key for item in cited for key in item.evidence_ids))
        display = (
            " ".join(item.statement for item in attention[:3])
            if attention
            else "В поддержанных проверках нет выводов с приоритетом attention; "
            "это не отсутствие риска."
        )
        if len(attention) > 3:
            display += f" Ещё сигналов внимания: {len(attention) - 3}; подробности — в карточке."
        cells.append(
            column.cell(
                len(attention),
                ids,
                FindingDataStatus.PARTIAL
                if any(item.data_status is not FindingDataStatus.CONFIRMED for item in attention)
                else FindingDataStatus.CONFIRMED,
                display=display,
            )
        )
    add(
        "attention_signals",
        "Сигналы, требующие внимания",
        "company",
        cells,
        "Отдельные обстоятельства для проверки. "
        "Количество сигналов не определяет надёжность компании.",
    )
    return ComparisonResult(
        snapshot_ids=tuple(item.snapshot_id for item in selected),
        evaluated_at=evaluated_at.astimezone(UTC),
        financial_year=financial_year,
        rows=tuple(rows),
        limitations=tuple(limitations),
    )


def _financial_cell(column: _ComparisonColumn, metric: str, year: int | None) -> ComparisonCell:
    finding = next(
        (
            item
            for item in column.analysis.findings
            if item.code == "financial_period" and item.period == year
        ),
        None,
    )
    if finding is not None:
        value = column.values(finding)[metric]
        if value is not None and not isinstance(value, Decimal):
            raise AnalysisValidationError("Некорректное денежное значение сравнения")
        return column.cell(
            value,
            finding.evidence_ids,
            FindingDataStatus.INSUFFICIENT if value is None else finding.data_status,
            display=None if value is None else f"{_number(value)} ₽",
        )
    # Список всех проверенных периодов или явный пробел подтверждает отсутствие выбранного года.
    coverage = tuple(
        item
        for item in column.analysis.findings
        if item.code
        in {
            "financial_period",
            "financial_period_after_report",
            "financial_missing",
            "financial_empty",
        }
    )
    ids = tuple(dict.fromkeys(key for item in coverage for key in item.evidence_ids))
    if not ids:
        raise AnalysisValidationError("Финансовый пропуск не имеет доказательств")
    status = (
        FindingDataStatus.INAPPLICABLE
        if any(item.data_status is FindingDataStatus.INAPPLICABLE for item in coverage)
        else FindingDataStatus.INSUFFICIENT
    )
    return column.cell(
        None,
        ids,
        status,
        display=f"Нет отчёта за {year} год"
        if year is not None
        else "Нет завершённых финансовых периодов",
    )


def validate_comparison(
    result: ComparisonResult, snapshots: Sequence[CounterpartySnapshot]
) -> None:
    """Повторить матрицу и проверить каждую ссылку, значение, период и порядок столбцов."""

    selected = tuple(snapshots)
    if tuple(item.snapshot_id for item in selected) != result.snapshot_ids:
        raise AnalysisValidationError("Сравнение относится к другим компаниям или порядку снимков")
    for snapshot in selected:
        analysis = analyze_snapshot(snapshot, evaluated_at=result.evaluated_at)
        ledger = {
            item.evidence_id: item for item in (*snapshot.evidence, *analysis.derived_evidence)
        }
        for row in result.rows:
            for cell in row.cells:
                if cell.snapshot_id != snapshot.snapshot_id:
                    continue
                if not cell.evidence_ids or len(set(cell.evidence_ids)) != len(cell.evidence_ids):
                    raise AnalysisValidationError("Ячейка сравнения имеет некорректные ссылки")
                for key in cell.evidence_ids:
                    item = ledger.get(key)
                    if (
                        item is None
                        or item.snapshot_id != cell.snapshot_id
                        or item.company_id != snapshot.company_id
                    ):
                        raise AnalysisValidationError(
                            "Доказательство ячейки относится к другому снимку"
                        )
    expected = compare_snapshots(selected, evaluated_at=result.evaluated_at)
    if result != expected:
        raise AnalysisValidationError(
            "Матрица сравнения не соответствует исходным фактам и правилам"
        )
