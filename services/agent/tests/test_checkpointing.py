"""Tests for the local LangGraph checkpointer adapter."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from counterparty_agent.checkpointing import Checkpointer, postgres_checkpointer


class FakeSaver:
    """Minimal saver double returned by the official factory."""

    async def adelete_thread(self, thread_id: str) -> None:
        """Accept a thread deletion call."""
        del thread_id


@pytest.mark.asyncio
async def test_postgres_adapter_delegates_lifecycle_to_official_saver() -> None:
    """The adapter neither owns connections nor implements checkpoint storage."""
    events: list[str] = []
    saver = FakeSaver()

    @asynccontextmanager
    async def official_factory(dsn: str) -> AsyncIterator[Checkpointer]:
        events.append(f"enter:{dsn}")
        try:
            yield saver
        finally:
            events.append("exit")

    with patch(
        "counterparty_agent.checkpointing.AsyncPostgresSaver.from_conn_string",
        side_effect=official_factory,
    ):
        async with postgres_checkpointer("postgresql://checkpoint-db") as opened:
            assert opened is saver
            assert events == ["enter:postgresql://checkpoint-db"]

    assert events == ["enter:postgresql://checkpoint-db", "exit"]
