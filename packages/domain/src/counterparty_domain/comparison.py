"""Deterministic side-by-side comparison of pinned report overviews.

The comparison preserves request order, selects financial years by an explicit
policy, and never ranks companies.  Unknown values remain unknown cells; they
are not coerced to zero or sorted below known values.
"""

from collections.abc import Sequence

from counterparty_contracts import (
    Availability,
    CompanyOverview,
    ComparisonCriterion,
    ComparisonRow,
    ComparisonRowStatus,
    ContractWarning,
    FactValue,
    ReportId,
    ValueType,
    WarningCode,
    YearPolicy,
)

__all__ = ["COMPARISON_RULE_VERSION", "build_comparison_rows"]

COMPARISON_RULE_VERSION = "comparison/1"

_FINANCIAL_PREFIX = "financials."


def _financial_years(overview: CompanyOverview) -> set[int]:
    years: set[int] = set()
    for fact in overview.facts:
        if not fact.key.startswith(_FINANCIAL_PREFIX):
            continue
        parts = fact.key.split(".", 2)
        if len(parts) == 3 and parts[1].isdigit():
            years.add(int(parts[1]))
    return years


def _common_year(overviews: Sequence[CompanyOverview]) -> int | None:
    if not overviews:
        return None
    common = _financial_years(overviews[0])
    for overview in overviews[1:]:
        common &= _financial_years(overview)
    return max(common) if common else None


def _missing_cell(key: str, label: str, *, period: int | None = None) -> FactValue:
    return FactValue(
        key=key,
        label=label,
        value_type=ValueType.STRING,
        period=period,
        availability=Availability.MISSING,
    )


def _financial_cells(overview: CompanyOverview, year: int | None) -> list[FactValue]:
    if year is None:
        return [_missing_cell("financials", "Финансовые показатели")]
    prefix = f"{_FINANCIAL_PREFIX}{year}."
    selected = [
        fact.model_copy(update={"key": fact.key.removeprefix(prefix)})
        for fact in overview.facts
        if fact.key.startswith(prefix)
    ]
    if selected:
        return selected
    return [_missing_cell("financials", "Финансовые показатели", period=year)]


def _criterion_cells(
    overview: CompanyOverview,
    criterion: ComparisonCriterion,
    *,
    financial_year: int | None,
) -> list[FactValue]:
    if criterion is ComparisonCriterion.STATUS:
        status = overview.status
        return [
            FactValue(
                key="status",
                label="Статус",
                value=status.raw_value,
                value_type=ValueType.ENUM,
                availability=status.availability,
                evidence_refs=status.evidence_refs,
            )
        ]
    if criterion is ComparisonCriterion.BANK_RISK:
        risk = overview.bank_risk
        return [
            FactValue(
                key="bank_risk",
                label="Оценка банка",
                value=risk.raw_value,
                value_type=ValueType.ENUM,
                availability=risk.availability,
                evidence_refs=risk.evidence_refs,
            )
        ]
    if criterion is ComparisonCriterion.FINANCIALS:
        return _financial_cells(overview, financial_year)

    prefix = f"{criterion.value}."
    selected = [fact for fact in overview.facts if fact.key.startswith(prefix)]
    if selected:
        return selected
    return [_missing_cell(criterion.value, criterion.value.replace("_", " ").title())]


def _row_status(cells: Sequence[FactValue]) -> ComparisonRowStatus:
    available = sum(cell.availability is Availability.AVAILABLE for cell in cells)
    if available == len(cells):
        return ComparisonRowStatus.COMPLETE
    if available:
        return ComparisonRowStatus.PARTIAL
    return ComparisonRowStatus.UNAVAILABLE


def build_comparison_rows(
    report_ids: Sequence[ReportId],
    overviews: Sequence[CompanyOverview],
    criteria: Sequence[ComparisonCriterion],
    *,
    year_policy: YearPolicy,
    year: int | None = None,
) -> tuple[list[ComparisonRow], list[ContractWarning]]:
    """Build stable per-company rows without a score, winner or ranking.

    Args:
        report_ids: Requested pinned snapshots in client-visible order.
        overviews: Available overview projections for those snapshots.
        criteria: Whitelisted categories to place side by side.
        year_policy: How financial periods are selected.
        year: Required only for ``explicit``.

    Returns:
        Rows for every available overview and comparison-level diagnostics.
        A caller may append an unavailable row when a report itself could not
        be read, because constructing its company identity requires storage.
    """
    by_report = {overview.report.id: overview for overview in overviews}
    ordered = [by_report[report_id] for report_id in report_ids if report_id in by_report]
    common_year = _common_year(ordered) if year_policy is YearPolicy.COMMON_LATEST else None
    warnings: list[ContractWarning] = []
    if year_policy is YearPolicy.COMMON_LATEST and common_year is None:
        warnings.append(
            ContractWarning(
                code=WarningCode.NOT_COMPARABLE,
                message="The companies have no common available financial period.",
            )
        )

    rows: list[ComparisonRow] = []
    selected_years: set[int] = set()
    for overview in ordered:
        financial_year = year
        if year_policy is YearPolicy.COMMON_LATEST:
            financial_year = common_year
        elif year_policy is YearPolicy.LATEST_AVAILABLE:
            years = _financial_years(overview)
            financial_year = max(years) if years else None
        if financial_year is not None:
            selected_years.add(financial_year)

        cells: list[FactValue] = []
        for criterion in criteria:
            cells.extend(_criterion_cells(overview, criterion, financial_year=financial_year))
        row_warnings: list[ContractWarning] = []
        if any(cell.availability is not Availability.AVAILABLE for cell in cells):
            row_warnings.append(
                ContractWarning(
                    code=WarningCode.PARTIAL_DATA,
                    message=("Some requested facts are unavailable; an unknown value is not zero."),
                )
            )
        rows.append(
            ComparisonRow(
                company=overview.company,
                report=overview.report,
                cells=cells,
                status=_row_status(cells),
                warnings=row_warnings,
            )
        )

    if year_policy is YearPolicy.LATEST_AVAILABLE and len(selected_years) > 1:
        warnings.append(
            ContractWarning(
                code=WarningCode.PERIOD_MISMATCH,
                message="Для компаний показаны разные последние доступные финансовые периоды.",
            )
        )
    return rows, warnings
