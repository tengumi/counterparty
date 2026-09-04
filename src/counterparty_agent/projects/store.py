"""Локальное состояние проектов в существующем SQLite, без базы отчётов."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from counterparty_agent.projects.models import Project


class ProjectStore:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    async def setup(self) -> None:
        await self.connection.execute(
            "CREATE TABLE IF NOT EXISTS workspace_projects "
            "(project_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, revision INTEGER NOT NULL, "
            "updated_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspace_owner ON workspace_projects(user_id)"
        )
        await self.connection.commit()

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        async with self.connection.execute(
            "SELECT payload FROM workspace_projects WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            Project.model_validate_json(row[0]).model_dump(
                include={"project_id", "title", "goal", "updated_at", "revision", "shortlist_ids"},
                mode="json",
            )
            for row in rows
        ]

    async def load(self, project_id: str, user_id: str) -> Project:
        async with self.connection.execute(
            "SELECT payload FROM workspace_projects WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise HTTPException(404, "Проект не найден в этом рабочем пространстве.")
        return Project.model_validate_json(row[0])

    async def create(self, project: Project, user_id: str) -> Project:
        await self.connection.execute(
            "INSERT INTO workspace_projects VALUES (?, ?, ?, ?, ?)",
            (
                project.project_id,
                user_id,
                project.revision,
                project.updated_at.isoformat(),
                project.model_dump_json(),
            ),
        )
        await self.connection.commit()
        return project

    async def save(self, project: Project, user_id: str, expected_revision: int) -> Project:
        """CAS защищает от параллельных вкладок и устаревших подтверждений."""

        if project.revision != expected_revision:
            raise HTTPException(409, "Проект изменился. Обновите его и повторите действие.")
        project.revision += 1
        project.updated_at = datetime.now(UTC)
        cursor = await self.connection.execute(
            "UPDATE workspace_projects SET revision = ?, updated_at = ?, payload = ? "
            "WHERE project_id = ? AND user_id = ? AND revision = ?",
            (
                project.revision,
                project.updated_at.isoformat(),
                project.model_dump_json(),
                project.project_id,
                user_id,
                expected_revision,
            ),
        )
        await self.connection.commit()
        if cursor.rowcount != 1:
            raise HTTPException(409, "Проект изменился в другой вкладке. Обновите его.")
        return project
