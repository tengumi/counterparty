"""Create the service roles and grant them what they are allowed to do.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05

Each service connects as its own PostgreSQL role, so what it may do is decided
by the database rather than by the code that happens to run inside it: the
importer writes only ``reports``, MCP only reads ``reports``, the UI backend
reads both schemas and writes only ``workspace``, and the agent reads the
project context and may update one column of a thread — it holds no privilege
on ``reports`` at all, because it reaches report facts through MCP.

The whole matrix lives in ``counterparty_storage.roles``. It is declared once,
asserted by the storage tests, executed here and checked against a running
PostgreSQL by ``migrations/tests/test_role_privileges.py``.

The roles are created ``NOLOGIN``. They are group roles: a deployment creates
its own login user, grants it the matching group and keeps the password out of
this repository. Roles are cluster-wide rather than per database, so creation
is written to be safe on a cluster that already hosts them.

Framework-owned checkpoint storage lives in a namespace this project does not
own. Granting privileges there belongs to the deployment step that creates it
and is deliberately absent from this revision.
"""

from collections.abc import Sequence

from alembic import op
from counterparty_storage.roles import (
    create_role_statements,
    grant_statements,
    revoke_statements,
)

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the four group roles and apply the privilege matrix."""
    for statement in create_role_statements():
        op.execute(statement)
    for statement in grant_statements():
        op.execute(statement)


def downgrade() -> None:
    """Hand back only the privileges owned by this database.

    PostgreSQL roles are cluster-wide while Alembic revisions are per database.
    Dropping a role here would either fail when another project database still
    grants it privileges or, worse, remove a group role that database needs.
    The NOLOGIN groups therefore outlive a database-local downgrade; explicit
    cluster decommissioning owns their eventual removal.
    """
    for statement in revoke_statements():
        op.execute(statement)
