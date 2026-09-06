"""Create user decisions and AI analysis artifacts.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06

Two independent, versioned entities of Specs 09 §5 / 10 §5 become tables here:

* ``user_decisions`` — what a person recorded about a project. It is not an AI
  output and is never overwritten: revising a decision inserts a new row that
  points back with ``supersedes_id``, and the earlier row stays. The author is
  a ``RESTRICT`` foreign key to ``users``, so a decision can never be left
  without the person who made it.
* ``analysis_artifacts`` — one immutable version of an AI conclusion. Identity
  is ``(id, version)``; a later analysis is a new row, never an edit, so an
  answer that was already shown stays readable unchanged.

Both reference their project by ``(id, tenant_id)``, so neither can be moved
between tenants. ``counterparty_ui_api`` reaches both through the whole-schema
default privileges granted in revision 0004; the agent, which will write
artifacts, gets its grant in a later revision together with that capability.

The revision is fully reversible: ``downgrade`` drops exactly what it created.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the revision."""
    op.create_table(
        "analysis_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("based_on_context_version", sa.Integer(), nullable=False),
        sa.Column("report_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("grounds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unknowns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("next_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "freshness",
            sa.Enum(
                "current",
                "outdated",
                "source_removed",
                name="artifact_freshness",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_thread_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "based_on_context_version >= 0",
            name=op.f("ck_analysis_artifacts_context_version_non_negative"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_analysis_artifacts_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["workspace.projects.id", "workspace.projects.tenant_id"],
            name="fk_analysis_artifacts_project_id_tenant_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "version", name=op.f("pk_analysis_artifacts")),
        schema="workspace",
    )
    op.create_index(
        "ix_analysis_artifacts_project_id_created_at",
        "analysis_artifacts",
        ["project_id", "created_at"],
        unique=False,
        schema="workspace",
    )
    op.create_table(
        "user_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "ready",
                "ready_with_conditions",
                "not_ready",
                "need_more_info",
                name="decision_outcome",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("company_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("based_on_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("based_on_artifact_version", sa.Integer(), nullable=True),
        sa.Column("context_version", sa.Integer(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(based_on_artifact_id IS NULL) = (based_on_artifact_version IS NULL)",
            name=op.f("ck_user_decisions_artifact_reference_pins_version"),
        ),
        sa.CheckConstraint(
            "based_on_artifact_version IS NULL OR based_on_artifact_version >= 1",
            name=op.f("ck_user_decisions_artifact_version_positive"),
        ),
        sa.CheckConstraint(
            "context_version >= 0",
            name=op.f("ck_user_decisions_context_version_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["workspace.users.id"],
            name=op.f("fk_user_decisions_author_user_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["workspace.projects.id", "workspace.projects.tenant_id"],
            name="fk_user_decisions_project_id_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["workspace.user_decisions.id"],
            name="fk_user_decisions_supersedes_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_decisions")),
        schema="workspace",
    )
    op.create_index(
        "ix_user_decisions_project_id_created_at",
        "user_decisions",
        ["project_id", "created_at"],
        unique=False,
        schema="workspace",
    )


def downgrade() -> None:
    """Revert the revision."""
    op.drop_index(
        "ix_user_decisions_project_id_created_at",
        table_name="user_decisions",
        schema="workspace",
    )
    op.drop_table("user_decisions", schema="workspace")
    op.drop_index(
        "ix_analysis_artifacts_project_id_created_at",
        table_name="analysis_artifacts",
        schema="workspace",
    )
    op.drop_table("analysis_artifacts", schema="workspace")
