"""One-shot "на что обратить внимание" block for the report screen.

This is not a conversation turn: no graph, no checkpoint, no tool loop. It
reads a few report sections straight from the MCP tools and asks the model
once, with the response schema passed to the model as structured output —
no JSON-shaped prompt, no hand parsing.

Kept deliberately small — the value is a plain-language orientation for the
task at hand, not a second analysis engine.
"""

import logging
from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .config import AgentSettings
from .harness.models import create_chat_model
from .harness.tools import reports_toolset

logger = logging.getLogger(__name__)

_SECTIONS = ("financials", "execution_proceedings", "arbitration", "risk_signals")

_SYSTEM = (
    "Ты — помощник по проверке контрагентов в Альфа-Бизнесе. Перед тобой отчёт о "
    "компании и задача обычного предпринимателя. Составь блок «на что обратить "
    "внимание»: 3–4 пункта — самое важное из отчёта именно для этой сделки, а не "
    "формальный пересказ.\n"
    "Каждый пункт: 1–2 предложения, живой русский язык без англицизмов и без "
    "Markdown. Называй конкретные числа из отчёта и сразу говори, что это значит "
    "для предпринимателя на практике (например: «денег на счетах 176 тыс. ₽ при "
    "долге поставщикам 171 млн ₽ — ваш аванс может уйти на чужие долги раньше, "
    "чем вам отгрузят товар»). Не выдумывай и не оценивай то, чего в данных нет.\n"
    "Сначала самое существенное: обычно первый пункт — главный риск или главный "
    "плюс для сделки."
)


class SummaryBullet(BaseModel):
    """One line of the orientation block."""

    tone: Literal["risk", "ok", "neutral"] = Field(
        description="risk — настораживает для этой сделки; ok — реально в пользу компании; "
        "neutral — важный нейтральный факт или пробел в данных"
    )
    text: str = Field(
        min_length=1,
        description="1–2 предложения простым языком, с конкретными числами и их смыслом для сделки",
    )


class ReportSummary(BaseModel):
    """The orientation block shown above the raw report sections."""

    bullets: list[SummaryBullet] = Field(
        description="3–4 пункта, самый важный первым", min_length=1, max_length=4
    )
    caveat: str = Field(
        description="одна фраза: это объяснение под задачу пользователя, а не оценка банка; "
        "ниже идут факты как есть"
    )


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


async def build_report_summary(
    settings: AgentSettings, *, report_id: str, task: str
) -> ReportSummary:
    """Read the report, ask the model once with a response schema, return the block.

    Raises:
        ValueError: if the report has no data or the model call fails.
    """
    context = await _gather(settings, report_id)
    if not context:
        raise ValueError("no report data to summarise")
    model = create_chat_model(settings)
    question = (
        f"Задача пользователя: {task or 'оценка контрагента для сделки'}\n\n"
        f"Данные отчёта:\n{context}"
    )
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
