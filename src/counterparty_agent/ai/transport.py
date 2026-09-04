"""Настраиваемый Chat Completions клиент без логирования payload."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from counterparty_agent.config import Settings

from counterparty_agent.ai.contracts import (
    ChatHistory,
    LlmContextLimitError,
    LlmInvalidResponseError,
    LlmNotConfiguredError,
    LlmResult,
)
from counterparty_agent.ai.prompts import MAX_CONTEXT_CHARACTERS, SYSTEM_PROMPT


def build_messages(
    question: str,
    context: Mapping[str, Any],
    history: ChatHistory = (),
) -> list[dict[str, str]]:
    """Собрать ограниченный запрос, явно отделив данные отчёта."""

    if len(question) > 12_000 or any(len(content) > 4_000 for _, content in history[-8:]):
        raise LlmContextLimitError("Запрос или история превышает допустимый размер")
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for role, content in history[-8:]:
        messages.append({"role": role, "content": content})

    serialized_context = json.dumps(
        context,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    if len(serialized_context) > MAX_CONTEXT_CHARACTERS:
        raise LlmContextLimitError("Проверенный контекст превышает допустимый размер")
    messages.append(
        {
            "role": "user",
            "content": (
                "<INPUT_DATA>\n"
                f"{serialized_context}\n"
                "</INPUT_DATA>\n\n"
                "<QUESTION>\n"
                f"{question}\n"
                "</QUESTION>"
            ),
        }
    )
    return messages


def create_client(settings: Settings) -> Any:
    """Создать официальный асинхронный клиент OpenAI, настроенный на провайдер."""

    from openai import AsyncOpenAI

    # SDK выводит тело запроса на DEBUG, включая сообщения; запрещаем такой trace.
    logging.getLogger("openai._base_client").setLevel(logging.WARNING)
    try:
        api_key = settings.require_llm_api_key()
    except ValueError as error:
        raise LlmNotConfiguredError(str(error)) from error

    return AsyncOpenAI(
        api_key=api_key,
        base_url=settings.normalized_llm_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


async def generate_answer(
    settings: Settings,
    question: str,
    context: Mapping[str, Any],
    history: ChatHistory = (),
    *,
    client: Any | None = None,
) -> LlmResult:
    """Вызвать языковую модель без раскрытия учётных данных и скрытых рассуждений."""

    messages = build_messages(question, context, history)
    llm_client = client if client is not None else create_client(settings)
    try:
        return await _request_completion(settings, messages, llm_client)
    finally:
        if client is None:
            await llm_client.close()


async def _request_completion(
    settings: Settings,
    messages: list[dict[str, str]],
    llm_client: Any,
    *,
    json_mode: bool = False,
) -> LlmResult:
    """Общий ограниченный Chat Completions вызов без отражения payload в ошибках."""

    options: dict[str, object] = {}
    if json_mode:
        options["response_format"] = {"type": "json_object"}
    completion = await llm_client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        extra_body={"reasoning": {"enabled": settings.llm_reasoning_enabled}},
        **options,
    )

    choices = getattr(completion, "choices", None)
    if not choices:
        raise LlmInvalidResponseError("Провайдер вернул ответ без вариантов")
    choice = choices[0]
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise LlmInvalidResponseError("Провайдер вернул пустой ответ")
    if getattr(choice, "finish_reason", None) != "stop":
        raise LlmInvalidResponseError("Провайдер не завершил текстовый ответ")

    usage = getattr(completion, "usage", None)
    return LlmResult(
        answer=content.strip(),
        model=getattr(completion, "model", settings.llm_model),
        finish_reason=getattr(choice, "finish_reason", None),
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
    )


async def _check_connection() -> LlmResult:
    from counterparty_agent.config import get_settings

    settings = get_settings()
    return await generate_answer(
        settings,
        question="Ответь ровно одним словом: READY",
        context={"purpose": "connection_check", "contains_company_data": False},
    )


def main() -> None:
    """Выполнить минимальную платную проверку соединения при явном запуске разработчиком."""

    try:
        result = asyncio.run(_check_connection())
    except LlmNotConfiguredError as error:
        raise SystemExit(str(error)) from error

    print(f"провайдер connection OK: model={result.model}, answer={result.answer!r}")
    print(f"tokens: input={result.input_tokens}, output={result.output_tokens}")
