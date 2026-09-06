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
from uuid import UUID

from counterparty_contracts import ClientRequestId, RunId, RunStatus
from counterparty_storage import ThreadScope
from pydantic import JsonValue

from .durable import DurableRuns
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
    scope: ThreadScope | None = None
    """The trusted ``(tenant, project, thread)`` the RPC resolved, when a
    database is configured. ``None`` in a process without one; the runner then
    falls back to a thin, tenant-less context."""

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
    def scope(self) -> ThreadScope | None:
        """The trusted scope of this run, or ``None`` without a database."""
        return self._run.scope

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


def _based_on_context_version(run: Run) -> int:
    """The project context version this run was accepted against."""
    info = run.initial_state.run
    return 0 if info is None else info.based_on_context_version


class RunRegistry:
    """Process-local owner of active run tasks.

    The replayable event log stays in memory on purpose (Specs 04 §7). When a
    :class:`DurableRuns` mirror is supplied, the run's *lifecycle* is also
    written to ``workspace.agent_runs`` so a restart leaves no run reading as
    forever running and a reconnect can report its durable state.
    """

    def __init__(self, runner: AgentRunner, *, durable: DurableRuns | None = None) -> None:
        """Store the runner and the optional durable lifecycle mirror."""
        self._runner = runner
        self.durable = durable
        self._runs: dict[RunId, Run] = {}
        self._by_request: dict[ClientRequestId, Run] = {}
        self._tasks: dict[RunId, asyncio.Task[None]] = {}

    def get(self, run_id: RunId) -> Run | None:
        """Look up a run that this process started."""
        return self._runs.get(run_id)

    def get_by_request(self, client_request_id: ClientRequestId) -> Run | None:
        """Look up the run a client request already started (retry safety)."""
        return self._by_request.get(client_request_id)

    async def start(self, run: Run, *, scope: ThreadScope | None = None) -> Run:
        """Start the run in its own task, independent of any HTTP response.

        With a durable mirror and a resolved scope, acceptance is written first:
        its failure (a thread that already has an active run) propagates so the
        caller can refuse instead of starting a second run.
        """
        if run.id in self._runs:
            raise ValueError(f"run {run.id} already started")
        run.scope = scope
        if self.durable is not None and scope is not None:
            await self.durable.accept(
                scope,
                run_id=run.id,
                client_request_id=UUID(str(run.client_request_id)),
                based_on_context_version=_based_on_context_version(run),
            )
        self._runs[run.id] = run
        self._by_request[run.client_request_id] = run
        task = asyncio.create_task(self._execute(run), name=f"agent-run-{run.id}")
        self._tasks[run.id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run.id, None))
        return run

    async def cancel(self, run_id: RunId) -> Run | None:
        """Request cooperative cancellation; idempotent per Specs 10 §6."""
        run = self._runs.get(run_id)
        if run is None:
            return None
        run.request_cancel()
        if self.durable is not None and run.scope is not None and not run.finished:
            await self.durable.advance(run.scope, run_id, RunStatus.CANCELLING)
        return run

    async def _execute(self, run: Run) -> None:
        scope = run.scope
        try:
            await self._mirror(run.id, scope, RunStatus.RUNNING)
            await self._runner(RunContext(run))
        except asyncio.CancelledError:
            # The process is stopping. The durable row is left to shutdown
            # recovery (interrupt_active), which cannot race a closing stream.
            run.publish(SetOperation(("run", "status"), RunStatus.CANCELLED.value))
            run.finish()
            raise
        except Exception:
            logger.exception("Agent run %s failed", run.id)
            run.publish(
                SetOperation(("run", "status"), RunStatus.FAILED.value),
                TerminalError("Внутренняя ошибка агента"),
            )
            # Mirror the terminal state before the stream is allowed to close,
            # so a reader that follows the response sees a settled row.
            await self._settle(run, scope, RunStatus.FAILED)
            run.finish()
        else:
            await self._settle(run, scope, run.status)
            run.finish()

    async def _mirror(self, run_id: RunId, scope: ThreadScope | None, status: RunStatus) -> None:
        """Mirror one non-terminal lifecycle transition when a durable scope is known."""
        if self.durable is None or scope is None:
            return
        await self.durable.advance(scope, run_id, status)

    async def _settle(self, run: Run, scope: ThreadScope | None, status: RunStatus) -> None:
        """Mirror the terminal transition and store the folded public projection.

        The projection is folded from the same in-memory event log the stream
        replays; a fold that somehow fails must not keep the run from settling,
        so it degrades to a plain lifecycle mirror.
        """
        if self.durable is None or scope is None:
            return
        # Deferred: projection.py folds the event types defined in this module.
        from .projection import fold_projection

        try:
            projection = fold_projection(run.initial_state, run.events).model_dump(mode="json")
        except Exception:
            logger.exception("Run %s projection fold failed; mirroring lifecycle only", run.id)
            await self.durable.advance(scope, run.id, status)
            return
        await self.durable.finalize(scope, run.id, status, projection)

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
