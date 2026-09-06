"""Application and resource lifecycle tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import uuid4

import pytest
from counterparty_contracts import ThreadId
from counterparty_storage.repositories import AgentRunOwner
from fastapi.testclient import TestClient
from pydantic import SecretStr

from counterparty_agent.app import create_app
from counterparty_agent.checkpointing import Checkpointer
from counterparty_agent.composition import AgentResources
from counterparty_agent.config import AgentSettings


@asynccontextmanager
async def fake_owner(_: str) -> AsyncIterator[AgentRunOwner]:
    """Keep unit resource tests independent of a database."""
    yield cast(AgentRunOwner, object())


class FakeCheckpointer:
    """Test double implementing the service-local saver boundary."""

    def __init__(self) -> None:
        """Initialize an empty deletion record."""
        self.deleted_threads: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        """Record the thread passed through the boundary."""
        self.deleted_threads.append(thread_id)


def test_health_without_database_configuration() -> None:
    """The independently runnable shell does not require PostgreSQL."""
    with TestClient(create_app(AgentSettings(postgres_dsn=None))) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "counterparty-agent",
        "checkpoint_backend": "not_configured",
    }


def test_import_does_not_open_checkpointer() -> None:
    """Constructing the app leaves external resources for lifespan startup."""
    opened = False

    @asynccontextmanager
    async def factory(_: AgentRunOwner) -> AsyncIterator[Checkpointer]:
        nonlocal opened
        opened = True
        yield FakeCheckpointer()

    create_app(
        AgentSettings(postgres_dsn=SecretStr("postgresql://unused")),
        checkpointer_factory=factory,
        run_owner_factory=fake_owner,
    )

    assert opened is False


@pytest.mark.asyncio
async def test_configured_checkpointer_is_owned_by_lifespan() -> None:
    """Startup opens one saver and shutdown closes the same saver."""
    events: list[str] = []
    fake = FakeCheckpointer()

    @asynccontextmanager
    async def factory(owner: AgentRunOwner) -> AsyncIterator[Checkpointer]:
        assert owner is not None
        events.append("open")
        try:
            yield fake
        finally:
            events.append("close")

    app = create_app(
        AgentSettings(postgres_dsn=SecretStr("postgresql://agent:secret@db/workspace")),
        checkpointer_factory=factory,
        run_owner_factory=fake_owner,
    )

    async with app.router.lifespan_context(app):
        resources = cast(AgentResources, app.state.resources)
        assert resources.checkpointer is fake
        await fake.adelete_thread(str(ThreadId(uuid4())))
        assert events == ["open"]

    assert events == ["open", "close"]
