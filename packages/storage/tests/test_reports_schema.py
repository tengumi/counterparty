"""Structural guarantees of the ``reports`` schema."""

from decimal import Decimal

import pytest
from sqlalchemy import Numeric, Table, UniqueConstraint
from sqlalchemy.types import TIMESTAMP

from counterparty_storage import MANAGED_SCHEMAS, REPORTS_SCHEMA, metadata
from counterparty_storage.reports import SourceState

FIRST_VERTICAL = {
    "import_batches",
    "companies",
    "report_snapshots",
    "company_profiles",
    "company_statuses",
    "activity_codes",
    "financial_statements",
    "zsk_assessments",
    "section_availability",
    "import_warnings",
}


def _table(name: str) -> Table:
    return metadata.tables[f"{REPORTS_SCHEMA}.{name}"]


def test_first_vertical_tables_are_mapped() -> None:
    """The mapped report tables are exactly the agreed first vertical."""
    mapped = {table.name for table in metadata.sorted_tables if table.schema == REPORTS_SCHEMA}
    assert mapped == FIRST_VERTICAL


def test_no_table_leaks_out_of_the_managed_schemas() -> None:
    """No table lands in ``public`` or in a schema owned by a framework."""
    schemas = {table.schema for table in metadata.sorted_tables}
    assert schemas <= MANAGED_SCHEMAS
    assert REPORTS_SCHEMA in schemas


def test_child_rows_carry_report_id_and_source_path() -> None:
    """Every per-record child table stays resolvable back to the source."""
    for name in ("activity_codes", "financial_statements", "section_availability"):
        table = _table(name)
        assert "report_id" in table.c
        assert "source_path" in table.c
        assert not table.c.source_path.nullable


@pytest.mark.parametrize(
    "column",
    [
        "proceeds",
        "profit",
        "total_assets",
        "current_assets",
        "stocks",
        "receivables",
        "cash",
        "noncurrent_assets",
        "fixed_assets",
        "balance_total_liabilities_side",
        "equity",
        "long_term_total",
        "long_term_other",
        "short_term_total",
        "short_term_borrowed",
        "accounts_payable",
    ],
)
def test_money_columns_are_exact_and_nullable(column: str) -> None:
    """Money is NUMERIC and absence stays NULL rather than becoming zero."""
    financials = _table("financial_statements").c[column]
    assert isinstance(financials.type, Numeric)
    assert not isinstance(financials.type.python_type, float)
    assert financials.type.python_type is Decimal
    assert financials.nullable


def test_financial_year_is_independent_of_the_snapshot_date() -> None:
    """The financial year is an integer column, never the report timestamp."""
    financials = _table("financial_statements")
    assert financials.c.year.type.python_type is int
    assert isinstance(_table("report_snapshots").c.source_report_at.type, TIMESTAMP)
    assert "year" not in _table("report_snapshots").c


def test_missing_empty_zero_and_invalid_are_distinguishable() -> None:
    """Source state keeps the four cases apart from a reported zero."""
    assert [state.value for state in SourceState] == [
        "missing",
        "present_empty",
        "present",
        "invalid",
    ]
    availability = _table("section_availability")
    assert availability.c.record_count.nullable
    assert availability.c.source_state.type.python_type is SourceState


def test_zsk_is_stored_raw_without_a_recomputed_colour() -> None:
    """Only the raw external value and a display policy version are stored."""
    zsk = _table("zsk_assessments")
    assert set(zsk.c.keys()) == {"report_id", "raw_value", "display_policy_version", "source_path"}


def test_equity_share_capital_and_balance_total_are_separate_concepts() -> None:
    """Reported equity is not the balance-sheet total of the liabilities side."""
    financials = _table("financial_statements")
    assert "equity" in financials.c
    assert "balance_total_liabilities_side" in financials.c
    assert "share_capital" not in financials.c


def test_snapshot_hash_makes_reimport_idempotent() -> None:
    """A repeated snapshot hash cannot create a second row for the company."""
    constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in _table("report_snapshots").constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("company_id", "hash") in constraints


def test_inn_is_unique_and_stored_as_text() -> None:
    """Companies are identified by INN as a string, not as a number."""
    companies = _table("companies")
    assert companies.c.inn.type.python_type is str
    assert companies.c.entity_type.nullable


def test_constraint_names_are_deterministic() -> None:
    """Naming conventions keep migrations reversible by name."""
    indexes = {index.name for table in metadata.sorted_tables for index in table.indexes}
    assert "ix_report_snapshots_company_id_source_report_at" in indexes
    assert "ix_financial_statements_report_id_year" in indexes
