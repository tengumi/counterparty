"""A LangChain chat model that plans without a model API (AG-01).

The provider and model id are configuration. This adapter is the default value
of that configuration so the service builds, starts and is testable with no key
and no network: it is a real ``BaseChatModel`` bound through the ordinary
``bind_tools`` path, so the Deep Agents harness runs its own loop over it
exactly as it would over a hosted model. Nothing here is a second agent loop --
it only decides what the "model" says next.

Its policy is fixed and small:

1. identify the company through ``get_company_overview`` (INN taken from the
   question or from the project layer of the system prompt);
2. read one section through ``get_report_section`` using the ``report_id``
   the overview pinned;
3. answer with one cited line per available fact, and name the sections the
   snapshot did not carry instead of reporting them as zero.

When no INN is available it asks for one instead of guessing, which is also
what the acceptance scenario expects of a real model.
"""

import json
import re
from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field

from .prompts import (
    ANSWER_HEADING,
    ASK_FOR_INN,
    MISSING_SECTION_LINE,
    UNKNOWN_HEADING,
)

OVERVIEW_TOOL = "get_company_overview"
SECTION_TOOL = "get_report_section"
DEFAULT_SECTION = "financials"

_INN = re.compile(r"(?<![\dA-Fa-f-])(\d{10}|\d{12})(?![\dA-Fa-f-])")
"""An INN, never a digit run inside a UUID: hex and dash neighbours disqualify."""


class DeterministicChatModel(BaseChatModel):
    """Scripted tool-calling model used as the default provider adapter."""

    model_id: str = "counterparty-deterministic-v1"
    bound_tools: tuple[str, ...] = ()
    section: str = DEFAULT_SECTION
    seen_prompts: list[list[BaseMessage]] = Field(default_factory=list)
    """Every message list this adapter was asked to continue, for assertions."""

    @property
    def _llm_type(self) -> str:
        return "counterparty-deterministic"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any],
        **kwargs: Any,
    ) -> "DeterministicChatModel":
        """Bind tool names the ordinary LangChain way, without a schema call."""
        names = tuple(_tool_name(tool) for tool in tools)
        return self.model_copy(update={"bound_tools": names})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen_prompts.append(list(messages))
        message = self._decide(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _decide(self, messages: list[BaseMessage]) -> AIMessage:
        results = _tool_results(messages)
        if OVERVIEW_TOOL in self.bound_tools and OVERVIEW_TOOL not in results:
            inn = _find_inn(messages)
            if inn is None:
                return AIMessage(content=ASK_FOR_INN)
            return _call(OVERVIEW_TOOL, {"inn": inn}, "call-overview")
        report_id = _report_id(results.get(OVERVIEW_TOOL))
        if (
            SECTION_TOOL in self.bound_tools
            and SECTION_TOOL not in results
            and report_id is not None
        ):
            return _call(
                SECTION_TOOL,
                {"report_id": report_id, "section": self.section},
                "call-section",
            )
        return AIMessage(content=_compose_answer(list(results.values())))


def _tool_name(tool: object) -> str:
    if isinstance(tool, BaseTool):
        return tool.name
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return str(function["name"])
        return str(tool.get("name", ""))
    return str(getattr(tool, "name", getattr(tool, "__name__", "")))


def _call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def _tool_results(messages: Sequence[BaseMessage]) -> dict[str, Any]:
    names: dict[str, str] = {}
    results: dict[str, Any] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                call_id = call.get("id")
                if isinstance(call_id, str):
                    names[call_id] = call["name"]
        elif isinstance(message, ToolMessage):
            name = message.name or names.get(str(message.tool_call_id), "")
            if name:
                results[name] = _payload(message)
    return results


def _payload(message: ToolMessage) -> Any:
    """Decode a tool result to its structured envelope.

    The LangChain MCP adapter delivers a tool result as a list of content
    blocks (``[{"type": "text", "text": "<json>"}]``); a plain adapter delivers
    the JSON string directly. Both are reduced to the parsed envelope here so
    the policy above reads ``data``/``report`` the same way in tests and
    against the live MCP.
    """
    content = message.content
    if isinstance(content, list):
        content = "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError:
            return {}
    return content


def _find_inn(messages: Sequence[BaseMessage]) -> str | None:
    # Only the user names the counterparty. The system prompt now carries the
    # signed-in client's own INN, which is not what is being checked.
    for message in reversed(messages):
        if isinstance(message, SystemMessage):
            continue
        text = message.text if isinstance(message.text, str) else str(message.content)
        match = _INN.search(text)
        if match is not None:
            return match.group(1)
    return None


def _report_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        report = data.get("report")
        if isinstance(report, dict) and isinstance(report.get("id"), str):
            return str(report["id"])
    ids = payload.get("source_report_ids")
    if isinstance(ids, list) and ids and isinstance(ids[0], str):
        return str(ids[0])
    return None


def _compose_answer(payloads: Sequence[Any]) -> str:
    facts: list[str] = []
    gaps: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        facts.extend(_fact_lines(data.get("facts")))
        gaps.extend(_gap_lines(data.get("available_sections")))
    lines = [ANSWER_HEADING, *facts] if facts else []
    if gaps:
        lines.extend(["", UNKNOWN_HEADING, *dict.fromkeys(gaps)])
    return "\n".join(lines)


def _fact_lines(facts: object) -> list[str]:
    lines: list[str] = []
    if not isinstance(facts, list):
        return lines
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("availability") != "available":
            continue
        refs = [ref for ref in fact.get("evidence_refs", []) if isinstance(ref, str)]
        if not refs:
            continue
        value = fact.get("value")
        unit = fact.get("unit") or fact.get("currency") or ""
        citation = " ".join(f"[evidence:{ref}]" for ref in refs)
        lines.append(f"- {fact.get('label', fact.get('key'))}: {value} {unit}".rstrip())
        lines[-1] = f"{lines[-1]} {citation}"
    return lines


def _gap_lines(sections: object) -> list[str]:
    lines: list[str] = []
    if not isinstance(sections, list):
        return lines
    for entry in sections:
        if not isinstance(entry, dict):
            continue
        availability: Literal["available"] | str = str(entry.get("availability", ""))
        if availability in {"available", ""}:
            continue
        lines.append(MISSING_SECTION_LINE.format(section=entry.get("section"), state=availability))
    return lines
