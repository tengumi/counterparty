"""One-shot "на что обратить внимание" block for the report screen.

A general read of the counterparty — not tied to any deal. The screen does not
know what the user is trying to do (prepayment, deferral, one-off), so the
block never mentions one: it summarises the company itself.

Not a conversation turn: no graph, no checkpoint, no tool loop. It reads a few
report sections straight from the MCP tools and asks the model once, with the
response schema passed as structured output — no JSON-shaped prompt, no hand
parsing.
"""

import asyncio
import logging
from collections.abc import Awaitable, Coroutine, Sequence
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .config import AgentSettings
from .harness.models import create_chat_model
from .harness.tools import reports_toolset

logger = logging.getLogger(__name__)

_SECTIONS = ("financials", "execution_proceedings", "risk_signals")
_PART_CHARS = 3500
"""Each report part is trimmed before it reaches the model. The raw MCP dumps
run tens of thousands of characters of JSON; the block needs the shape of the
numbers, not every field, and a big prefill is what makes the call slow."""

_SYSTEM = (
    "Ты — помощник по проверке контрагентов в Альфа-Бизнесе. Перед тобой отчёт о "
    "компании. Составь общий блок «на что обратить внимание» по этому "
    "контрагенту: 3–4 пункта — самое важное из отчёта о самой компании.\n"
    "Это общая справка, не под конкретную сделку. НЕ упоминай аванс, предоплату, "
    "отсрочку, сроки поставки, сумму договора и «вашу сделку» — ты не знаешь, "
    "зачем пользователь смотрит компанию.\n"
    "Что осветить: масштаб и возраст компании и чем занимается; финансовое "
    "состояние (выручка и её динамика, собственный капитал, прибыль, долги перед "
    "поставщиками и перед компанией); исполнительные производства, суды, "
    "налоговые сигналы — есть или нет и насколько существенно; чего в данных не "
    "хватает.\n"
    "Каждый пункт: 1–2 предложения, живой русский язык без англицизмов и без "
    "Markdown, с конкретными числами из отчёта и коротким пояснением, что это "
    "значит. Не выдумывай и не оценивай то, чего в данных нет. Сначала самое "
    "существенное."
)


class SummaryBullet(BaseModel):
    """One line of the orientation block."""

    tone: Literal["risk", "ok", "neutral"] = Field(
        description="risk — настораживает; ok — в пользу компании; "
        "neutral — важный нейтральный факт или пробел в данных"
    )
    text: str = Field(
        min_length=1,
        description="1–2 предложения простым языком, с конкретными числами и коротким пояснением; "
        "без упоминания аванса, отсрочки, сроков и суммы сделки",
    )


class ReportSummary(BaseModel):
    """The orientation block shown above the raw report sections."""

    bullets: list[SummaryBullet] = Field(
        description="3–4 пункта о самой компании, самый важный первым", min_length=1, max_length=4
    )


def _tool(tools: Sequence[BaseTool], name: str) -> BaseTool | None:
    return next((tool for tool in tools if tool.name == name), None)


def _clip(value: object) -> str:
    text = str(value)
    return text if len(text) <= _PART_CHARS else text[:_PART_CHARS] + " …(обрезано)"


async def _gather(settings: AgentSettings, report_id: str) -> str:
    """Pull a few report parts into one trimmed plain-text block for the model.

    Parts are fetched together and each is clipped: the raw MCP dumps are tens
    of thousands of characters, and a big prefill is what made the call slow.
    """

    async def part(name: str, coro: Awaitable[Any]) -> str:
        try:
            return f"== {name} ==\n{_clip(await coro)}"
        except Exception as error:
            logger.info("summary: part %s unavailable: %s", name, error)
            return ""

    async with reports_toolset(settings) as tools:
        overview = _tool(tools, "get_company_overview")
        section = _tool(tools, "get_report_section")
        jobs: list[Coroutine[Any, Any, str]] = []
        if overview is not None:
            jobs.append(part("Карточка", overview.ainvoke({"report_id": report_id})))
        if section is not None:
            jobs.extend(
                part(name, section.ainvoke({"report_id": report_id, "section": name}))
                for name in _SECTIONS
            )
        parts = await asyncio.gather(*jobs)
    return "\n\n".join(p for p in parts if p)


async def build_report_summary(settings: AgentSettings, *, report_id: str) -> ReportSummary:
    """Read the report, ask the model once with a response schema, return the block.

    Raises:
        ValueError: if the report has no data or the model call fails.
    """
    context = await _gather(settings, report_id)
    if not context:
        raise ValueError("no report data to summarise")
    model = create_chat_model(settings)
    question = f"Данные отчёта:\n{context}"
    try:
        structured = model.with_structured_output(ReportSummary)
        result = await structured.ainvoke(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=question)]
        )
    except Exception as error:
        raise ValueError(f"summary model call failed: {error}") from error
    if not isinstance(result, ReportSummary):
        result = ReportSummary.model_validate(result)
    return result
