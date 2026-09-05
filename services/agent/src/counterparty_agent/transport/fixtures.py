"""Deterministic wire fixtures shared with the web transport tests.

The bytes are produced by the real `assistant-stream` encoder, so the browser
test decodes exactly what the service sends instead of a hand-written stream.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from counterparty_contracts import ClientRequestId, ProjectId, RunId, ThreadId

from .delivery import stream_run
from .public_state import PublicMessage, TextBlock, initial_state
from .runs import Run, RunRegistry
from .stub_agent import deterministic_agent

FIXTURE_PROJECT_ID = ProjectId(UUID("00000000-0000-4000-8000-000000000001"))
FIXTURE_THREAD_ID = ThreadId(UUID("00000000-0000-4000-8000-000000000002"))
FIXTURE_REQUEST_ID = ClientRequestId(UUID("00000000-0000-4000-8000-000000000003"))
FIXTURE_RUN_ID = RunId(UUID("00000000-0000-4000-8000-000000000004"))
FIXTURE_STARTED_AT = datetime(2025, 9, 5, 9, 0, tzinfo=UTC)

FIXTURE_PROMPTS = {
    "answer": "Можно ли перечислять 80% аванса?",
    "error": "/fail проверь отчёт",
    "cancelled": "/slow проверь отчёт",
}
_CANCEL_AFTER_EVENTS = 4


def _build_run(prompt: str) -> Run:
    return Run(
        id=FIXTURE_RUN_ID,
        client_request_id=FIXTURE_REQUEST_ID,
        initial_state=initial_state(
            project_id=FIXTURE_PROJECT_ID,
            thread_id=FIXTURE_THREAD_ID,
            run_id=FIXTURE_RUN_ID,
            started_at=FIXTURE_STARTED_AT,
            user_message=PublicMessage(
                id="client-msg-1",
                role="user",
                blocks=[TextBlock(text=prompt)],
                status="complete",
                created_at=FIXTURE_STARTED_AT,
            ),
        ),
        prompt=prompt,
    )


async def _drain(run: Run) -> str:
    response = stream_run(run)
    body: AsyncIterator[bytes | str] = response.body_iterator  # type: ignore[attr-defined]
    parts = [part.decode() if isinstance(part, bytes) else part async for part in body]
    return "".join(parts)


async def render(name: str) -> str:
    """Encode one named V01 case exactly as the service would send it."""
    run = _build_run(FIXTURE_PROMPTS[name])
    async with RunRegistry(deterministic_agent) as registry:
        await registry.start(run)
        if name == "cancelled":
            while len(run.events) < _CANCEL_AFTER_EVENTS:
                await asyncio.sleep(0)
            run.request_cancel()
        return await _drain(run)
