"""Чтение финансовых форм с Decimal и сохранением пропусков."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from counterparty_agent.data.values import (
    _mapping,
    _optional_decimal,
    _optional_decimal_from_mapping,
    _optional_mapping,
    _required_decimal,
    _required_int,
    _sequence,
)
from counterparty_agent.models import (
    FinancialAssets,
    FinancialCoefficients,
    FinancialLiabilities,
    FinancialStatement,
)


def _map_financial_statements(
    report: Mapping[str, Any], record_number: int
) -> tuple[FinancialStatement, ...] | None:
    if "finReports" not in report:
        return None

    raw_statements = _sequence(report["finReports"], "report.finReports", record_number)
    statements: list[FinancialStatement] = []
    for index, raw_statement in enumerate(raw_statements):
        prefix = f"report.finReports[{index}]"
        statement = _mapping(raw_statement, prefix, record_number)
        common = _mapping(statement.get("common"), f"{prefix}.common", record_number)
        assets = _mapping(statement.get("assets"), f"{prefix}.assets", record_number)
        current_assets = _mapping(
            assets.get("currentAssets"), f"{prefix}.assets.currentAssets", record_number
        )
        non_current_assets = _optional_mapping(
            assets,
            "uncurrentAssets",
            f"{prefix}.assets.uncurrentAssets",
            record_number,
        )
        liabilities = _mapping(statement.get("liabilities"), f"{prefix}.liabilities", record_number)
        long_term = _optional_mapping(
            liabilities,
            "longTermDuties",
            f"{prefix}.liabilities.longTermDuties",
            record_number,
        )
        short_term = _optional_mapping(
            liabilities,
            "shortTermLiabilities",
            f"{prefix}.liabilities.shortTermLiabilities",
            record_number,
        )
        statements.append(
            FinancialStatement(
                year=_required_int(common.get("year"), f"{prefix}.common.year", record_number),
                proceeds=_optional_decimal(
                    common, "proceeds", f"{prefix}.common.proceeds", record_number
                ),
                profit=_optional_decimal(
                    common, "profit", f"{prefix}.common.profit", record_number
                ),
                assets=FinancialAssets(
                    total=_required_decimal(
                        assets.get("totalAssets"), f"{prefix}.assets.totalAssets", record_number
                    ),
                    current_total=_optional_decimal(
                        current_assets,
                        "total",
                        f"{prefix}.assets.currentAssets.total",
                        record_number,
                    ),
                    stocks=_optional_decimal(
                        current_assets,
                        "stocks",
                        f"{prefix}.assets.currentAssets.stocks",
                        record_number,
                    ),
                    receivables=_optional_decimal(
                        current_assets,
                        "receivables",
                        f"{prefix}.assets.currentAssets.receivables",
                        record_number,
                    ),
                    cash_and_equivalents=_optional_decimal(
                        current_assets,
                        "bankroll",
                        f"{prefix}.assets.currentAssets.bankroll",
                        record_number,
                    ),
                    non_current_total=_optional_decimal_from_mapping(
                        non_current_assets,
                        "total",
                        f"{prefix}.assets.uncurrentAssets.total",
                        record_number,
                    ),
                    fixed_assets=_optional_decimal_from_mapping(
                        non_current_assets,
                        "fixedAssets",
                        f"{prefix}.assets.uncurrentAssets.fixedAssets",
                        record_number,
                    ),
                ),
                liabilities=FinancialLiabilities(
                    total=_required_decimal(
                        liabilities.get("totalLiabilities"),
                        f"{prefix}.liabilities.totalLiabilities",
                        record_number,
                    ),
                    capital_and_reserves=_optional_decimal(
                        liabilities,
                        "capitals",
                        f"{prefix}.liabilities.capitals",
                        record_number,
                    ),
                    long_term_total=_optional_decimal_from_mapping(
                        long_term,
                        "total",
                        f"{prefix}.liabilities.longTermDuties.total",
                        record_number,
                    ),
                    other_long_term=_optional_decimal_from_mapping(
                        long_term,
                        "others",
                        f"{prefix}.liabilities.longTermDuties.others",
                        record_number,
                    ),
                    short_term_total=_optional_decimal_from_mapping(
                        short_term,
                        "total",
                        f"{prefix}.liabilities.shortTermLiabilities.total",
                        record_number,
                    ),
                    borrowed_funds=_optional_decimal_from_mapping(
                        short_term,
                        "borrowedFunds",
                        f"{prefix}.liabilities.shortTermLiabilities.borrowedFunds",
                        record_number,
                    ),
                    accounts_payable=_optional_decimal_from_mapping(
                        short_term,
                        "accountsPayable",
                        f"{prefix}.liabilities.shortTermLiabilities.accountsPayable",
                        record_number,
                    ),
                ),
            )
        )
    return tuple(statements)


def _map_financial_coefficients(
    report: Mapping[str, Any], record_number: int
) -> FinancialCoefficients | None:
    if "coefficient" not in report:
        return None
    prefix = "report.coefficient"
    raw_coefficients = _mapping(report["coefficient"], prefix, record_number)
    return FinancialCoefficients(
        year=_required_int(raw_coefficients.get("year"), f"{prefix}.year", record_number),
        profitability=_required_decimal(
            raw_coefficients.get("profitability"), f"{prefix}.profitability", record_number
        ),
        solvency=_required_decimal(
            raw_coefficients.get("solvency"), f"{prefix}.solvency", record_number
        ),
        sustainability=_required_decimal(
            raw_coefficients.get("sustainability"), f"{prefix}.sustainability", record_number
        ),
    )
