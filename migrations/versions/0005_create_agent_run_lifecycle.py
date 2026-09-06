"""Create durable agent run lifecycle.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-05 21:39:26.921189
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the revision."""
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("client_request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "accepted",
                "running",
                "cancelling",
                "completed",
                "awaiting_input",
                "failed",
                "cancelled",
                "interrupted",
                name="agent_run_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("based_on_context_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_public_revision", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "(status IN ('accepted', 'running', 'cancelling')) = (finished_at IS NULL)",
            name=op.f("ck_agent_runs_terminal_status_matches_timestamp"),
        ),
        sa.CheckConstraint(
            "based_on_context_version >= 0", name=op.f("ck_agent_runs_context_version_non_negative")
        ),
        sa.CheckConstraint(
            "last_public_revision >= 0", name=op.f("ck_agent_runs_public_revision_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["workspace.projects.id", "workspace.projects.tenant_id"],
            name="fk_agent_runs_project_id_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "project_id"],
            ["workspace.threads.id", "workspace.threads.project_id"],
            name="fk_agent_runs_thread_id_project_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint(
            "tenant_id", "thread_id", "client_request_id", name="uq_agent_runs_request"
        ),
        schema="workspace",
    )
    op.create_index(
        "uq_agent_runs_active_thread",
        "agent_runs",
        ["thread_id"],
        unique=True,
        schema="workspace",
        postgresql_where=sa.text("status IN ('accepted', 'running', 'cancelling')"),
    )

    op.execute("GRANT SELECT, INSERT, UPDATE ON workspace.agent_runs TO counterparty_agent")


def downgrade() -> None:
    """Revert the revision."""
    op.drop_index(
        "uq_agent_runs_active_thread",
        table_name="agent_runs",
        schema="workspace",
        postgresql_where=sa.text("status IN ('accepted', 'running', 'cancelling')"),
    )
    op.drop_table("agent_runs", schema="workspace")
