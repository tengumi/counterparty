"""Сборка явного LangGraph и переходов между узлами."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from counterparty_agent.workflow.comparison import (
    _analyze_comparison,
    _answer_comparison_question,
    _compose_comparison,
    _load_comparison,
    _validate_comparison,
    _validate_comparison_answer,
)
from counterparty_agent.workflow.contracts import WorkflowContext, WorkflowState
from counterparty_agent.workflow.review_session import review_session
from counterparty_agent.workflow.routing import _parse_request, _restore_session
from counterparty_agent.workflow.selection import (
    _resolve_addition,
    _resolve_comparison,
    _resolve_entities,
)
from counterparty_agent.workflow.semantic import (
    _apply_intent,
    _finish_routing,
    _retain_context,
    _route_intent,
)
from counterparty_agent.workflow.single import (
    _analyze,
    _answer_question,
    _compose,
    _load_snapshot,
    _validate,
    _validate_answer,
)


def _request_route(state: WorkflowState) -> str:
    return (
        state["status"]
        if state["status"]
        in {"resolve", "load", "resolve_comparison", "load_comparison", "resolve_addition"}
        else "compose"
    )


def _comparison_resolution_route(state: WorkflowState) -> str:
    return "load_comparison" if state["status"] == "load_comparison" else "compose"


def _comparison_load_route(state: WorkflowState) -> str:
    return "analyze_comparison" if state["status"] == "analyze_comparison" else "compose"


def _resolution_route(state: WorkflowState) -> str:
    return state["status"] if state["status"] in {"load", "load_comparison"} else "compose"


def _load_route(state: WorkflowState) -> str:
    return "analyze" if state["status"] == "analyze" else "compose"


def _validated_route(state: WorkflowState) -> str:
    return "answer_question" if state["status"] == "answer_question" else "compose"


def _answer_route(state: WorkflowState) -> str:
    return (
        state["status"]
        if state["status"] in {"validate_answer", "compose_comparison"}
        else "compose"
    )


def _comparison_validated_route(state: WorkflowState) -> str:
    return state["status"]


def _answer_composed_route(state: WorkflowState) -> str:
    return "compose_comparison" if state["status"] == "compose_comparison" else "compose"


def build_graph(
    checkpointer: BaseCheckpointSaver[Any],
) -> CompiledStateGraph[WorkflowState, WorkflowContext, WorkflowState, WorkflowState]:
    """Собрать граф; вызывающий API передаёт только пустой input и доверенный thread_id."""

    graph = StateGraph(WorkflowState, context_schema=WorkflowContext)
    graph.add_node("restore_session", _restore_session)
    graph.add_node("route_intent", _route_intent)
    graph.add_node("apply_intent", _apply_intent)
    graph.add_node("finish_routing", _finish_routing)
    graph.add_node("review_session", review_session)
    graph.add_node("retain_context", _retain_context)
    graph.add_node("parse_request", _parse_request)
    graph.add_node("resolve_entities", _resolve_entities)
    graph.add_node("resolve_comparison", _resolve_comparison)
    graph.add_node("resolve_addition", _resolve_addition)
    graph.add_node("load_comparison", _load_comparison)
    graph.add_node("analyze_comparison", _analyze_comparison)
    graph.add_node("validate_comparison", _validate_comparison)
    graph.add_node("compose_comparison", _compose_comparison)
    graph.add_node("answer_comparison_question", _answer_comparison_question)
    graph.add_node("validate_comparison_answer", _validate_comparison_answer)
    graph.add_node("answer_focused_question", _answer_question)
    graph.add_node("load_snapshot", _load_snapshot)
    graph.add_node("analyze", _analyze)
    graph.add_node("validate", _validate)
    graph.add_node("answer_question", _answer_question)
    graph.add_node("validate_answer", _validate_answer)
    graph.add_node("compose", _compose)
    graph.add_edge(START, "restore_session")
    graph.add_edge("restore_session", "route_intent")
    graph.add_conditional_edges(
        "route_intent",
        lambda state: (
            state["status"] if state["status"] in {"parse_request", "apply_intent"} else "compose"
        ),
        {
            "parse_request": "parse_request",
            "apply_intent": "apply_intent",
            "compose": "retain_context",
        },
    )
    graph.add_conditional_edges(
        "apply_intent",
        _request_route,
        {
            "resolve": "resolve_entities",
            "load": "load_snapshot",
            "compose": "retain_context",
            "resolve_comparison": "resolve_comparison",
            "load_comparison": "load_comparison",
            "resolve_addition": "resolve_addition",
        },
    )
    graph.add_conditional_edges(
        "retain_context",
        _request_route,
        {"load": "load_snapshot", "load_comparison": "load_comparison", "compose": "compose"},
    )
    graph.add_conditional_edges(
        "parse_request",
        _request_route,
        {
            "resolve": "resolve_entities",
            "load": "load_snapshot",
            "compose": "compose",
            "resolve_comparison": "resolve_comparison",
            "load_comparison": "load_comparison",
            "resolve_addition": "resolve_addition",
        },
    )
    graph.add_conditional_edges(
        "resolve_entities",
        _resolution_route,
        {"load": "load_snapshot", "load_comparison": "load_comparison", "compose": "compose"},
    )
    graph.add_conditional_edges(
        "load_snapshot", _load_route, {"analyze": "analyze", "compose": "compose"}
    )
    graph.add_conditional_edges(
        "resolve_comparison",
        _comparison_resolution_route,
        {"load_comparison": "load_comparison", "compose": "compose"},
    )
    graph.add_conditional_edges(
        "resolve_addition",
        _comparison_resolution_route,
        {"load_comparison": "load_comparison", "compose": "compose"},
    )
    graph.add_conditional_edges(
        "load_comparison",
        _comparison_load_route,
        {"analyze_comparison": "analyze_comparison", "compose": "compose"},
    )
    graph.add_edge("analyze_comparison", "validate_comparison")
    graph.add_conditional_edges(
        "validate_comparison",
        _comparison_validated_route,
        {
            "compose_comparison": "compose_comparison",
            "answer_comparison_question": "answer_comparison_question",
            "answer_focused_question": "answer_focused_question",
        },
    )
    graph.add_conditional_edges(
        "answer_comparison_question",
        _comparison_validated_route,
        {
            "compose_comparison": "compose_comparison",
            "validate_comparison_answer": "validate_comparison_answer",
        },
    )
    graph.add_edge("validate_comparison_answer", "compose_comparison")
    graph.add_conditional_edges(
        "answer_focused_question",
        _answer_route,
        {
            "validate_answer": "validate_answer",
            "compose_comparison": "compose_comparison",
            "compose": "compose",
        },
    )
    graph.add_edge("compose_comparison", "finish_routing")
    graph.add_edge("analyze", "validate")
    graph.add_conditional_edges(
        "validate", _validated_route, {"answer_question": "answer_question", "compose": "compose"}
    )
    graph.add_conditional_edges(
        "answer_question",
        _answer_route,
        {
            "validate_answer": "validate_answer",
            "compose": "compose",
            "compose_comparison": "compose_comparison",
        },
    )
    graph.add_conditional_edges(
        "validate_answer",
        _answer_composed_route,
        {"compose_comparison": "compose_comparison", "compose": "compose"},
    )
    graph.add_edge("compose", "finish_routing")
    graph.add_edge("finish_routing", "review_session")
    graph.add_edge("review_session", END)
    return graph.compile(checkpointer=checkpointer, debug=False)
