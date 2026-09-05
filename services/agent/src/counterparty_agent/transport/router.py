"""HTTP surface of the agent RPC transport (Specs 10 §6)."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from counterparty_contracts import (
    ClientRequestId,
    ProjectId,
    RunId,
    RunInfo,
    ThreadId,
)
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from .delivery import stream_projection, stream_run
from .durable import ActiveRunExists, is_terminal
from .public_state import PublicAgentState, PublicMessage, TextBlock, initial_state
from .runs import Run, RunRegistry


class ChatMessage(BaseModel):
    """Domain message carried by an `add-message` command."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str
    document_ids: list[UUID] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    company_ids: list[UUID] = Field(default_factory=list)


class AddMessageCommand(BaseModel):
    """The only command this spike executes."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["add-message"]
    message: ChatMessage


class ChatRequest(BaseModel):
    """Body of `POST /rpc/agent/chat`."""

    model_config = ConfigDict(extra="forbid")

    project_id: ProjectId
    thread_id: ThreadId
    client_request_id: ClientRequestId
    stream: Literal[True] = True
    commands: list[AddMessageCommand] = Field(min_length=1)


class RunSnapshot(BaseModel):
    """Lifecycle view returned by the non-streaming run endpoints."""

    model_config = ConfigDict(extra="forbid")

    run: RunInfo
    revision: int = Field(ge=0)


def _resources(request: Request) -> RunRegistry:
    registry = getattr(request.app.state, "runs", None)
    if not isinstance(registry, RunRegistry):  # pragma: no cover - lifespan always sets it
        raise HTTPException(status_code=503, detail="run registry unavailable")
    return registry


def _run_info(run: Run) -> RunInfo:
    info = run.initial_state.run
    if info is None:  # pragma: no cover - runs always carry RunInfo
        raise HTTPException(status_code=500, detail="run projection incomplete")
    return info.model_copy(update={"status": run.status})


def _durable_projection(info: RunInfo) -> PublicAgentState:
    """Build the whole projection a reconnect gets when the run is only durable.

    There is no in-memory event log, so the message and activity lists are
    empty; the run's lifecycle is what carries over.
    """
    terminal = is_terminal(info.status)
    return PublicAgentState(
        project_id=info.project_id,
        thread_id=info.thread_id,
        run=info,
        revision=info.last_public_revision,
        messages=[],
        activities=[],
        context_version=info.based_on_context_version,
        save_status="saved" if terminal else "unsaved",
    )


def create_transport_router() -> APIRouter:
    """Build the `/rpc/agent` router; resources come from the app lifespan."""
    router = APIRouter(prefix="/rpc/agent", tags=["agent-rpc"])

    @router.post("/chat")
    async def chat(request: Request, body: ChatRequest) -> Response:
        """Start (or re-attach to) one run and stream its public projection."""
        registry = _resources(request)
        existing = registry.get_by_request(body.client_request_id)
        if existing is not None:
            # Retrying with the same client_request_id must not start a second run.
            return stream_run(existing)

        scope = None
        if registry.durable is not None:
            scope = await registry.durable.resolve_scope(
                project_id=UUID(str(body.project_id)),
                thread_id=UUID(str(body.thread_id)),
            )
            if scope is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="unknown project or thread",
                )

        command = body.commands[0]
        now = datetime.now(UTC)
        run_id = RunId(uuid4())
        run = Run(
            id=run_id,
            client_request_id=body.client_request_id,
            initial_state=initial_state(
                project_id=body.project_id,
                thread_id=body.thread_id,
                run_id=run_id,
                started_at=now,
                user_message=PublicMessage(
                    id=command.message.id,
                    role="user",
                    blocks=[TextBlock(text=command.message.text)],
                    status="complete",
                    created_at=now,
                ),
            ),
            prompt=command.message.text,
        )
        try:
            await registry.start(run, scope=scope)
        except ActiveRunExists as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="this thread already has an active run",
            ) from error
        return stream_run(run)

    @router.post("/runs/{run_id}/subscribe")
    async def subscribe(request: Request, run_id: RunId) -> Response:
        """Re-attach to a run without re-running it.

        A run this process still holds is replayed from its event log. A run
        only known durably — after a restart — is returned as one projection
        frame carrying its lifecycle.
        """
        registry = _resources(request)
        run = registry.get(run_id)
        if run is not None:
            return stream_run(run)
        if registry.durable is not None:
            info = await registry.durable.lookup(run_id)
            if info is not None:
                return stream_projection(_durable_projection(info))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown run")

    @router.post("/runs/{run_id}/cancel", response_model=RunSnapshot)
    async def cancel(request: Request, run_id: RunId) -> Annotated[RunSnapshot, "Idempotent"]:
        """Stop the run; repeated calls return the same terminal state."""
        registry = _resources(request)
        run = await registry.cancel(run_id)
        if run is not None:
            return RunSnapshot(run=_run_info(run), revision=len(run.events))
        if registry.durable is not None:
            info = await registry.durable.lookup(run_id)
            if info is not None:
                return RunSnapshot(run=info, revision=info.last_public_revision)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown run")

    @router.get("/runs/{run_id}", response_model=RunSnapshot)
    async def get_run(request: Request, run_id: RunId) -> Annotated[RunSnapshot, "Lifecycle"]:
        """Report run lifecycle without opening a stream."""
        registry = _resources(request)
        run = registry.get(run_id)
        if run is not None:
            return RunSnapshot(run=_run_info(run), revision=len(run.events))
        if registry.durable is not None:
            info = await registry.durable.lookup(run_id)
            if info is not None:
                return RunSnapshot(run=info, revision=info.last_public_revision)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown run")

    return router
