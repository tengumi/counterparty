"""Agent-side counterparty pinning: ask the UI backend to add a company by INN.

The agent's database role holds no write privilege on ``workspace``; pinning a
company is the UI backend's job, since it may read ``reports`` and write
``workspace``. The agent reaches it through one internal, token-authenticated
endpoint — the direction ``AGENT_UI_API_URL`` already declares — so all
provisioning logic (INN resolution, snapshot pinning, slot and context version)
stays in one place instead of being copied here.

The tool this module builds is an ordinary LangChain tool. The Deep Agents loop
calls it like any other; it takes only an INN and returns one short Russian
sentence the model can quote back.
"""

import asyncio
import logging
from collections import defaultdict
from uuid import UUID

import httpx
from langchain_core.tools import BaseTool, tool

from ..config import AgentSettings
from .prompts import (
    ADD_COMPANY_ADDED,
    ADD_COMPANY_ALREADY,
    ADD_COMPANY_FAILED,
    ADD_COMPANY_NOT_FOUND,
    ADD_COMPANY_TOOL_DESCRIPTION,
    ADD_COMPANY_UNNAMED,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0

_project_locks: dict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)
"""One in-process lock per project.

The model often emits several ``add_company_to_check`` calls from one step and
the harness runs them concurrently. Each hits the same project row on the UI
backend (context version, company slot); run in parallel two of three collide
and come back 500. Serialising per project keeps every add on the clean path
the endpoint already handles."""


async def add_company_by_inn(settings: AgentSettings, *, project_id: UUID, inn: str) -> str:
    """POST one INN to the UI backend's internal add-company endpoint.

    Returns a short sentence describing the outcome; never raises for a
    transport or server error, so a failed pin degrades to a message rather
    than a failed run.
    """
    base = settings.ui_api_url
    token = settings.ui_api_internal_token
    if base is None or token is None:  # pragma: no cover - guarded by caller
        return ADD_COMPANY_FAILED.format(inn=inn, reason="провижининг не настроен")
    url = f"{base.rstrip('/')}/api/v1/internal/projects/{project_id}/companies"
    headers = {"X-Internal-Token": token.get_secret_value()}
    try:
        async with _project_locks[project_id], httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, json={"inn": inn}, headers=headers)
            if response.status_code >= 500:
                # A row conflict with a sibling add; the serialised retry is clean.
                await asyncio.sleep(0.2)
                response = await client.post(url, json={"inn": inn}, headers=headers)
    except httpx.HTTPError as error:
        logger.warning("add_company_to_check transport error: %s", error)
        return ADD_COMPANY_FAILED.format(inn=inn, reason="сервис недоступен")

    if response.status_code >= 500:
        return ADD_COMPANY_FAILED.format(inn=inn, reason="сервис недоступен")
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    outcome = str(body.get("outcome") or "")
    name = str(body.get("name") or "").strip() or ADD_COMPANY_UNNAMED.format(inn=inn)

    if response.status_code == 200 and outcome == "added":
        return ADD_COMPANY_ADDED.format(name=name, inn=inn)
    if outcome == "already_present":
        return ADD_COMPANY_ALREADY.format(name=name, inn=inn)
    if outcome == "not_found" or response.status_code == 404:
        return ADD_COMPANY_NOT_FOUND.format(inn=inn)
    reason = str(body.get("message") or "неизвестная ошибка")
    return ADD_COMPANY_FAILED.format(inn=inn, reason=reason)


def build_add_company_tool(settings: AgentSettings, *, project_id: UUID) -> BaseTool:
    """Build the ``add_company_to_check`` tool bound to one project."""

    @tool("add_company_to_check", description=ADD_COMPANY_TOOL_DESCRIPTION)
    async def add_company_to_check(inn: str) -> str:
        digits = "".join(ch for ch in inn if ch.isdigit())
        if len(digits) not in (10, 12):
            return ADD_COMPANY_FAILED.format(
                inn=inn, reason="ИНН должен состоять из 10 или 12 цифр"
            )
        return await add_company_by_inn(settings, project_id=project_id, inn=digits)

    return add_company_to_check
