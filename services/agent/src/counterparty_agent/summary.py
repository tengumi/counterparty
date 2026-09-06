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
import json
import logging
from collections.abc import Awaitable, Coroutine, Sequence
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, ValidationError

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
    "отсрочку, сроки поставки, сумму договора и «вашу сделку».\n"
    "Что осветить: масштаб и возраст компании и чем занимается; финансовое "
    "состояние (выручка и её динамика, собственный капитал, прибыль, долги перед "
    "поставщиками и перед компанией); исполнительные производства, суды, "
    "налоговые и репутационные сигналы — есть или нет и насколько существенно; "
    "чего в данных не хватает.\n"
    "Формат каждого пункта: одно, максимум два коротких предложения — не абзац. "
    "Живой русский без англицизмов, без Markdown. Пиши смысл, а не технические "
    "имена: «убыток», «отрицательный собственный капитал», «низкий банковский "
    "риск», «зелёный сигнал платформы „Знай своего клиента“», «массовый адрес "
    "или директор», «раздел исполнительных производств». Никаких кодов вроде "
    "profit, execution_proceedings, ЗСК=GREEN, risk=LOW и латинских названий "
    "полей. Приводи конкретные числа из отчёта и коротко — что это значит.\n"
    "tone обязательно расставляй по смыслу, не ставь всё подряд neutral:\n"
    "  risk — плохой для контрагента факт: убыток, отрицательный капитал, "
    "исполнительные производства, суды против компании, высокий банковский риск "
    "или риск ЗСК, массовый адрес/директор, нулевая выручка при активной "
    "деятельности;\n"
    "  ok — благоприятный факт: нет судов и взысканий, низкий риск и зелёный "
    "ЗСК, положительный растущий капитал, устойчивая выручка;\n"
    "  neutral — только по-настоящему нейтральные факты и пробелы в данных.\n"
    "Сначала самое существенное."
)


class SummaryBullet(BaseModel):
    """One line of the orientation block."""

    tone: Literal["risk", "ok", "neutral"] = Field(
        description="risk — плохой для контрагента факт (убыток, отрицательный капитал, "
        "взыскания, суды, высокий риск, массовый адрес/директор); ok — благоприятный "
        "факт (нет судов, низкий риск, растущий капитал); neutral — только нейтральные "
        "факты и пробелы в данных. Не ставь всё neutral."
    )
    text: str = Field(
        min_length=1,
        max_length=320,
        description="одно-два коротких предложения простым языком, с конкретными числами; "
        "без технических имён полей и латинских кодов; без упоминания сделки, аванса, сроков",
    )


class ReportSummary(BaseModel):
    """The orientation block shown above the raw report sections."""

    bullets: list[SummaryBullet] = Field(
        description="3–4 пункта о самой компании, самый важный первым", min_length=1, max_length=4
    )


_SHAPE = (
    'Верни ТОЛЬКО JSON без пояснений: {"bullets":[{"tone":"risk|ok|neutral","text":"..."}]}. '
    "3–4 пункта."
)


def _parse(raw: str) -> ReportSummary:
    """Pull the JSON object out of a plain model reply."""
    text = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start == -1:
        raise ValueError("no JSON in reply")
    end = max(text.rfind("}"), text.rfind("]"))
    payload = json.loads(text[start : end + 1])
    bullets = payload["bullets"] if isinstance(payload, dict) else payload
    return ReportSummary.model_validate({"bullets": bullets[:4]})


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
    model = create_chat_model(settings, model_id=settings.summary_model_id)
    question = f"Данные отчёта:\n{context}\n\n{_SHAPE}"
    # A plain call, parsed by hand: with_structured_output streams the JSON on
    # this provider and the accumulator mangles Cyrillic ("ТЕТРА# ДОМ").
    try:
        reply = await model.ainvoke(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=question)]
        )
    except Exception as error:
        raise ValueError(f"summary model call failed: {error}") from error
    try:
        return _parse(str(reply.text))
    except (json.JSONDecodeError, KeyError, ValidationError, ValueError) as error:
        raise ValueError(f"summary reply not parseable: {error}") from error
