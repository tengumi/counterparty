"""Create the reports and workspace schemas.

Revision ID: 0001
Revises:
Create Date: 2026-09-05

``reports`` holds the immutable provided source and its typed entities;
``workspace`` holds user work, AI proposals and framework-owned state. The
Alembic version table stays in ``public`` so that both schemas can be dropped
by a downgrade without destroying migration bookkeeping.

Schemas owned by a framework (for example a LangGraph checkpoint namespace such
as ``agent_state``) are deliberately not created here: their DDL belongs to the
library and is applied as its own deployment step. This revision therefore does
not claim that name, and ``env.py`` keeps such a schema out of autogenerate.
"""

from collections.abc import Sequence

from alembic import op
from counterparty_storage import REPORTS_SCHEMA, WORKSPACE_SCHEMA

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMAS = (REPORTS_SCHEMA, WORKSPACE_SCHEMA)


def upgrade() -> None:
    """Create both application schemas."""
    for schema in _SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    """Drop both application schemas.

    ``RESTRICT`` is intentional: if anything unmanaged was created inside one of
    them, the downgrade fails loudly instead of cascading through objects this
    project does not own.
    """
    for schema in reversed(_SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" RESTRICT')
