"""Real PostgreSQL acceptance for V04; skipped without an isolated test database."""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from counterparty_storage import ThreadScope, create_database_engine
from counterparty_storage.repositories import agent_run_owner
from counterparty_storage.workspace import AgentRunStatus, Project, Tenant, Thread, User
from psycopg import AsyncConnection
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from counterparty_agent.checkpointing import checkpoint_config, postgres_checkpointer
from counterparty_agent.deploy_checkpoints import deploy_checkpoints
from counterparty_agent.persistence import postgres_run_owner

Database = tuple[str, str, AsyncEngine, ThreadScope]


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """Use migrated disposable databases and a non-owner runtime login."""
    admin = os.environ.get("AGENT_TEST_POSTGRES_DSN")
    runtime = os.environ.get("AGENT_TEST_RUNTIME_DSN")
    if not admin or not runtime:
        pytest.skip("AGENT_TEST_POSTGRES_DSN and AGENT_TEST_RUNTIME_DSN are required")
    await deploy_checkpoints(admin)
    engine = create_database_engine(admin.replace("postgresql://", "postgresql+psycopg://", 1))
    scope = ThreadScope(tenant_id=uuid4(), project_id=uuid4(), thread_id=uuid4())
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        user = User(id=uuid4(), email=f"{uuid4()}@example.test", display_name="Fixture")
        session.add_all([user, Tenant(id=scope.tenant_id, slug=str(uuid4()), title="Fixture")])
        await session.flush()
        session.add(
            Project(
                id=scope.project_id,
                tenant_id=scope.tenant_id,
                owner_id=user.id,
                title="Persistence fixture",
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


async def _worker(action: str, runtime: str, scope: ThreadScope, run_id: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("checkpoint_worker.py")),
        action,
        env={
            **os.environ,
            "AGENT_TEST_RUNTIME_DSN": runtime,
            "AGENT_TEST_RUN_ID": run_id,
            "AGENT_TEST_SCOPE": json.dumps(
                {
                    "tenant_id": str(scope.tenant_id),
                    "project_id": str(scope.project_id),
                    "thread_id": str(scope.thread_id),
                }
            ),
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode is not None
    return process.returncode, output.decode()


@pytest.mark.asyncio
async def test_graph_checkpoint_survives_process_crash_and_explicit_continue(
    database: Database,
) -> None:
    """A new process reads the same thread and marks its abandoned run interrupted."""
    admin, runtime, engine, scope = database
    run_id = str(uuid4())
    code, output = await _worker("crash", runtime, scope, run_id)
    assert code == 17, output
    async with engine.connect() as connection:
        status = await connection.scalar(
            text("SELECT status FROM workspace.agent_runs WHERE id=:id"), {"id": run_id}
        )
        assert status == "running"
    code, output = await _worker("continue", runtime, scope, run_id)
    assert code == 0, output
    result = json.loads(output)
    assert result["previous_status"] == "interrupted"
    assert result["messages"] == ["start", "checkpoint survived", "continued"]
    # Deployment is repeatable and does not rewrite saved graph history.
    await deploy_checkpoints(admin)
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM workspace.checkpoints")) > 0
        assert await connection.scalar(text("SELECT to_regclass('public.checkpoints')")) is None


@pytest.mark.asyncio
async def test_scope_mapping_and_runtime_without_ddl(database: Database) -> None:
    """Tenant/project/thread mapping is checked before saver access; runtime owns no DDL."""
    _, runtime, engine, scope = database
    from counterparty_storage import NotFoundError

    async with postgres_run_owner(runtime) as owner:
        own = await checkpoint_config(owner, scope)
        for foreign in [
            ThreadScope(tenant_id=uuid4(), project_id=scope.project_id, thread_id=scope.thread_id),
            ThreadScope(tenant_id=scope.tenant_id, project_id=uuid4(), thread_id=scope.thread_id),
            ThreadScope(tenant_id=scope.tenant_id, project_id=scope.project_id, thread_id=uuid4()),
        ]:
            with pytest.raises(NotFoundError):
                await checkpoint_config(owner, foreign)
        async with AsyncSession(engine) as session, session.begin():
            second = Thread(
                id=uuid4(),
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                title="Second chat",
            )
            session.add(second)
            await session.flush()
            second_id = second.id
        other = await checkpoint_config(
            owner,
            ThreadScope(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                thread_id=second_id,
            ),
        )
        assert own != other
        async with postgres_checkpointer(runtime) as saver:
            assert await saver.aget_tuple(other) is None
    async with await AsyncConnection.connect(runtime, autocommit=True) as connection:
        with pytest.raises(InsufficientPrivilege, match="permission denied"):
            await connection.execute("CREATE TABLE workspace.runtime_must_not_create (id int)")


@pytest.mark.asyncio
async def test_single_worker_and_lost_owner_are_fenced(database: Database) -> None:
    """A live owner's rows cannot be recovered by another worker or mutated after lock loss."""
    _, runtime, engine, scope = database
    runtime_engine = create_database_engine(
        runtime.replace("postgresql://", "postgresql+psycopg://", 1)
    )
    try:
        async with agent_run_owner(runtime_engine) as owner:
            async with owner.runs(scope) as repository:
                run = await repository.create(client_request_id=uuid4(), based_on_context_version=0)
                await repository.set_status(run.id, AgentRunStatus.RUNNING)
            with pytest.raises(RuntimeError, match="another agent worker"):
                async with postgres_run_owner(runtime):
                    pytest.fail("second worker entered")
            # Kill precisely the connection holding the advisory lock. A later
            # transaction must fail, never silently reconnect and write as owner.
            async with engine.begin() as connection:
                pid = await connection.scalar(
                    text(
                        "SELECT pid FROM pg_locks WHERE locktype='advisory' "
                        "AND classid=1129337423 AND objid=1 AND objsubid=2 "
                        "AND database=(SELECT oid FROM pg_database "
                        "WHERE datname=current_database())"
                    )
                )
                await connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            with pytest.raises((RuntimeError, DBAPIError)):
                async with owner.runs(scope) as repository:
                    await repository.set_status(run.id, AgentRunStatus.COMPLETED)
            async with (
                postgres_run_owner(runtime) as replacement,
                replacement.runs(scope) as repository,
            ):
                restored = await repository.get(run.id)
                assert restored is not None and restored.status is AgentRunStatus.INTERRUPTED
    finally:
        await runtime_engine.dispose()


@pytest.mark.asyncio
async def test_one_active_run_and_terminal_recovery(database: Database) -> None:
    """PostgreSQL excludes two active runs; completed history survives restart recovery."""
    _, runtime, _, scope = database
    async with postgres_run_owner(runtime) as owner:
        async with owner.runs(scope) as repository:
            run = await repository.create(client_request_id=uuid4(), based_on_context_version=0)
        with pytest.raises(IntegrityError):
            async with owner.runs(scope) as repository:
                await repository.create(client_request_id=uuid4(), based_on_context_version=0)
        async with owner.runs(scope) as repository:
            await repository.set_status(run.id, AgentRunStatus.COMPLETED)
    async with postgres_run_owner(runtime) as owner, owner.runs(scope) as repository:
        terminal = await repository.get(run.id)
        assert terminal is not None and terminal.status is AgentRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_app_lifespan_recovers_and_shuts_down_without_setup(database: Database) -> None:
    """Actual FastAPI startup owns recovery, rejects another worker and never performs DDL."""
    from typing import cast
    from unittest.mock import patch

    from pydantic import SecretStr

    from counterparty_agent.app import create_app
    from counterparty_agent.composition import AgentResources
    from counterparty_agent.config import AgentSettings

    _, runtime, _, scope = database
    settings = AgentSettings(postgres_dsn=SecretStr(runtime))
    app = create_app(settings)
    second = create_app(settings)
    with patch(
        "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.setup",
        side_effect=AssertionError("worker must not run setup"),
    ):
        async with app.router.lifespan_context(app):
            resources = cast(AgentResources, app.state.resources)
            owner = resources.run_owner
            assert owner is not None
            with pytest.raises(RuntimeError, match="another agent worker"):
                async with second.router.lifespan_context(second):
                    pytest.fail("second app entered")
            async with owner.runs(scope) as repository:
                active = await repository.create(
                    client_request_id=uuid4(), based_on_context_version=0
                )
    async with postgres_run_owner(runtime) as restored, restored.runs(scope) as repository:
        run = await repository.get(active.id)
        assert run is not None and run.status is AgentRunStatus.INTERRUPTED
