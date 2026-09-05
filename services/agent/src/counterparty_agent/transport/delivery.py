"""Bridge between a managed run and one assistant-stream response.

The delivery callback owns no agent work: it replays the run's log into the
supported `RunController`, so closing the response cancels only the delivery.
"""

from assistant_stream import RunController, create_run
from assistant_stream.serialization import AssistantTransportResponse
from starlette.responses import Response

from .runs import (
    AppendItemOperation,
    AppendTextOperation,
    Run,
    SetOperation,
    StatePath,
    TerminalError,
)


def _navigate(controller: RunController, path: StatePath) -> object:
    node = controller.state
    for key in path:
        node = node[key]
    return node


def _apply_set(controller: RunController, path: StatePath, value: object) -> None:
    if not path:
        controller.state = value
        return
    parent = _navigate(controller, path[:-1])
    parent[path[-1]] = value  # type: ignore[index]


async def _deliver(controller: RunController, run: Run) -> None:
    controller.state = run.initial_state.model_dump(mode="json")
    async for event in run.subscribe():
        match event:
            case SetOperation(path=path, value=value):
                _apply_set(controller, path, value)
            case AppendItemOperation(path=path, value=value):
                target = _navigate(controller, path)
                target.append(value)  # type: ignore[attr-defined]
            case AppendTextOperation(path=path, text=text):
                controller.append_state_text(list(path), text)
            case TerminalError(message=message):
                controller.flush()
                controller.add_error(message)


def stream_run(run: Run) -> Response:
    """Return the library response that streams one run to a subscriber."""

    async def callback(controller: RunController) -> None:
        await _deliver(controller, run)

    response: Response = AssistantTransportResponse(create_run(callback, state={}))
    return response
