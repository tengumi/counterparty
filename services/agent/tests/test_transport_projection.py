"""Folding a run's in-memory event log into its final public projection.

The agent persists this fold when a run finishes so a client that opens the
chat afterwards reads the real history. The fold has to land on the same
projection the streaming path builds, event for event.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from counterparty_contracts import ClientRequestId, ProjectId, RunId, ThreadId

from counterparty_agent.transport.projection import fold_projection
from counterparty_agent.transport.public_state import (
    PublicActivity,
    PublicMessage,
    TextBlock,
    initial_state,
)
from counterparty_agent.transport.runs import Run, RunRegistry
from counterparty_agent.transport.stub_agent import deterministic_agent

_PROJECT = ProjectId(UUID("00000000-0000-4000-8000-0000000000a1"))
_THREAD = ThreadId(UUID("00000000-0000-4000-8000-0000000000a2"))
_REQUEST = ClientRequestId(UUID("00000000-0000-4000-8000-0000000000a3"))
_RUN = RunId(UUID("00000000-0000-4000-8000-0000000000a4"))
_STARTED = datetime(2025, 9, 5, 9, 0, tzinfo=UTC)


def _run(prompt: str) -> Run:
    return Run(
        id=_RUN,
        client_request_id=_REQUEST,
        initial_state=initial_state(
            project_id=_PROJECT,
            thread_id=_THREAD,
            run_id=_RUN,
            started_at=_STARTED,
            user_message=PublicMessage(
                id="client-msg-1",
                role="user",
                blocks=[TextBlock(text=prompt)],
                status="complete",
                created_at=_STARTED,
            ),
        ),
        prompt=prompt,
    )


async def _finished(prompt: str, *, cancel_after: int | None = None) -> Run:
    run = _run(prompt)
    async with RunRegistry(deterministic_agent) as registry:
        await registry.start(run)
        if cancel_after is not None:
            while len(run.events) < cancel_after:
                await asyncio.sleep(0)
            run.request_cancel()
        while not run.finished:
            await asyncio.sleep(0)
    return run


@pytest.mark.asyncio
async def test_a_completed_run_folds_to_the_full_answer() -> None:
    """The user message stays and the assistant message carries the joined text."""
    run = await _finished("Можно ли перечислять 80% аванса?")

    state = fold_projection(run.initial_state, run.events)

    assert [message.role for message in state.messages] == ["user", "assistant"]
    assistant = state.messages[1]
    assert assistant.status == "complete"
    assert assistant.blocks[0].text.startswith("Смотрю условия поставки.")
    assert "не задаёт дату отгрузки" in assistant.blocks[0].text
    assert [activity.status for activity in state.activities] == ["completed"]
    assert state.run is not None and state.run.status == "completed"
    assert state.save_status == "saved"
    assert state.revision == 1


@pytest.mark.asyncio
async def test_the_fold_joins_every_text_delta_from_the_log() -> None:
    """No append-text delta is dropped or reordered by the fold."""
    from counterparty_agent.transport.runs import AppendTextOperation

    run = await _finished("Можно ли перечислять 80% аванса?")
    deltas = "".join(event.text for event in run.events if isinstance(event, AppendTextOperation))

    state = fold_projection(run.initial_state, run.events)

    assert deltas != ""
    assert state.messages[1].blocks[0].text == deltas


@pytest.mark.asyncio
async def test_a_cancelled_run_keeps_its_partial_output() -> None:
    """A cancel at a safe boundary still leaves the text emitted so far."""
    run = await _finished("/slow проверь отчёт", cancel_after=4)

    state = fold_projection(run.initial_state, run.events)

    assert state.run is not None and state.run.status == "cancelled"
    assert state.messages[1].status == "partial"
    assert state.messages[1].blocks[0].text.startswith("Разбираю документ")


@pytest.mark.asyncio
async def test_a_run_seeded_with_prior_turns_folds_to_the_whole_thread() -> None:
    """Prior messages and activities from the last projection are carried through.

    This is what keeps a thread's history whole across runs: the new run folds
    its events onto the previous projection, and its own turn is appended, not
    substituted for the earlier ones.
    """
    prior_user = PublicMessage(
        id="turn-1-user",
        role="user",
        blocks=[TextBlock(text="Первый вопрос")],
        status="complete",
        created_at=_STARTED,
    )
    prior_answer = PublicMessage(
        id="turn-1-assistant",
        role="assistant",
        blocks=[TextBlock(text="Первый ответ")],
        status="complete",
        created_at=_STARTED,
    )
    prior_activity = PublicActivity(
        id="turn-1-act", kind="reading_report", label="Читаю отчёт", status="completed"
    )
    run = Run(
        id=_RUN,
        client_request_id=_REQUEST,
        initial_state=initial_state(
            project_id=_PROJECT,
            thread_id=_THREAD,
            run_id=_RUN,
            started_at=_STARTED,
            user_message=PublicMessage(
                id="turn-2-user",
                role="user",
                blocks=[TextBlock(text="Можно ли перечислять 80% аванса?")],
                status="complete",
                created_at=_STARTED,
            ),
            prior_messages=[prior_user, prior_answer],
            prior_activities=[prior_activity],
        ),
        prompt="Можно ли перечислять 80% аванса?",
    )
    async with RunRegistry(deterministic_agent) as registry:
        await registry.start(run)
        while not run.finished:
            await asyncio.sleep(0)

    state = fold_projection(run.initial_state, run.events)

    assert [m.id for m in state.messages[:3]] == [
        "turn-1-user",
        "turn-1-assistant",
        "turn-2-user",
    ]
    assert state.messages[3].role == "assistant"
    assert state.messages[3].blocks[0].text  # the new answer, appended
    assert any(a.id == "turn-1-act" for a in state.activities)
    assert state.run is not None and state.run.status == "completed"
