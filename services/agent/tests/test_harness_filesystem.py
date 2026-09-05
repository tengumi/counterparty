"""The file tools stay inside one project/thread workspace (Specs 04 §4).

Enforcement is on our side of the boundary, so it is asserted through the real
graph: a scripted model asks for paths outside the workspace and for a shell,
and the framework's own permission rules refuse them.
"""

from typing import Any
from uuid import UUID

from harness_fixtures import ScriptedChatModel, report_tools
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from counterparty_agent.harness import (
    RunEvidenceLedger,
    build_context,
    create_harness,
    thread_workspace_root,
)
from counterparty_agent.harness.filesystem import DENIED_PATH_EXAMPLES, scoped_permissions

PROJECT = UUID("33333333-3333-4333-8333-333333333333")
THREAD = UUID("44444444-4444-4444-8444-444444444444")
OTHER_THREAD = UUID("55555555-5555-4555-8555-555555555555")
ROOT = thread_workspace_root(PROJECT, THREAD)


def _call(name: str, args: dict[str, Any], index: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"c{index}", "type": "tool_call"}],
    )


async def _run(script: list[AIMessage]) -> list[ToolMessage]:
    """Run one scripted session and return the tool results it produced."""
    model = ScriptedChatModel(script=[*script, AIMessage(content="Done?")])
    graph = create_harness(
        model=model,
        tools=report_tools(),
        context=build_context(
            project_id=PROJECT,
            tenant_id=UUID(int=2),
            title="Supply check",
            workflow_status="in_progress",
            context_version=1,
            companies=[],
            thread_id=THREAD,
            thread_title="Delivery terms",
            thread_status="active",
        ),
        ledger=RunEvidenceLedger(),
        checkpointer=InMemorySaver(),
    )
    state = await graph.ainvoke(
        {"messages": [("user", "Write the note.")]},
        RunnableConfig(configurable={"thread_id": str(THREAD)}, recursion_limit=16),
    )
    return [message for message in state["messages"] if isinstance(message, ToolMessage)]


def test_the_allow_rule_precedes_the_catch_all_deny() -> None:
    """The allow rule precedes the catch all deny."""
    rules = scoped_permissions(PROJECT, THREAD)
    assert rules[0].mode == "allow"
    assert rules[0].paths == [ROOT, f"{ROOT}/**"]
    assert rules[-1] == rules[-1].__class__(
        operations=["read", "write"], paths=["/**"], mode="deny"
    )


async def test_a_file_inside_the_thread_workspace_is_written() -> None:
    """A file inside the thread workspace is written."""
    results = await _run(
        [_call("write_file", {"file_path": f"{ROOT}/notes.md", "content": "x"}, 1)]
    )
    assert "denied" not in results[0].text.lower()


async def test_writing_outside_the_workspace_is_denied() -> None:
    """Writing outside the workspace is denied."""
    results = await _run(
        [_call("write_file", {"file_path": "/notes-escape.md", "content": "x"}, 1)]
    )
    assert "denied" in results[0].text.lower()


async def test_another_thread_workspace_is_not_reachable() -> None:
    """Another thread workspace is not reachable."""
    other = thread_workspace_root(PROJECT, OTHER_THREAD)
    results = await _run([_call("read_file", {"file_path": f"{other}/notes.md"}, 1)])
    assert "denied" in results[0].text.lower()


async def test_the_os_root_and_the_environment_are_not_reachable() -> None:
    """The os root and the environment are not reachable."""
    script = [
        _call("read_file", {"file_path": path}, i) for i, path in enumerate(DENIED_PATH_EXAMPLES)
    ]
    results = await _run(script)
    assert results
    assert all("denied" in result.text.lower() for result in results)


async def test_escaping_the_workspace_with_a_relative_path_is_denied() -> None:
    """Escaping the workspace with a relative path is denied."""
    results = await _run([_call("read_file", {"file_path": f"{ROOT}/../../secret.md"}, 1)])
    assert "denied" in results[0].text.lower() or "error" in results[0].text.lower()


async def test_no_shell_is_available_to_the_agent() -> None:
    """No shell is available to the agent."""
    results = await _run([_call("execute", {"command": "cat /etc/passwd"}, 1)])
    assert "root:" not in results[0].text
    assert "not available" in results[0].text.lower()
