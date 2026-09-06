"""Fresh-process worker for the V04 PostgreSQL crash/restart proof."""

import asyncio
import json
import os
import sys
from typing import TypedDict
from uuid import UUID, uuid4

from counterparty_storage import ThreadScope
from counterparty_storage.workspace import AgentRunStatus
from langgraph.graph import END, START, StateGraph

from counterparty_agent.checkpointing import checkpoint_config, postgres_checkpointer
from counterparty_agent.persistence import postgres_run_owner


class SpikeState(TypedDict):
    """Small deterministic graph state, persisted by the official saver."""

    messages: list[str]
    phase: str


async def run() -> None:
    """Crash after a durable checkpoint or explicitly continue in a new process."""
    dsn = os.environ["AGENT_TEST_RUNTIME_DSN"]
    scope = ThreadScope(
        **{key: UUID(value) for key, value in json.loads(os.environ["AGENT_TEST_SCOPE"]).items()}
    )
    run_id = UUID(os.environ["AGENT_TEST_RUN_ID"])
    crash = sys.argv[1] == "crash"

    def prepare(state: SpikeState) -> SpikeState:
        return {"messages": [*state["messages"], "checkpoint survived"], "phase": "prepared"}

    def complete(state: SpikeState) -> SpikeState:
        if crash:
            # This exits inside a graph node: no lifespan/finally/connection cleanup.
            os._exit(17)
        return {"messages": [*state["messages"], "continued"], "phase": "complete"}

    async with postgres_run_owner(dsn) as owner:
        config = await checkpoint_config(owner, scope)
        async with postgres_checkpointer(owner) as saver:
            builder = StateGraph(SpikeState)
            builder.add_node("prepare", prepare)
            builder.add_node("complete", complete)
            builder.add_edge(START, "prepare")
            builder.add_edge("prepare", "complete")
            builder.add_edge("complete", END)
            graph = builder.compile(checkpointer=saver)
            if crash:
                async with owner.runs(scope) as repository:
                    await repository.create(
                        run_id=run_id,
                        client_request_id=uuid4(),
                        based_on_context_version=0,
                    )
                    await repository.set_status(run_id, AgentRunStatus.RUNNING)
                await graph.ainvoke(
                    {"messages": ["start"], "phase": "new"},
                    config,
                    durability="sync",
                )
                raise AssertionError("crash node did not exit")
            async with owner.runs(scope) as repository:
                previous = await repository.get(run_id)
                assert previous is not None and previous.status is AgentRunStatus.INTERRUPTED
                previous_status = previous.status.value
                new_run = await repository.create(
                    client_request_id=uuid4(),
                    based_on_context_version=0,
                )
                await repository.set_status(new_run.id, AgentRunStatus.RUNNING)
            snapshot = await graph.aget_state(config)
            assert snapshot.values["phase"] == "prepared"
            assert snapshot.next == ("complete",)
            result = await graph.ainvoke(None, config, durability="sync")
            assert result["messages"] == ["start", "checkpoint survived", "continued"]
            async with owner.runs(scope) as repository:
                await repository.set_status(new_run.id, AgentRunStatus.COMPLETED)
            print(
                json.dumps(
                    {
                        "previous_status": previous_status,
                        "phase": result["phase"],
                        "messages": result["messages"],
                        "new_run_id": str(new_run.id),
                    }
                )
            )


if __name__ == "__main__":
    asyncio.run(run())
