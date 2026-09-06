"""Deterministic stand-in for the agent graph.

The spike verifies the transport, not reasoning: this runner emits exactly the
four V01 event shapes (text, typed activity, terminal error, cancel) without a
model call, so the same assertions hold in tests and in the browser.
"""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import NamedTuple

from counterparty_contracts import RunStatus

from .runs import RunContext


class _Paths(NamedTuple):
    """Where this run's own message and activity sit once appended.

    The projection carries the whole thread, so with prior turns seeded into
    ``initial_state`` the run's items land after them, not at a fixed 1/0.
    """

    msg: str
    act: str
    text: tuple[str, ...]


def _paths(ctx: RunContext) -> _Paths:
    state = ctx.run.initial_state
    msg = str(len(state.messages))
    act = str(len(state.activities))
    return _Paths(msg=msg, act=act, text=("messages", msg, "blocks", "0", "text"))
_ANSWER_CHUNKS = (
    "Смотрю условия поставки. ",
    "Аванс 80% от 2,4 млн ₽ — это 1,92 млн ₽ до отгрузки. ",
    "Срок «21 день после комплектации» не задаёт дату отгрузки.",
)
_SLOW_STEPS = 40
_SLOW_STEP_SECONDS = 0.05
_ANSWER_STEP_SECONDS = 0.0


class Scenario(StrEnum):
    """Which V01 case a request asks the stub to reproduce."""

    ANSWER = "answer"
    FAIL = "fail"
    SLOW = "slow"

    @classmethod
    def from_prompt(cls, prompt: str) -> "Scenario":
        """Pick a scenario from an explicit spike marker in the message text."""
        marker = prompt.strip().split(maxsplit=1)[0] if prompt.strip() else ""
        if marker == "/fail":
            return cls.FAIL
        if marker == "/slow":
            return cls.SLOW
        return cls.ANSWER


def _at(ctx: RunContext, seconds: float) -> str:
    started: datetime = _started_at(ctx)
    return (started + timedelta(seconds=seconds)).isoformat()


def _started_at(ctx: RunContext) -> datetime:
    run_info = ctx.run.initial_state.run
    if run_info is None:  # pragma: no cover - runs always carry RunInfo
        raise ValueError("run projection must carry RunInfo")
    return run_info.started_at


def _begin(ctx: RunContext, paths: _Paths) -> None:
    ctx.set(("run", "status"), RunStatus.RUNNING.value)
    ctx.append_item(
        ("activities",),
        {
            "id": f"activity-{paths.msg}",
            "kind": "reading_document",
            "label": "Читаю условия поставки",
            "status": "running",
            "evidence_refs": [],
            "started_at": _at(ctx, 0),
            "finished_at": None,
        },
    )
    ctx.append_item(
        ("messages",),
        {
            "id": f"assistant-{paths.msg}",
            "role": "assistant",
            "blocks": [{"type": "text", "text": ""}],
            "status": "streaming",
            "created_at": _at(ctx, 0),
        },
    )


def _settle(
    ctx: RunContext, *, status: RunStatus, message_status: str, revision: int, paths: _Paths
) -> None:
    ctx.set(("messages", paths.msg, "status"), message_status)
    ctx.set(("run", "status"), status.value)
    ctx.set(("run", "finished_at"), _at(ctx, 1))
    ctx.set(("run", "last_public_revision"), revision)
    ctx.set(("revision",), revision)
    ctx.set(("save_status",), "saved")


async def deterministic_agent(ctx: RunContext) -> None:
    """Emit one V01 case, checking cancellation at every safe boundary."""
    scenario = Scenario.from_prompt(ctx.prompt)
    paths = _paths(ctx)
    _begin(ctx, paths)

    if scenario is Scenario.FAIL:
        ctx.set(("activities", paths.act, "status"), "failed")
        ctx.set(("activities", paths.act, "finished_at"), _at(ctx, 1))
        _settle(ctx, status=RunStatus.FAILED, message_status="error", revision=1, paths=paths)
        ctx.set(
            ("run", "error"),
            {
                "schema_version": "0.1",
                "code": "dependency_unavailable",
                "message": "Источник сведений недоступен. Попробуйте позже.",
                "retryable": True,
                "request_id": str(ctx.run.id),
                "details": None,
            },
        )
        ctx.fail("Источник сведений недоступен. Попробуйте позже.")
        return

    slow = scenario is Scenario.SLOW
    if slow:
        # Emit before the first boundary so a cancel still leaves partial output.
        ctx.append_text(paths.text, "Разбираю документ, это займёт время…")
    steps = _SLOW_STEPS if slow else len(_ANSWER_CHUNKS)
    step_seconds = _SLOW_STEP_SECONDS if slow else _ANSWER_STEP_SECONDS
    for step in range(steps):
        if await ctx.pause(step_seconds):
            ctx.set(("run", "status"), RunStatus.CANCELLING.value)
            ctx.set(("activities", paths.act, "status"), "failed")
            ctx.set(("activities", paths.act, "finished_at"), _at(ctx, 1))
            _settle(
                ctx,
                status=RunStatus.CANCELLED,
                message_status="partial",
                revision=1,
                paths=paths,
            )
            return
        if not slow:
            ctx.append_text(paths.text, _ANSWER_CHUNKS[step])

    ctx.set(("activities", paths.act, "status"), "completed")
    ctx.set(("activities", paths.act, "finished_at"), _at(ctx, 1))
    _settle(ctx, status=RunStatus.COMPLETED, message_status="complete", revision=1, paths=paths)
