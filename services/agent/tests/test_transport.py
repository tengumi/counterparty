"""V01 transport checks: text, typed activity, terminal error and cancel."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
import uvicorn
from counterparty_contracts import ClientRequestId, ProjectId, RunStatus, ThreadId
from fastapi.testclient import TestClient
from httpx import AsyncClient

from counterparty_agent.app import create_app
from counterparty_agent.config import AgentSettings

PROJECT_ID = ProjectId(uuid4())
THREAD_ID = ThreadId(uuid4())


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A running app without any external dependency."""
    with TestClient(create_app(AgentSettings(postgres_dsn=None))) as running:
        yield running


def chat_body(text: str, *, request_id: ClientRequestId | None = None) -> dict[str, Any]:
    """Build the domain request the web adapter produces."""
    return {
        "project_id": str(PROJECT_ID),
        "thread_id": str(THREAD_ID),
        "client_request_id": str(request_id or ClientRequestId(uuid4())),
        "stream": True,
        "commands": [
            {
                "type": "add-message",
                "message": {
                    "id": "client-msg-1",
                    "text": text,
                    "document_ids": [],
                    "evidence_refs": [],
                    "company_ids": [],
                },
            }
        ],
    }


def decode(sse: str) -> list[dict[str, Any]]:
    """Decode the SSE body the library encoder produced."""
    frames: list[dict[str, Any]] = []
    for line in sse.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line.removeprefix("data: ")
        if payload == "[DONE]":
            frames.append({"type": "[DONE]"})
            continue
        frames.append(json.loads(payload))
    return frames


def materialize(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply update-state operations the way the browser accumulator does."""
    state: Any = None
    for frame in frames:
        if frame.get("type") != "update-state":
            continue
        for op in frame["operations"]:
            state = _apply(state, op["path"], op)
    assert isinstance(state, dict)
    return state


def _apply(target: Any, path: list[str], op: dict[str, Any]) -> Any:
    if not path:
        if op["type"] == "set":
            return op["value"]
        return (target or "") + op["value"]
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


def stream(client: TestClient, text: str, **kwargs: Any) -> str:
    """Post one chat request and read the whole response body."""
    response = client.post("/rpc/agent/chat", json=chat_body(text, **kwargs))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return response.text


def test_text_reaches_the_client_as_append_text_deltas(client: TestClient) -> None:
    """V01 case 1: streamed text arrives as append-text, not as one blob."""
    frames = decode(stream(client, "Можно ли перечислять 80% аванса?"))
    text_path = ["messages", "1", "blocks", "0", "text"]
    deltas = [
        op["value"]
        for frame in frames
        if frame.get("type") == "update-state"
        for op in frame["operations"]
        if op["type"] == "append-text" and op["path"] == text_path
    ]

    assert len(deltas) > 1
    state = materialize(frames)
    assert state["messages"][1]["blocks"][0]["text"] == "".join(deltas)
    assert state["messages"][1]["status"] == "complete"
    assert state["messages"][0]["role"] == "user"
    assert frames[-1] == {"type": "[DONE]"}


def test_typed_activity_reaches_the_client(client: TestClient) -> None:
    """V01 case 2: a typed activity is published with a safe label."""
    state = materialize(decode(stream(client, "Проверь условия")))
    activity = state["activities"][0]

    assert activity["kind"] == "reading_document"
    assert activity["label"] == "Читаю условия поставки"
    assert activity["status"] == "completed"
    assert activity["finished_at"] is not None
    assert state["run"]["status"] == RunStatus.COMPLETED.value
    assert state["save_status"] == "saved"


def test_terminal_error_uses_the_library_error_frame(client: TestClient) -> None:
    """V01 case 3: failure ends in an `error` chunk plus a failed projection."""
    frames = decode(stream(client, "/fail проверь отчёт"))
    errors = [frame for frame in frames if frame.get("type") == "error"]
    state = materialize(frames)

    assert [frame["error"] for frame in errors] == [
        "Источник сведений недоступен. Попробуйте позже."
    ]
    assert state["run"]["status"] == RunStatus.FAILED.value
    assert state["run"]["error"]["code"] == "dependency_unavailable"
    assert state["messages"][1]["status"] == "error"
    assert frames[-1] == {"type": "[DONE]"}


@asynccontextmanager
async def live_agent() -> AsyncIterator[str]:
    """Serve the app over a real socket.

    `httpx.ASGITransport` and `TestClient` both buffer the whole response, so
    neither can send `cancel` while a stream is still open.
    """
    config = uvicorn.Config(
        create_app(AgentSettings(postgres_dsn=None)),
        host="127.0.0.1",
        port=0,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.mark.asyncio
async def test_explicit_cancel_stops_the_run_and_keeps_partial_state() -> None:
    """V01 case 4: cancel is a separate command; partial output stays visible."""
    async with live_agent() as base_url, AsyncClient(base_url=base_url, timeout=10.0) as http:
        collected: list[str] = []
        run_id: str | None = None
        requested = False
        async with http.stream("POST", "/rpc/agent/chat", json=chat_body("/slow")) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                collected.append(line)
                if run_id is None:
                    run_id = _run_id_from(line)
                elif not requested:
                    requested = True
                    cancelled = await http.post(f"/rpc/agent/runs/{run_id}/cancel")
                    assert cancelled.status_code == 200
        assert requested

        frames = decode("\n".join(collected))
        state = materialize(frames)

        assert state["run"]["status"] == RunStatus.CANCELLED.value
        assert state["messages"][1]["status"] == "partial"
        assert state["messages"][1]["blocks"][0]["text"] != ""
        assert frames[-1] == {"type": "[DONE]"}

        again = await http.post(f"/rpc/agent/runs/{run_id}/cancel")
        assert again.status_code == 200
        assert again.json()["run"]["status"] == RunStatus.CANCELLED.value


def _run_id_from(line: str) -> str | None:
    """Read the run id out of the first root `set` operation."""
    if not line.startswith("data: ") or '"update-state"' not in line:
        return None
    frame = json.loads(line.removeprefix("data: "))
    for op in frame["operations"]:
        if op["path"] == [] and isinstance(op["value"], dict):
            run_id: str = op["value"]["run"]["id"]
            return run_id
    return None


def test_retry_with_the_same_request_id_does_not_start_a_second_run(client: TestClient) -> None:
    """Specs 10 §6: a repeated client_request_id re-attaches instead of re-running."""
    request_id = ClientRequestId(uuid4())
    first = materialize(decode(stream(client, "Проверь условия", request_id=request_id)))
    second = materialize(decode(stream(client, "Проверь условия", request_id=request_id)))

    assert first["run"]["id"] == second["run"]["id"]
    assert first["messages"] == second["messages"]


def test_subscribe_replays_a_finished_run_without_rerunning_it(client: TestClient) -> None:
    """Specs 04 §7: re-attaching restores the projection, it does not re-send."""
    frames = decode(stream(client, "Проверь условия"))
    run_id = materialize(frames)["run"]["id"]

    replayed = client.post(f"/rpc/agent/runs/{run_id}/subscribe")

    assert replayed.status_code == 200
    assert materialize(decode(replayed.text)) == materialize(frames)


def test_unknown_run_is_reported_as_not_found(client: TestClient) -> None:
    """Lifecycle endpoints do not invent runs."""
    assert client.get(f"/rpc/agent/runs/{uuid4()}").status_code == 404
    assert client.post(f"/rpc/agent/runs/{uuid4()}/cancel").status_code == 404
