"""Agent runs owned by the process, not by any single streaming response.

Specs 04 §7 requires the agent task to survive a closed response: leaving the
page must stop the subscription, not the run. The task is therefore started
here and every response subscribes to its replayable event log.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from types import TracebackType

from counterparty_contracts import ClientRequestId, RunId, RunStatus
from pydantic import JsonValue

from .public_state import PublicAgentState

logger = logging.getLogger(__name__)

StatePath = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SetOperation:
    """Replace the value at one path of the public projection."""

    path: StatePath
    value: JsonValue


@dataclass(frozen=True, slots=True)
class AppendItemOperation:
    """Append one item to the list at `path`.

    A separate event kind because the library proxy grows lists through
    `append`; addressing index `len(list)` directly is rejected.
    """

    path: StatePath
    value: JsonValue


@dataclass(frozen=True, slots=True)
class AppendTextOperation:
    """Append a text delta at one path of the public projection."""

    path: StatePath
    text: str


@dataclass(frozen=True, slots=True)
class TerminalError:
    """Safe terminal failure signalled outside the state projection."""

    message: str


RunEvent = SetOperation | AppendItemOperation | AppendTextOperation | TerminalError


@dataclass(eq=False)
class Run:
    """One agent execution and its replayable public event log."""

    id: RunId
    client_request_id: ClientRequestId
    initial_state: PublicAgentState
    prompt: str
    status: RunStatus = field(default=RunStatus.ACCEPTED, init=False)
    _events: list[RunEvent] = field(default_factory=list, init=False)
    _changed: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _cancelling: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _finished: bool = field(default=False, init=False)

    @property
    def events(self) -> Sequence[RunEvent]:
        """Everything published so far, in publication order."""
        return tuple(self._events)

    @property
    def finished(self) -> bool:
        """Whether no further event will be published."""
        return self._finished

    @property
    def cancel_requested(self) -> bool:
        """Whether an explicit cancel command was accepted for this run."""
        return self._cancelling.is_set()

    def publish(self, *events: RunEvent) -> None:
        """Append events for every current and future subscriber."""
        if self._finished:
            logger.warning("Ignored event published after run %s finished", self.id)
            return
        for event in events:
            if isinstance(event, SetOperation) and event.path == ("run", "status"):
                self.status = RunStatus(str(event.value))
        self._events.extend(events)
        self._changed.set()

    def finish(self) -> None:
        """Close the log so subscribers complete."""
        self._finished = True
        self._changed.set()

    def request_cancel(self) -> None:
        """Ask the run to stop cooperatively; safe to call repeatedly."""
        self._cancelling.set()

    async def wait_cancel(self, timeout: float) -> bool:
        """Sleep up to `timeout`, returning True as soon as cancel is requested."""
        try:
            await asyncio.wait_for(self._cancelling.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    async def subscribe(self) -> AsyncIterator[RunEvent]:
        """Replay the log from the beginning, then follow it until the run ends."""
        index = 0
        while True:
            while index < len(self._events):
                yield self._events[index]
                index += 1
            if self._finished:
                return
            self._changed.clear()
            if index < len(self._events) or self._finished:
                continue
            await self._changed.wait()


class RunContext:
    """Publishing surface handed to the agent implementation."""

    __slots__ = ("_run",)

    def __init__(self, run: Run) -> None:
        """Bind the context to one run."""
        self._run = run

    @property
    def run(self) -> Run:
        """The run being executed."""
        return self._run

    @property
    def prompt(self) -> str:
        """Text of the message that started this run."""
        return self._run.prompt

    @property
    def cancel_requested(self) -> bool:
        """Whether the run should stop at the next safe boundary."""
        return self._run.cancel_requested

    def set(self, path: StatePath, value: JsonValue) -> None:
        """Publish a `set` operation."""
        self._run.publish(SetOperation(path, value))

    def append_item(self, path: StatePath, value: JsonValue) -> None:
        """Publish an append to the list at `path`."""
        self._run.publish(AppendItemOperation(path, value))

    def append_text(self, path: StatePath, text: str) -> None:
        """Publish an `append-text` operation."""
        self._run.publish(AppendTextOperation(path, text))

    def fail(self, message: str) -> None:
        """Publish a terminal error frame."""
        self._run.publish(TerminalError(message))

    async def pause(self, seconds: float) -> bool:
        """Wait at a safe boundary; return True when cancel arrived first."""
        return await self._run.wait_cancel(seconds)


AgentRunner = Callable[[RunContext], Awaitable[None]]


class RunRegistry:
    """Process-local owner of active run tasks."""

    def __init__(self, runner: AgentRunner) -> None:
        """Store the runner used for every run started here."""
        self._runner = runner
        self._runs: dict[RunId, Run] = {}
        self._by_request: dict[ClientRequestId, Run] = {}
        self._tasks: dict[RunId, asyncio.Task[None]] = {}

    def get(self, run_id: RunId) -> Run | None:
        """Look up a run that this process started."""
        return self._runs.get(run_id)

    def get_by_request(self, client_request_id: ClientRequestId) -> Run | None:
        """Look up the run a client request already started (retry safety)."""
        return self._by_request.get(client_request_id)

    def start(self, run: Run) -> Run:
        """Start the run in its own task, independent of any HTTP response."""
        if run.id in self._runs:
            raise ValueError(f"run {run.id} already started")
        self._runs[run.id] = run
        self._by_request[run.client_request_id] = run
        task = asyncio.create_task(self._execute(run), name=f"agent-run-{run.id}")
        self._tasks[run.id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run.id, None))
        return run

    def cancel(self, run_id: RunId) -> Run | None:
        """Request cooperative cancellation; idempotent per Specs 10 §6."""
        run = self._runs.get(run_id)
        if run is not None:
            run.request_cancel()
        return run

    async def _execute(self, run: Run) -> None:
        try:
            await self._runner(RunContext(run))
        except asyncio.CancelledError:
            run.publish(SetOperation(("run", "status"), RunStatus.CANCELLED.value))
            run.finish()
            raise
        except Exception:
            logger.exception("Agent run %s failed", run.id)
            run.publish(
                SetOperation(("run", "status"), RunStatus.FAILED.value),
                TerminalError("Внутренняя ошибка агента"),
            )
            run.finish()
        else:
            run.finish()

    async def aclose(self) -> None:
        """Stop remaining tasks during a bounded graceful shutdown."""
        tasks = list(self._tasks.values())
        for run in self._runs.values():
            run.request_cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=1.0)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._runs.clear()
        self._by_request.clear()
        self._tasks.clear()

    async def __aenter__(self) -> "RunRegistry":
        """Enter the registry scope."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Leave the registry scope, stopping active runs."""
        await self.aclose()
