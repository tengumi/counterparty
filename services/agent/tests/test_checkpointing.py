"""Tests for the local LangGraph checkpointer adapter."""

from psycopg.conninfo import conninfo_to_dict

from counterparty_agent.checkpointing import workspace_conninfo


def test_deploy_conninfo_pins_framework_schema() -> None:
    """Deployment cannot inherit a caller-selected public search path."""
    conninfo = workspace_conninfo("postgresql://checkpoint-db/db?options=-csearch_path%3Dpublic")
    assert conninfo_to_dict(conninfo)["options"] == "-csearch_path=workspace,pg_catalog"


def test_stored_run_statuses_match_the_public_contract() -> None:
    """The persisted lifecycle needs no translation or guessed public state."""
    from counterparty_contracts import RunStatus
    from counterparty_storage.workspace import AgentRunStatus

    assert {status.value for status in AgentRunStatus} == {status.value for status in RunStatus}
