"""FastAPI, HTTP-маршруты и раздача готового интерфейса."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from counterparty_agent.api.runtime import COOKIE_NAME, _Runtime
from counterparty_agent.api.schemas import ChatRequest, ChatResponse
from counterparty_agent.config import Settings, get_settings
from counterparty_agent.projects.routes import router as project_router

UI_PATH = Path(__file__).parent.parent / "ui" / "index.html"


UI_BUILD = Path(__file__).parent.parent / "ui" / "build"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Собрать приложение; источник и SQLite открываются один раз на lifespan."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured = settings or get_settings()
        configured.session_db_path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(configured.session_db_path)) as saver:
            runtime = _Runtime(configured, saver)
            try:
                await runtime.setup()
                application.state.runtime = runtime
                yield
            finally:
                if runtime.llm_client is not None:
                    await runtime.llm_client.close()

    application = FastAPI(title="Counterparty Agent", version="0.1.0", lifespan=lifespan)
    application.mount("/ui", StaticFiles(directory=UI_BUILD, check_dir=False), name="ui")
    application.include_router(project_router)

    @application.middleware("http")
    async def local_boundary(request: Request, call_next: Any) -> Response:
        # Записи из браузера разрешены только с текущего origin; это не банковская авторизация.
        origin = request.headers.get("origin")
        if request.method in {"POST", "DELETE", "PUT", "PATCH"} and origin:
            if origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Запрос с другого сайта запрещён."}, status_code=403)
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        del request, error
        # Ответ FastAPI по умолчанию включает input: не отражаем пользовательский текст/PII.
        return JSONResponse({"detail": "Неверный формат запроса."}, status_code=422)

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        built = UI_BUILD / "index.html"
        return FileResponse(built if built.exists() else UI_PATH)

    @application.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @application.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        runtime: _Runtime = request.app.state.runtime
        return {
            "status": "ok" if runtime.source is not None else "degraded",
            "mode": "grounded_llm" if runtime.settings.llm_configured else "deterministic",
            "source_status": runtime.source_status,
            "companies_count": len(runtime.source.snapshots) if runtime.source else 0,
            "llm_configured": runtime.settings.llm_configured,
            "llm_used": False,
            "qa_available": runtime.settings.llm_configured,
        }

    @application.post("/api/sessions", status_code=201)
    async def new_session(request: Request, response: Response) -> dict[str, str]:
        runtime: _Runtime = request.app.state.runtime
        async with runtime.lock:
            await runtime.prune()
            user_id = await runtime.user_id(request)
            if user_id is None:
                token = secrets.token_urlsafe(32)
                user_id = hashlib.sha256(token.encode()).hexdigest()
                await runtime.saver.conn.execute(
                    "INSERT INTO browser_identities VALUES (?, ?)", (user_id, time.time())
                )
                response.set_cookie(
                    COOKIE_NAME,
                    token,
                    httponly=True,
                    samesite="strict",
                    secure=request.url.scheme == "https",
                )
            session_id = secrets.token_hex(16)
            checkpoint_key = hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()
            await runtime.saver.conn.execute(
                "INSERT INTO browser_sessions VALUES (?, ?, ?, ?)",
                (session_id, user_id, checkpoint_key, time.time()),
            )
            await runtime.saver.conn.execute(
                "UPDATE browser_identities SET updated_at = ? WHERE user_id = ?",
                (time.time(), user_id),
            )
            await runtime.saver.conn.commit()
        return {"session_id": session_id}

    @application.get("/api/sessions/{session_id}", response_model=ChatResponse)
    async def restore_session(session_id: str, request: Request) -> ChatResponse:
        runtime: _Runtime = request.app.state.runtime
        async with runtime.session(request, session_id) as key:
            return await runtime.execute(session_id, key, restore=True)

    @application.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        runtime: _Runtime = request.app.state.runtime
        async with runtime.session(request, payload.session_id) as key:
            return await runtime.execute(
                payload.session_id,
                key,
                question=payload.question,
                candidate_snapshot_id=payload.candidate_snapshot_id,
                candidate_selection_id=payload.candidate_selection_id,
            )

    @application.delete("/api/sessions/{session_id}", status_code=204)
    async def clear_session(session_id: str, request: Request) -> Response:
        runtime: _Runtime = request.app.state.runtime
        async with runtime.session(request, session_id) as key:
            async with runtime.lock:
                await runtime.saver.adelete_thread(key)
                await runtime.saver.conn.execute(
                    "DELETE FROM browser_sessions WHERE session_id = ?", (session_id,)
                )
                await runtime.saver.conn.commit()
                # Все ожидающие на прежнем lock после пробуждения получат 404.
                runtime.session_locks.pop(key, None)
        return Response(status_code=204)

    return application


app = create_app()


def run() -> None:
    """Запустить локальный сервер через uv run python src/main.py."""

    import uvicorn

    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
