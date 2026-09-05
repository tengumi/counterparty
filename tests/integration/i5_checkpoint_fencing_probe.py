"""Independently probe stale checkpoint writes after the run-owner connection dies.

Run with the services/agent environment against an isolated migrated database.
The probe inserts synthetic workspace rows only and prints no DSNs or source data.
Exit 1 means a stale worker successfully wrote after replacement recovery.
"""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import TypedDict
from uuid import UUID, uuid4

from counterparty_agent.checkpointing import checkpoint_config, postgres_checkpointer
from counterparty_agent.persistence import postgres_run_owner
from counterparty_storage import ThreadScope, create_database_engine
from counterparty_storage.workspace import AgentRunStatus, Project, Tenant, Thread, User
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class State(TypedDict):
    """Synthetic deterministic checkpoint payload."""

    value: int


def graph_builder() -> StateGraph[State]:
    """Use an official deterministic graph for both separate process lifetimes."""
    builder = StateGraph(State)
    builder.add_node("increment", lambda state: {"value": state["value"] + 1})
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder


async def resume() -> None:
    """Read the committed tuple in a fresh interpreter, then continue from it."""
    scope = ThreadScope(
        tenant_id=UUID(sys.argv[2]),
        project_id=UUID(sys.argv[3]),
        thread_id=UUID(sys.argv[4]),
    )
    async with postgres_run_owner(os.environ["AGENT_TEST_RUNTIME_DSN"]) as owner:
        config = await checkpoint_config(owner, scope)
        async with owner.runs(scope) as repository:
            recovered = await repository.get(UUID(sys.argv[5]))
            assert recovered is not None
            assert recovered.status is AgentRunStatus.INTERRUPTED
        async with postgres_checkpointer(owner) as saver:
            graph = graph_builder().compile(checkpointer=saver)
            assert (await graph.aget_state(config)).values == {"value": 1}
            assert (await graph.ainvoke({"value": 5}, config, durability="sync"))[
                "value"
            ] == 6
    print(json.dumps({"fresh_process_restart": "passed"}))


async def main() -> None:
    """Kill exactly the owner connection, then try the already-open graph saver."""
    admin = os.environ["AGENT_TEST_POSTGRES_DSN"]
    runtime = os.environ["AGENT_TEST_RUNTIME_DSN"]
    engine = create_database_engine(
        admin.replace("postgresql://", "postgresql+psycopg://", 1)
    )
    scope = ThreadScope(tenant_id=uuid4(), project_id=uuid4(), thread_id=uuid4())
    async with AsyncSession(engine) as session, session.begin():
        user_id = uuid4()
        session.add_all(
            [
                Tenant(
                    id=scope.tenant_id, slug=str(scope.tenant_id), title="I5 fixture"
                ),
                User(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    display_name="I5 fixture",
                ),
            ]
        )
        await session.flush()
        session.add(
            Project(
                id=scope.project_id,
                tenant_id=scope.tenant_id,
                owner_id=user_id,
                title="I5 fixture",
            )
        )
        await session.flush()
        session.add(
            Thread(
                id=scope.thread_id,
                project_id=scope.project_id,
                tenant_id=scope.tenant_id,
                title="I5 fixture",
            )
        )

    result: dict[str, object] = {}
    try:
        async with AsyncExitStack() as stack:
            owner = await stack.enter_async_context(postgres_run_owner(runtime))
            config = await checkpoint_config(owner, scope)
            saver = await stack.enter_async_context(postgres_checkpointer(owner))
            graph = graph_builder().compile(checkpointer=saver)
            async with owner.runs(scope) as repository:
                run = await repository.create(
                    client_request_id=uuid4(), based_on_context_version=0
                )
                await repository.set_status(run.id, AgentRunStatus.RUNNING)
            assert (await graph.ainvoke({"value": 0}, config, durability="sync"))[
                "value"
            ] == 1
            previous = await saver.aget_tuple(config)
            assert previous is not None
            async with engine.begin() as connection:
                pid = await connection.scalar(
                    text(
                        "SELECT pid FROM pg_locks WHERE locktype='advisory' "
                        "AND classid=1129337423 AND objid=1 AND objsubid=2 "
                        "AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"
                    )
                )
                assert pid is not None
                await connection.execute(
                    text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                )
            replacement = await stack.enter_async_context(postgres_run_owner(runtime))
            async with replacement.runs(scope) as repository:
                recovered = await repository.get(run.id)
                assert recovered is not None
                result["recovered_run_status"] = recovered.status.value
            try:
                async with owner.runs(scope):
                    result["old_owner_rejected_run_write"] = False
            except Exception:
                result["old_owner_rejected_run_write"] = True
            try:
                stale = await graph.ainvoke({"value": 41}, config, durability="sync")
                result["stale_write_succeeded"] = stale["value"] == 42
                result["persisted_value_after_recovery"] = (
                    await graph.aget_state(config)
                ).values
            except Exception as error:
                result["stale_write_succeeded"] = False
                result["stale_write_error_type"] = type(error).__name__
            for name, mutation in (
                (
                    "aput",
                    saver.aput(
                        previous.config, previous.checkpoint, previous.metadata, {}
                    ),
                ),
                (
                    "aput_writes",
                    saver.aput_writes(previous.config, [("value", 42)], "i5-stale"),
                ),
                (
                    "adelete_thread",
                    saver.adelete_thread(config["configurable"]["thread_id"]),
                ),
            ):
                try:
                    await mutation
                    result[f"stale_{name}_rejected"] = False
                except Exception as error:
                    result[f"stale_{name}_rejected"] = True
                    result[f"stale_{name}_error_type"] = type(error).__name__
            async with postgres_checkpointer(replacement) as live_saver:
                result["checkpoint_unchanged"] = (
                    await live_saver.aget_tuple(config)
                ) == previous
    except Exception as error:
        result["owner_cleanup_error_type"] = type(error).__name__
    finally:
        await engine.dispose()
    required = {
        "old_owner_rejected_run_write": True,
        "recovered_run_status": "interrupted",
        "stale_write_succeeded": False,
        "stale_aput_rejected": True,
        "stale_aput_writes_rejected": True,
        "stale_adelete_thread_rejected": True,
        "checkpoint_unchanged": True,
    }
    passed = all(result.get(key) == value for key, value in required.items())
    if passed:
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            __file__,
            "--resume",
            str(scope.tenant_id),
            str(scope.project_id),
            str(scope.thread_id),
            str(run.id),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, errors = await asyncio.wait_for(child.communicate(), timeout=20)
        assert child.returncode == 0, errors.decode()
        result.update(json.loads(output))
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    asyncio.run(resume() if "--resume" in sys.argv else main())
