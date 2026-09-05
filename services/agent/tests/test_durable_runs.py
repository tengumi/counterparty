"""AG-04: run lifecycle survives the process and a restart reads it honestly.

Skipped without an isolated PostgreSQL. These tests drive the real RPC surface
against a migrated disposable database and a non-owner runtime login, the way
the deployed service runs.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import uvicorn
from counterparty_storage import ThreadScope, create_database_engine
from counterparty_storage.workspace import AgentRunStatus, Project, Tenant, Thread, User
from fastapi.testclient import TestClient
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from counterparty_agent.app import create_app
from counterparty_agent.config import AgentSettings
from counterparty_agent.persistence import postgres_run_owner

Seeded = tuple[str, str, AsyncEngine, ThreadScope]


@pytest.fixture
async def seeded() -> AsyncIterator[Seeded]:
    """A migrated database with one project and thread, plus a runtime login."""
    admin = os.environ.get("AGENT_TEST_POSTGRES_DSN")
    runtime = os.environ.get("AGENT_TEST_RUNTIME_DSN")
    if not admin or not runtime:
        pytest.skip("AGENT_TEST_POSTGRES_DSN and AGENT_TEST_RUNTIME_DSN are required")
    engine = create_database_engine(admin.replace("postgresql://", "postgresql+psycopg://", 1))
    scope = ThreadScope(tenant_id=uuid4(), project_id=uuid4(), thread_id=uuid4())
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        await session.execute(text("DELETE FROM workspace.agent_runs"))
        user = User(id=uuid4(), email=f"{uuid4()}@example.test", display_name="Fixture")
        session.add_all([user, Tenant(id=scope.tenant_id, slug=str(uuid4()), title="Fixture")])
        await session.flush()
        session.add(
            Project(
                id=scope.project_id,
                tenant_id=scope.tenant_id,
                owner_id=user.id,
                title="Durable run fixture",
            )
        )
        await session.flush()
        session.add(
            Thread(
                id=scope.thread_id,
                project_id=scope.project_id,
                tenant_id=scope.tenant_id,
                title="First chat",
            )
        )
    try:
        yield admin, runtime, engine, scope
    finally:
        await engine.dispose()


def _status(admin: str, run_id: str) -> str | None:
    """Read one run's durable status with a plain synchronous connection."""
    with psycopg.connect(admin) as connection:
        row = connection.execute(
            "SELECT status FROM workspace.agent_runs WHERE id = %s", (run_id,)
        ).fetchone()
    return None if row is None else str(row[0])


def _body(scope: ThreadScope, text_: str, *, request_id: UUID | None = None) -> dict[str, Any]:
    return {
        "project_id": str(scope.project_id),
        "thread_id": str(scope.thread_id),
        "client_request_id": str(request_id or uuid4()),
        "stream": True,
        "commands": [
            {
                "type": "add-message",
                "message": {
                    "id": "client-msg-1",
                    "text": text_,
                    "document_ids": [],
                    "evidence_refs": [],
                    "company_ids": [],
                },
            }
        ],
    }


def _run_id(sse: str) -> str:
    for line in sse.splitlines():
        if not line.startswith("data: ") or '"update-state"' not in line:
            continue
        frame = json.loads(line.removeprefix("data: "))
        for op in frame["operations"]:
            if op["path"] == [] and isinstance(op["value"], dict):
                return str(op["value"]["run"]["id"])
    raise AssertionError("no run id in stream")


def _materialize(sse: str) -> dict[str, Any]:
    state: Any = None
    for line in sse.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line.removeprefix("data: ")
        if payload == "[DONE]":
            continue
        frame = json.loads(payload)
        if frame.get("type") != "update-state":
            continue
        for op in frame["operations"]:
            state = _apply(state, op["path"], op)
    assert isinstance(state, dict)
    return state


def _apply(target: Any, path: list[str], op: dict[str, Any]) -> Any:
    if not path:
        return op["value"] if op["type"] == "set" else (target or "") + op["value"]
    head, rest = path[0], path[1:]
    if isinstance(target, list):
        index = int(head)
        copy = list(target)
        if index == len(copy):
            copy.append(_apply(None, rest, op))
        else:
            copy[index] = _apply(copy[index], rest, op)
        return copy
    obj = target if isinstance(target, dict) else {}
    return {**obj, head: _apply(obj.get(head), rest, op)}


@pytest.fixture
def client(seeded: Seeded) -> Iterator[TestClient]:
    """The agent app bound to the runtime DSN, one worker for the database."""
    _, runtime, _, _ = seeded
    with TestClient(create_app(AgentSettings(postgres_dsn=SecretStr(runtime)))) as running:
        yield running


