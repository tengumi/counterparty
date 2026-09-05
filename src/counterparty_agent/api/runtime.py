"""Ресурсы приложения, владение сессиями, TTL и блокировки."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langsmith import tracing_context

from counterparty_agent.ai.deal import DealContext
from counterparty_agent.ai.transport import create_client
from counterparty_agent.api.projections import _response
from counterparty_agent.api.schemas import ChatResponse
from counterparty_agent.config import Settings
from counterparty_agent.data.errors import SnapshotSourceError
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.projects.store import ProjectStore
from counterparty_agent.workflow.builder import build_graph
from counterparty_agent.workflow.contracts import InvalidCandidateSelection, WorkflowContext

LOGGER = logging.getLogger(__name__)


COOKIE_NAME = "counterparty_browser"


SESSION_PATTERN = r"^[0-9a-f]{32}$"


class _Runtime:
    """Запросы одной сессии последовательны; разные сессии не ждут чужую LLM."""

    def __init__(self, settings: Settings, saver: AsyncSqliteSaver) -> None:
        self.settings = settings
        self.saver = saver
        self.graph = build_graph(saver)
        self.lock = asyncio.Lock()
        self.session_locks: dict[str, asyncio.Lock] = {}
        self.active_keys: set[str] = set()
        self.llm_client: Any | None = None
        self.source: JsonCounterpartySource | None = None
        self.source_status = "unavailable"
        self.projects = ProjectStore(saver.conn)

    async def setup(self) -> None:
        if self.settings.llm_configured:
            self.llm_client = create_client(self.settings)
        await self.saver.setup()
        await self.projects.setup()
        await self.saver.conn.execute(
            "CREATE TABLE IF NOT EXISTS browser_identities "
            "(user_id TEXT PRIMARY KEY, updated_at REAL NOT NULL)"
        )
        await self.saver.conn.execute(
            "CREATE TABLE IF NOT EXISTS browser_sessions "
            "(session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
            "checkpoint_key TEXT NOT NULL UNIQUE, updated_at REAL NOT NULL)"
        )
        await self.saver.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_browser_sessions_updated "
            "ON browser_sessions(updated_at)"
        )
        async with self.saver.conn.execute("PRAGMA table_info(browser_sessions)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        if "review_context" not in columns:
            await self.saver.conn.execute(
                "ALTER TABLE browser_sessions ADD COLUMN review_context TEXT"
            )
        await self.saver.conn.commit()
        await self.prune()
        try:
            self.source = await asyncio.to_thread(
                JsonCounterpartySource.from_path, self.settings.snapshot_json_path
            )
            self.source_status = self.source.outcome.value
        except SnapshotSourceError as error:
            self.source_status = error.outcome.value
            LOGGER.warning("Источник недоступен: %s", error.code)

    async def prune(self) -> None:
        cutoff = time.time() - self.settings.session_ttl_seconds
        async with self.saver.conn.execute(
            "SELECT session_id, checkpoint_key FROM browser_sessions WHERE updated_at < ?",
            (cutoff,),
        ) as cursor:
            expired = await cursor.fetchall()
        for session_id, checkpoint_key in expired:
            if checkpoint_key in self.active_keys:
                continue
            await self.saver.adelete_thread(checkpoint_key)
            await self.saver.conn.execute(
                "DELETE FROM browser_sessions WHERE session_id = ?", (session_id,)
            )
            self.session_locks.pop(checkpoint_key, None)
        await self.saver.conn.execute(
            "DELETE FROM browser_identities WHERE updated_at < ? AND NOT EXISTS "
            "(SELECT 1 FROM browser_sessions "
            "WHERE browser_sessions.user_id = browser_identities.user_id) AND NOT EXISTS "
            "(SELECT 1 FROM workspace_projects "
            "WHERE workspace_projects.user_id = browser_identities.user_id)",
            (cutoff,),
        )
        await self.saver.conn.commit()

    async def user_id(self, request: Request) -> str | None:
        token = request.cookies.get(COOKIE_NAME, "")
        if not token or len(token) > 128:
            return None
        user_id = hashlib.sha256(token.encode()).hexdigest()
        async with self.saver.conn.execute(
            "SELECT user_id FROM browser_identities WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return user_id if row else None

    async def owned_session(self, request: Request, session_id: str) -> str:
        await self.prune()
        user_id = await self.user_id(request)
        async with self.saver.conn.execute(
            "SELECT checkpoint_key FROM browser_sessions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise HTTPException(404, "Сессия не найдена или истекла. Начните новую сессию.")
        now = time.time()
        await self.saver.conn.execute(
            "UPDATE browser_sessions SET updated_at = ? WHERE session_id = ?", (now, session_id)
        )
        await self.saver.conn.execute(
            "UPDATE browser_identities SET updated_at = ? WHERE user_id = ?", (now, user_id)
        )
        await self.saver.conn.commit()
        return str(row[0])

    @asynccontextmanager
    async def session(self, request: Request, session_id: str) -> AsyncIterator[str]:
        """Проверять владельца до ожидания и повторно после него; DELETE использует тот же lock."""

        async with self.lock:
            key = await self.owned_session(request, session_id)
            session_lock = self.session_locks.setdefault(key, asyncio.Lock())
        async with session_lock:
            async with self.lock:
                # Пока запрос ждал, сессию могли удалить или она могла истечь.
                key = await self.owned_session(request, session_id)
                self.active_keys.add(key)
            try:
                yield key
            finally:
                async with self.lock:
                    self.active_keys.discard(key)
                    now = time.time()
                    await self.saver.conn.execute(
                        "UPDATE browser_sessions SET updated_at = ? WHERE session_id = ?",
                        (now, session_id),
                    )
                    await self.saver.conn.execute(
                        "UPDATE browser_identities SET updated_at = ? WHERE user_id IN "
                        "(SELECT user_id FROM browser_sessions WHERE session_id = ?)",
                        (now, session_id),
                    )
                    await self.saver.conn.commit()

    async def execute(
        self,
        session_id: str,
        checkpoint_key: str,
        *,
        question: str = "",
        candidate_snapshot_id: str | None = None,
        candidate_selection_id: str | None = None,
        restore: bool = False,
    ) -> ChatResponse:
        if self.source is None:
            raise HTTPException(
                503,
                "Источник недоступен. Проверьте COUNTERPARTY_SNAPSHOT_JSON_PATH "
                "и перезапустите сервер.",
            )
        async with self.saver.conn.execute(
            "SELECT review_context FROM browser_sessions "
            "WHERE session_id = ? AND checkpoint_key = ?",
            (session_id, checkpoint_key),
        ) as cursor:
            row = await cursor.fetchone()
        deal = DealContext.model_validate_json(row[0]) if row and row[0] else DealContext()
        if deal.source_hash and deal.source_hash != self.source.source_hash:
            deal = DealContext()
        context = WorkflowContext(
            source=self.source,
            evaluated_at=datetime.now(UTC),
            question=question,
            candidate_snapshot_id=candidate_snapshot_id,
            candidate_selection_id=candidate_selection_id,
            restore=restore,
            settings=self.settings,
            llm_client=self.llm_client,
            deal=deal,
        )
        try:
            # Внешний tracing не должен отправлять запросы и RuntimeContext за пределы стенда.
            with tracing_context(enabled=False):
                await self.graph.ainvoke(
                    {},
                    {"configurable": {"thread_id": checkpoint_key}},
                    context=context,
                )
            if context.result is None:
                raise RuntimeError("Граф не сформировал результат")
            response = _response(session_id, context.result)
            if context.deal is not None:
                await self.saver.conn.execute(
                    "UPDATE browser_sessions SET review_context = ? "
                    "WHERE session_id = ? AND checkpoint_key = ?",
                    (context.deal.model_dump_json(), session_id, checkpoint_key),
                )
                await self.saver.conn.commit()
            return response
        except InvalidCandidateSelection as error:
            raise HTTPException(
                409, "Выбор устарел. Повторите поиск и выберите предложенную компанию."
            ) from error
        except Exception as error:
            LOGGER.warning("Анализ не выполнен: %s", type(error).__name__)
            # Незавершённая проверка не становится подтверждённым контекстом.
            await self.saver.adelete_thread(checkpoint_key)
            raise HTTPException(503, "Не удалось проверить отчёт. Повторите поиск.") from error
