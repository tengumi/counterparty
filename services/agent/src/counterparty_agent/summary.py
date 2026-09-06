"""One-shot "на что обратить внимание" block for the report screen.

This is not a conversation turn: no graph, no checkpoint, no tool loop. It
reads a few report sections straight from the MCP tools, hands them to the
model once with the user's task, and parses a small JSON structure the report
screen renders above the raw sections.

Kept deliberately small — the value is a plain-language orientation for the
task at hand, not a second analysis engine.
"""

import json
import logging
from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, ValidationError

from .config import AgentSettings
from .harness.models import create_chat_model
from .harness.tools import reports_toolset

logger = logging.getLogger(__name__)

_SECTIONS = ("financials", "execution_proceedings", "arbitration", "risk_signals")

_SYSTEM = (
    "Ты — помощник по проверке контрагентов в Альфа-Бизнесе. По данным отчёта и "
    "задаче пользователя составь короткий блок «на что обратить внимание»: 3–4 "
    "пункта, каждый — 1–2 предложения простым языком, без англицизмов и без "
    "Markdown. В каждом пункте, где есть число, называй его. Не выдумывай: "
    "опирайся только на приведённые данные.\n"
    'tone у пункта: "risk" — то, что настораживает для этой задачи; "ok" — '
    'то, что в пользу компании; "neutral" — нейтральный факт или пробел в '
    "данных (пробел — это «неизвестно», а не «всё чисто»).\n"
    "caveat — одна фраза о том, что это объяснение под задачу пользователя, а не "
    "оценка банка, и что дальше идут факты как есть.\n"
    'Верни СТРОГО JSON без пояснений: {"bullets":[{"tone":"risk|ok|neutral",'
    '"text":"..."}],"caveat":"..."}'
)


class SummaryBullet(BaseModel):
    """One line of the orientation block."""

    tone: Literal["risk", "ok", "neutral"] = "neutral"
    text: str = Field(min_length=1)


class ReportSummary(BaseModel):
    """The orientation block shown above the raw report sections."""

    bullets: list[SummaryBullet] = Field(default_factory=list)
    caveat: str = ""


def _tool(tools: Sequence[BaseTool], name: str) -> BaseTool | None:
    return next((tool for tool in tools if tool.name == name), None)


async def _gather(settings: AgentSettings, report_id: str) -> str:
    """Pull a few sections of the report into one plain-text block for the model."""
    parts: list[str] = []
    async with reports_toolset(settings) as tools:
        overview = _tool(tools, "get_company_overview")
        section = _tool(tools, "get_report_section")
        if overview is not None:
            parts.append("== Карточка ==\n" + str(await overview.ainvoke({"report_id": report_id})))
        if section is not None:
            for name in _SECTIONS:
                try:
                    result = await section.ainvoke({"report_id": report_id, "section": name})
                except Exception as error:
                    logger.info("summary: section %s unavailable: %s", name, error)
                    continue
                parts.append(f"== {name} ==\n{result}")
    return "\n\n".join(parts)


def _parse(raw: str) -> ReportSummary:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text.strip("`")
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    data = json.loads(text)
    summary = ReportSummary.model_validate(data)
    summary.bullets = summary.bullets[:4]
    return summary


async def build_report_summary(
    settings: AgentSettings, *, report_id: str, task: str
) -> ReportSummary:
    """Read the report, ask the model once, return the orientation block.

    Raises:
        ValueError: if the model does not return parseable JSON.
    """
    context = await _gather(settings, report_id)
    if not context:
        raise ValueError("no report data to summarise")
    model = create_chat_model(settings)
    question = (
        f"Задача пользователя: {task or 'оценка контрагента для сделки'}\n\n"
        f"Данные отчёта:\n{context}"
    )
    response = await model.ainvoke([SystemMessage(content=_SYSTEM), HumanMessage(content=question)])
    try:
        return _parse(str(response.text))
    except (json.JSONDecodeError, ValidationError, ValueError) as error:
        raise ValueError(f"model did not return a usable summary: {error}") from error
