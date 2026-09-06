"""Fold a run's event log into its final public projection.

The transport keeps the replayable event log in memory and streams it to
subscribers (:mod:`.delivery`). When a run reaches a terminal state the same
log is also folded, once, into a settled :class:`PublicAgentState` so the agent
can persist it: a client that opens the chat after the run finished then reads
its real ``messages`` and ``activities`` instead of an empty history.

This is the non-streaming twin of ``delivery._deliver``: it applies the same
three state operations, but to a plain JSON structure rather than to a live
``RunController`` proxy. A :class:`TerminalError` carries no projection state
and is skipped here; the terminal run status is already in the log as a
``set`` on ``("run", "status")``.
"""

from collections.abc import Sequence
from typing import Any

from .public_state import PublicAgentState
from .runs import (
    AppendItemOperation,
    AppendTextOperation,
    RunEvent,
    SetOperation,
    StatePath,
    TerminalError,
)


def fold_projection(
    initial_state: PublicAgentState, events: Sequence[RunEvent]
) -> PublicAgentState:
    """Return the projection that results from applying ``events`` in order."""
    root: Any = initial_state.model_dump(mode="json")
    for event in events:
        match event:
            case SetOperation(path=path, value=value):
                root = _set(root, path, value)
            case AppendItemOperation(path=path, value=value):
                _navigate(root, path).append(value)
            case AppendTextOperation(path=path, text=text):
                parent = _navigate(root, path[:-1])
                key = _key(parent, path[-1])
                parent[key] = f"{parent[key]}{text}"
            case TerminalError():
                continue
    return PublicAgentState.model_validate(root)


def _navigate(node: Any, path: StatePath) -> Any:
    """Walk ``path`` from ``node``, matching list indices to integers."""
    for step in path:
        node = node[_key(node, step)]
    return node


def _set(root: Any, path: StatePath, value: Any) -> Any:
    """Replace the value at ``path``; an empty path replaces the whole root."""
    if not path:
        return value
    parent = _navigate(root, path[:-1])
    parent[_key(parent, path[-1])] = value
    return root


def _key(container: Any, step: str) -> Any:
    """A list is addressed by an integer index, a mapping by the raw key."""
    return int(step) if isinstance(container, list) else step
