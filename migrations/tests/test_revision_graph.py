"""Checks on the revision graph that need no database."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent


def _scripts() -> ScriptDirectory:
    config = Config(str(MIGRATIONS_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return ScriptDirectory.from_config(config)


def test_single_head() -> None:
    """One linear history keeps deployment order unambiguous."""
    assert len(_scripts().get_heads()) == 1


def test_every_revision_is_reversible() -> None:
    """Each revision defines a downgrade, so a deploy can be rolled back."""
    for revision in _scripts().walk_revisions():
        module = revision.module
        assert hasattr(module, "downgrade"), revision.revision
        source = Path(str(revision.path)).read_text(encoding="utf-8")
        assert "def downgrade()" in source
        assert "raise NotImplementedError" not in source


def test_env_only_manages_owned_schemas() -> None:
    """Autogenerate never looks at a schema owned by a framework.

    A future LangGraph checkpoint namespace (for example ``agent_state``) is
    created by its own deployment step; these revisions must neither claim that
    name nor propose dropping its tables.
    """
    import schema_policy as env

    assert env.include_name("reports", "schema", {}) is True
    assert env.include_name("workspace", "schema", {}) is True
    assert env.include_name("agent_state", "schema", {}) is False
    assert env.include_name("checkpoints", "table", {"schema_name": "agent_state"}) is False
    assert env.include_name("companies", "table", {"schema_name": "reports"}) is True


def test_no_revision_claims_a_framework_schema() -> None:
    """The project's own DDL stays inside reports and workspace."""
    for revision in _scripts().walk_revisions():
        source = Path(str(revision.path)).read_text(encoding="utf-8")
        assert "agent_state" not in source.split('"""', 2)[-1]