def test_a_completed_run_leaves_a_terminal_row(client: TestClient, seeded: Seeded) -> None:
    """The lifecycle is mirrored: the run ends `completed` in the durable row."""
    admin, _, _, scope = seeded
    sse = client.post("/rpc/agent/chat", json=_body(scope, "Проверь условия")).text
    run_id = _run_id(sse)

    assert _materialize(sse)["run"]["status"] == "completed"
    assert _status(admin, run_id) == "completed"


def test_an_unknown_project_or_thread_is_refused(client: TestClient, seeded: Seeded) -> None:
    """The RPC verifies the scope; it does not run for an id it cannot resolve."""
    _, _, _, scope = seeded
    stray = dict(_body(scope, "Проверь условия"))
    stray["thread_id"] = str(uuid4())

    assert client.post("/rpc/agent/chat", json=stray).status_code == 404


@pytest.mark.asyncio
async def test_one_active_run_per_thread_is_enforced(seeded: Seeded) -> None:
    """A second run on a thread that already has an active one is a conflict."""
    admin, runtime, _, scope = seeded
    config = uvicorn.Config(
        create_app(AgentSettings(postgres_dsn=SecretStr(runtime))),
        host="127.0.0.1",
        port=0,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    run_id = ""
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10.0) as http:
            collected: list[str] = []
            async with http.stream("POST", "/rpc/agent/chat", json=_body(scope, "/slow")) as first:
                assert first.status_code == 200
                async for line in first.aiter_lines():
                    collected.append(line)
                    if run_id == "" and '"update-state"' in line:
                        try:
                            run_id = _run_id("\n".join(collected))
                        except AssertionError:
                            continue
                        second = await http.post(
                            "/rpc/agent/chat", json=_body(scope, "Проверь условия")
                        )
                        assert second.status_code == 409
                        cancelled = await http.post(f"/rpc/agent/runs/{run_id}/cancel")
                        assert cancelled.status_code == 200
                        break
    finally:
        server.should_exit = True
        await task
    assert run_id
    assert _status(admin, run_id) == "cancelled"


@pytest.mark.asyncio
async def test_a_restart_reads_an_interrupted_run_as_interrupted(seeded: Seeded) -> None:
    """A run abandoned by a dead worker is not forever running after a restart."""
    admin, runtime, _, scope = seeded
    async with postgres_run_owner(runtime) as owner, owner.runs(scope) as repository:
        run = await repository.create(client_request_id=uuid4(), based_on_context_version=0)
        await repository.set_status(run.id, AgentRunStatus.RUNNING)
    # Leaving the owner marks its still-active run interrupted (recovery on exit).
    assert _status(admin, str(run.id)) == "interrupted"

    with TestClient(create_app(AgentSettings(postgres_dsn=SecretStr(runtime)))) as restarted:
        lifecycle = restarted.get(f"/rpc/agent/runs/{run.id}")
        assert lifecycle.status_code == 200
        assert lifecycle.json()["run"]["status"] == "interrupted"

        replay = restarted.post(f"/rpc/agent/runs/{run.id}/subscribe")
        assert replay.status_code == 200
        state = _materialize(replay.text)
        assert state["run"]["status"] == "interrupted"
        assert state["messages"] == []
        assert state["save_status"] == "saved"


def test_an_unknown_run_is_still_not_found(client: TestClient) -> None:
    """A run that was never accepted is 404 on every lifecycle endpoint."""
    missing = uuid4()
    assert client.get(f"/rpc/agent/runs/{missing}").status_code == 404
    assert client.post(f"/rpc/agent/runs/{missing}/cancel").status_code == 404
    assert client.post(f"/rpc/agent/runs/{missing}/subscribe").status_code == 404


@pytest.mark.asyncio
async def test_the_rpc_resolves_a_trusted_scope_from_the_project(seeded: Seeded) -> None:
    """The tenant comes from the project row; a foreign thread does not resolve."""
    _, runtime, _, scope = seeded
    async with postgres_run_owner(runtime) as owner:
        resolved = await owner.resolve_thread_scope(
            project_id=scope.project_id, thread_id=scope.thread_id
        )
        assert resolved is not None
        assert resolved.tenant_id == scope.tenant_id
        assert resolved.project_id == scope.project_id

        assert (
            await owner.resolve_thread_scope(project_id=scope.project_id, thread_id=uuid4()) is None
        )
        assert (
            await owner.resolve_thread_scope(project_id=uuid4(), thread_id=scope.thread_id) is None
        )
