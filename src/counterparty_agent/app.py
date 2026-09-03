"""Граница FastAPI для статического демоинтерфейса и чата на базе DSLab."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from counterparty_agent.config import Settings, get_settings
from counterparty_agent.llm import ChatRole, LlmNotConfiguredError, generate_answer

LOGGER = logging.getLogger(__name__)
UI_PATH = Path(__file__).with_name("ui") / "index.html"
MAX_SESSION_MESSAGES = 8


class ChatRequest(BaseModel):
    """Компактные нормализованные входные данные для одного хода диалога."""

    session_id: str = Field(min_length=4, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    question: str = Field(min_length=1, max_length=2_000)
    context: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """Ответ для временного HTML-макета."""

    answer: str
    model: str
    finish_reason: str | None = None


@dataclass(slots=True)
class _SessionRecord:
    updated_at: float
    messages: deque[tuple[ChatRole, str]] = field(
        default_factory=lambda: deque(maxlen=MAX_SESSION_MESSAGES)
    )


_SESSIONS: dict[str, _SessionRecord] = {}
SettingsDependency = Annotated[Settings, Depends(get_settings)]


def _prune_sessions(settings: Settings, now: float) -> None:
    expired = [
        session_id
        for session_id, record in _SESSIONS.items()
        if now - record.updated_at > settings.session_ttl_seconds
    ]
    for session_id in expired:
        _SESSIONS.pop(session_id, None)


def _session_record(settings: Settings, session_id: str) -> _SessionRecord:
    now = time.monotonic()
    _prune_sessions(settings, now)
    record = _SESSIONS.setdefault(session_id, _SessionRecord(updated_at=now))
    record.updated_at = now
    return record


app = FastAPI(
    title="Counterparty Agent",
    version="0.1.0",
    description="Grounded counterparty chat backed by DSLab Qwen3.7 Plus",
)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Отдать одностраничный прототип интерфейса с того же источника, что и API."""

    return FileResponse(UI_PATH)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/health")
async def health(settings: SettingsDependency) -> dict[str, str | bool]:
    """Сообщить состояние конфигурации без платного вызова модели."""

    return {
        "status": "ok",
        "llm_configured": settings.llm_configured,
        "llm_provider": "dslab",
        "llm_model": settings.llm_model,
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, settings: SettingsDependency) -> ChatResponse:
    """Ответить по нормализованному контексту и ограниченной истории текущей сессии."""

    record = _session_record(settings, payload.session_id)
    history = list(record.messages)
    try:
        result = await generate_answer(
            settings,
            question=payload.question,
            context=payload.context,
            history=history,
        )
    except LlmNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        LOGGER.warning("DSLab request failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail="Не удалось получить ответ модели. Проверьте ключ, баланс и доступность DSLab.",
        ) from error

    record.messages.append(("user", payload.question))
    record.messages.append(("assistant", result.answer))
    record.updated_at = time.monotonic()
    return ChatResponse(
        answer=result.answer,
        model=result.model,
        finish_reason=result.finish_reason,
    )


@app.delete("/api/sessions/{session_id}", status_code=204)
async def clear_session(session_id: str) -> Response:
    """Удалить одну демосессию, не затрагивая состояние других пользователей."""

    _SESSIONS.pop(session_id, None)
    return Response(status_code=204)


def run() -> None:
    """Запустить локальный демосервер через консольный скрипт из pyproject.toml."""

    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
