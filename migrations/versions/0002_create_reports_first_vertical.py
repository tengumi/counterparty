"""Create the first vertical of the reports schema.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05

Import batch, company, report snapshot and the report entities that hang off a
snapshot: profile, status, activity codes, financial statements, the raw ZSK
signal, per-section availability and import warnings.

Sections that do not have their own tables yet still reach the database inside
``report_snapshots.raw_jsonb`` and are described by ``section_availability``, so
this revision loses nothing from the source.

The revision is fully reversible: ``downgrade`` drops exactly the objects it
created and leaves the schemas themselves to revision 0001.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the revision."""
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("ogrn", sa.String(length=15), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("inn", name="uq_companies_inn"),
        schema="reports",
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("imported_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("counts_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "record_count >= 0", name=op.f("ck_import_batches_record_count_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_batches")),
        sa.UniqueConstraint("sha256", name="uq_import_batches_sha256"),
        schema="reports",
    )
    op.create_table(
        "report_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("source_record_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_report_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("raw_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "ingestion_status",
            sa.Enum(
                "complete",
                "partial",
                "invalid",
                name="ingestion_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["reports.import_batches.id"],
            name=op.f("fk_report_snapshots_batch_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["reports.companies.id"],
            name=op.f("fk_report_snapshots_company_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_snapshots")),
        sa.UniqueConstraint("company_id", "hash", name="uq_report_snapshots_company_id_hash"),
        schema="reports",
    )
    op.create_index(
        "ix_report_snapshots_batch_id",
        "report_snapshots",
        ["batch_id"],
        unique=False,
        schema="reports",
    )
    op.create_index(
        "ix_report_snapshots_company_id_source_report_at",
        "report_snapshots",
        ["company_id", "source_report_at"],
        unique=False,
        schema="reports",
    )
    op.create_table(
        "activity_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.report_snapshots.id"],
            name=op.f("fk_activity_codes_report_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_codes")),
        sa.UniqueConstraint("report_id", "ordinal", name="uq_activity_codes_report_id_ordinal"),
        schema="reports",
    )
    op.create_index(
        "ix_activity_codes_report_id",
        "activity_codes",
        ["report_id"],
        unique=False,
        schema="reports",
    )
    op.create_table(
        "company_profiles",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("short_name", sa.Text(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("kpp", sa.String(length=9), nullable=True),
        sa.Column("okpo", sa.String(length=10), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("registration_date", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("years_from_registration", sa.Integer(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("company_size", sa.Text(), nullable=True),
        sa.Column("bank_risk_raw", sa.Text(), nullable=True),
        sa.Column("extra_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.report_snapshots.id"],
            name=op.f("fk_company_profiles_report_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("report_id", name=op.f("pk_company_profiles")),
        schema="reports",
    )
    op.create_table(
        "company_statuses",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("status_raw", sa.Text(), nullable=True),
        sa.Column("status_date", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reason_raw", sa.Text(), nullable=True),
        sa.Column("extra_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.report_snapshots.id"],
            name=op.f("fk_company_statuses_report_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("report_id", name=op.f("pk_company_statuses")),
        schema="reports",
    )
    op.create_table(
        "financial_statements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("proceeds", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("profit", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("total_assets", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("current_assets", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("stocks", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("receivables", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("cash", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("noncurrent_assets", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("fixed_assets", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column(
            "balance_total_liabilities_side", sa.Numeric(precision=20, scale=2), nullable=True
        ),
        sa.Column("equity", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("long_term_total", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("long_term_other", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("short_term_total", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("short_term_borrowed", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("accounts_payable", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("extra_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "year BETWEEN 1900 AND 2200", name=op.f("ck_financial_statements_year_in_range")
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.report_snapshots.id"],
            name=op.f("fk_financial_statements_report_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_statements")),
        sa.UniqueConstraint("report_id", "year", name="uq_financial_statements_report_id_year"),
        schema="reports",
    )
    op.create_index(
        "ix_financial_statements_report_id_year",
        "financial_statements",
        ["report_id", "year"],
        unique=False,
        schema="reports",
    )
    op.create_table(
        "import_warnings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("source_record_id", sa.Text(), nullable=True),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "warning",
                "error",
                name="warning_severity",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["reports.import_batches.id"],
            name=op.f("fk_import_warnings_batch_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.report_snapshots.id"],
            name=op.f("fk_import_warnings_report_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_warnings")),
        schema="reports",
    )
    op.create_index(
        "ix_import_warnings_batch_id",
        "import_warnings",
        ["batch_id"],
        unique=False,
        schema="reports",
    )
    op.create_index(
        "ix_import_warnings_report_id",
        "import_warnings",
        ["report_id"],
        unique=False,
        schema="reports",
    )
    op.create_table(
        "section_availability",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column(
            "source_state",
            sa.Enum(
                "missing",
                "present_empty",
                "present",
                "invalid",
                name="source_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("warnings_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "source_state <> 'present' OR record_count IS NOT NULL",
            name=op.f("ck_section_availability_present_requires_record_count"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.report_snapshots.id"],
            name=op.f("fk_section_availability_report_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("report_id", "section", name=op.f("pk_section_availability")),
        schema="reports",
    )
    op.create_table(
        "zsk_assessments",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("display_policy_version", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.report_snapshots.id"],
            name=op.f("fk_zsk_assessments_report_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("report_id", name=op.f("pk_zsk_assessments")),
        schema="reports",
    )


def downgrade() -> None:
    """Revert the revision."""
    op.drop_table("zsk_assessments", schema="reports")
    op.drop_table("section_availability", schema="reports")
    op.drop_index("ix_import_warnings_report_id", table_name="import_warnings", schema="reports")
    op.drop_index("ix_import_warnings_batch_id", table_name="import_warnings", schema="reports")
    op.drop_table("import_warnings", schema="reports")
    op.drop_index(
        "ix_financial_statements_report_id_year",
        table_name="financial_statements",
        schema="reports",
    )
    op.drop_table("financial_statements", schema="reports")
    op.drop_table("company_statuses", schema="reports")
    op.drop_table("company_profiles", schema="reports")
    op.drop_index("ix_activity_codes_report_id", table_name="activity_codes", schema="reports")
    op.drop_table("activity_codes", schema="reports")
    op.drop_index(
        "ix_report_snapshots_company_id_source_report_at",
        table_name="report_snapshots",
        schema="reports",
    )
    op.drop_index("ix_report_snapshots_batch_id", table_name="report_snapshots", schema="reports")
    op.drop_table("report_snapshots", schema="reports")
    op.drop_table("import_batches", schema="reports")
    op.drop_table("companies", schema="reports")
