"""Финансовые показатели, пропуски и отрицательные значения."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from counterparty_agent.analytics.common import (
    AnalysisValidationError,
    _AnalysisBuilder,
    _encode,
    _number,
)
from counterparty_agent.models import (
    Evidence,
    EvidenceCoverage,
    FinancialStatement,
    FindingCategory,
    FindingDataStatus,
    FindingSeverity,
    PartyType,
)


def _analyze_finances(builder: _AnalysisBuilder) -> None:
    snapshot = builder.snapshot
    statements = snapshot.financial_statements
    if not statements:
        parents = builder.inputs("financial_statements", (statements,))
        is_ip = snapshot.identity.party_type is PartyType.INDIVIDUAL_ENTREPRENEUR
        builder.add(
            "financial_missing" if statements is None else "financial_empty",
            FindingCategory.FINANCE,
            "В snapshot ИП нет финансовых отчётов; финансовое положение не оценено."
            if is_ip
            else "Раздел финансов отсутствует или пуст; это не доказывает отсутствие деятельности.",
            {"missing": statements is None, "party_type": snapshot.identity.party_type.value},
            (*parents, *builder.inputs("identity", (snapshot.identity.model_dump(mode="python"),))),
            status=(
                FindingDataStatus.INAPPLICABLE
                if is_ip and parents[0].coverage is EvidenceCoverage.NOT_APPLICABLE
                else FindingDataStatus.INSUFFICIENT
            ),
        )
        return
    all_inputs = builder.inputs(
        "financial_statements.item", tuple(item.model_dump(mode="python") for item in statements)
    )
    by_year = {item.period: item for item in all_inputs}
    ordered = sorted(statements, key=lambda item: item.year)
    if len(by_year) != len(ordered) or len({item.year for item in ordered}) != len(ordered):
        raise AnalysisValidationError("Неоднозначные финансовые периоды")
    for item in ordered:
        evidence = by_year.get(item.year)
        if (
            evidence is None
            or evidence.stable_key != f"year:{item.year}"
            or _encode(evidence.typed_value) != _encode(item.model_dump(mode="python"))
        ):
            raise AnalysisValidationError("Доказательство относится к другому финансовому периоду")
    builder.add(
        "money_units_unspecified",
        FindingCategory.DATA_QUALITY,
        "Валюта и масштаб финансовых значений не заданы. Суммы показаны в единицах источника; "
        "сопоставимость единиц между годами не подтверждена.",
        {"currency": None, "unit": None},
        all_inputs,
        status=FindingDataStatus.INSUFFICIENT,
    )
    usable: list[FinancialStatement] = []
    for item in ordered:
        parent = (by_year[item.year],)
        if item.year >= snapshot.report_at.year:
            builder.add(
                "financial_period_after_report",
                FindingCategory.DATA_QUALITY,
                f"Годовой период {item.year} не завершён на дату отчёта; "
                "он не используется для годовой динамики.",
                {"year": item.year, "report_at": snapshot.report_at},
                (*parent, *builder.inputs("report_at", (snapshot.report_at,))),
                status=FindingDataStatus.CONFLICTING,
                period=item.year,
            )
            continue
        usable.append(item)
        values: dict[str, object] = {
            "year": item.year,
            "proceeds": item.proceeds,
            "profit": item.profit,
            "assets_total": item.assets.total,
            "liabilities_total": item.liabilities.total,
            "equity": item.liabilities.capital_and_reserves,
        }
        missing = [name for name, value in values.items() if value is None]
        builder.add(
            "financial_period",
            FindingCategory.FINANCE,
            f"За {item.year}: выручка — {_number(item.proceeds)}, "
            f"прибыль — {_number(item.profit)}, активы — {_number(item.assets.total)}, "
            f"итог пассивов — {_number(item.liabilities.total)}. "
            "Значения даны в единицах источника; итог пассивов не равен сумме долга.",
            values,
            parent,
            period=item.year,
            unit="source_unit",
            status=FindingDataStatus.PARTIAL if missing else FindingDataStatus.CONFIRMED,
        )
        if missing:
            builder.add(
                "financial_fields_missing",
                FindingCategory.DATA_QUALITY,
                f"В финансовом периоде {item.year} есть незаполненные показатели; "
                "они не заменены нулями.",
                {"missing_fields": tuple(missing)},
                parent,
                status=FindingDataStatus.INSUFFICIENT,
                period=item.year,
            )
        for code, value, label in (
            ("financial_loss", item.profit, "прибыль"),
            ("negative_equity", item.liabilities.capital_and_reserves, "капитал и резервы"),
        ):
            if value is not None and value < 0:
                builder.add(
                    code,
                    FindingCategory.FINANCE,
                    f"За {item.year} показатель «{label}» отрицательный: {_number(value)} "
                    "в единицах источника. Это отдельный факт, не итоговый скоринг.",
                    {"value": value},
                    parent,
                    period=item.year,
                    unit="source_unit",
                    severity=FindingSeverity.ATTENTION,
                )
        _balance_checks(builder, item, parent)
    for previous, current in zip(usable, usable[1:], strict=False):
        parents = (by_year[previous.year], by_year[current.year])
        period = f"{previous.year}:{current.year}"
        if current.year != previous.year + 1:
            builder.add(
                "financial_period_gap",
                FindingCategory.DATA_QUALITY,
                f"Между {previous.year} и {current.year} есть пропущенные годы; "
                "годовая динамика не рассчитана.",
                {"previous_year": previous.year, "year": current.year},
                parents,
                status=FindingDataStatus.INSUFFICIENT,
                period=period,
            )
        elif previous.proceeds is not None and current.proceeds is not None:
            percent = (
                ((current.proceeds - previous.proceeds) / previous.proceeds * 100).quantize(
                    Decimal("0.01")
                )
                if previous.proceeds > 0 and current.proceeds >= 0
                else None
            )
            delta = current.proceeds - previous.proceeds
            builder.add(
                "financial_revenue_change",
                FindingCategory.FINANCE,
                f"Изменение указанных значений выручки {previous.year} → {current.year}: "
                f"{_number(delta)}; процент — {_number(percent)}. "
                "Единицы между годами требуют подтверждения; при неположительной базе "
                "или отрицательной выручке процент не рассчитывается.",
                {
                    "previous_year": previous.year,
                    "year": current.year,
                    "previous": previous.proceeds,
                    "current": current.proceeds,
                    "delta": delta,
                    "percent": percent,
                },
                parents,
                period=period,
                status=FindingDataStatus.PARTIAL,
            )


def _balance_checks(
    builder: _AnalysisBuilder, item: FinancialStatement, parents: Sequence[Evidence]
) -> None:
    checks: tuple[tuple[str, Decimal, tuple[Decimal | None, ...]], ...] = (
        ("financial_balance_mismatch", item.assets.total, (item.liabilities.total,)),
        (
            "financial_assets_components_mismatch",
            item.assets.total,
            (item.assets.current_total, item.assets.non_current_total),
        ),
        (
            "financial_liabilities_components_mismatch",
            item.liabilities.total,
            (
                item.liabilities.capital_and_reserves,
                item.liabilities.long_term_total,
                item.liabilities.short_term_total,
            ),
        ),
    )
    for code, total, parts in checks:
        if any(value is None for value in parts):
            continue
        parts_sum = sum((value for value in parts if value is not None), Decimal(0))
        if total != parts_sum:
            builder.add(
                code,
                FindingCategory.DATA_QUALITY,
                f"За {item.year} связанные финансовые значения не сходятся: "
                f"{_number(total)} и {_number(parts_sum)} в единицах источника. "
                "Нужна проверка исходных показателей; это не вывод о нарушении закона.",
                {"total": total, "parts": parts, "parts_sum": parts_sum},
                parents,
                status=FindingDataStatus.CONFLICTING,
                severity=FindingSeverity.ATTENTION,
                period=item.year,
                unit="source_unit",
            )
