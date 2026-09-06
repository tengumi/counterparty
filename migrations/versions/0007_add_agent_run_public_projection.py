"""Store the durable public projection of a finished agent run.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-06

The V01 run keeps its replayable event log in memory (Specs 04 §7), and AG-04
mirrors only the run *lifecycle* into ``workspace.agent_runs``. What no one
persisted was the public projection itself — the ``messages`` and
``activities`` a reconnecting client renders — so opening a chat after the run
finished showed an empty history.

This revision adds one nullable ``public_projection`` JSONB column to
``workspace.agent_runs``. The agent writes the final ``PublicAgentState`` there
on its own fenced owner connection when a run reaches a terminal state (the I7
single-writer boundary is unchanged); ``counterparty_ui_api`` reads it back
through the whole-schema default privileges of revision 0004 and returns it
from ``GET /projects/{id}/threads/{tid}/conversation`` instead of an empty
projection. The column is nullable so a run that predates this revision, or one
still running, simply has no stored projection yet.

The revision is fully reversible: ``downgrade`` drops exactly the column it
added.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the revision."""
    op.add_column(
        "agent_runs",
        sa.Column("public_projection", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="workspace",
    )


def downgrade() -> None:
    """Revert the revision."""
    op.drop_column("agent_runs", "public_projection", schema="workspace")
