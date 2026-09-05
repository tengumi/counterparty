"""HTTP проекта: владение, версии, документы, план и подтверждение резюме."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from counterparty_agent.ai.deal import DealContext, validate_deal
from counterparty_agent.api.runtime import _Runtime
from counterparty_agent.projects.commands import apply_command, invalidate_review, require_revision
from counterparty_agent.projects.dialogue import answer_sources, ask_project
from counterparty_agent.projects.documents import MAX_DOCUMENT_BYTES, extract_document
from counterparty_agent.projects.models import (
    CreateProject,
    Project,
    ProjectCommand,
    ProjectQuestion,
)
from counterparty_agent.projects.planning import remember_question, synchronize_goal

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _owner(request: Request) -> tuple[_Runtime, str]:
    runtime: _Runtime = request.app.state.runtime
    owner = await runtime.user_id(request)
    if owner is None:
        raise HTTPException(404, "Сначала начните проверку в этом браузере.")
    return runtime, owner


@router.get("")
async def list_projects(request: Request) -> list[dict[str, Any]]:
    runtime, owner = await _owner(request)
    return await runtime.projects.list(owner)


@router.post("", status_code=201)
async def create_project(payload: CreateProject, request: Request) -> Project:
    runtime, owner = await _owner(request)
    if not payload.title.strip():
        raise HTTPException(422, "Название проекта не должно быть пустым.")
    if len(await runtime.projects.list(owner)) >= 100:
        raise HTTPException(422, "Для локального прототипа достигнут лимит в 100 проектов.")
    async with runtime.session(request, payload.session_id) as key:
        response = await runtime.execute(payload.session_id, key, restore=True)
        async with runtime.saver.conn.execute(
            "SELECT review_context FROM browser_sessions "
            "WHERE session_id = ? AND user_id = ? AND checkpoint_key = ?",
            (payload.session_id, owner, key),
        ) as cursor:
            context_row = await cursor.fetchone()
        deal = (
            DealContext.model_validate_json(context_row[0])
            if context_row and context_row[0]
            else DealContext()
        )
        validate_deal(deal)
    if (
        response.comparison_pending
        or response.candidates
        or any(s.status != "resolved" for s in response.comparison_selections)
    ):
        raise HTTPException(409, "Сначала завершите выбор компаний.")
    assert runtime.source is not None
    cards = response.cards if response.comparison else [response.card] if response.card else []
    if (deal.source_hash and deal.source_hash != runtime.source.source_hash) or (
        deal.snapshot_ids and set(deal.snapshot_ids) != {card.snapshot_id for card in cards}
    ):
        deal = DealContext()
    deal.snapshot_ids = [card.snapshot_id for card in cards]
    deal.source_hash = runtime.source.source_hash
    # Каждый проект получает отдельную сессию: тема другого проекта не наследуется.
    session_id = secrets.token_hex(16)
    checkpoint_key = hashlib.sha256(f"{owner}:{session_id}".encode()).hexdigest()
    await runtime.saver.conn.execute(
        "INSERT INTO browser_sessions (session_id, user_id, checkpoint_key, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, owner, checkpoint_key, time.time()),
    )
    await runtime.saver.conn.commit()
    if cards:
        query = ("Сравни " if len(cards) > 1 else "ИНН ") + "; ".join(c.inn for c in cards)
        await runtime.execute(session_id, checkpoint_key, question=query)
    project = Project(
        project_id=secrets.token_hex(16),
        title=payload.title.strip(),
        goal=payload.goal.strip() or deal.goal or "",
        deal=deal,
        snapshot_ids=[c.snapshot_id for c in cards],
        session_id=session_id,
        source_hash=runtime.source.source_hash,
    )
    synchronize_goal(project)
    remember_question(project, project.deal.question)
    return await runtime.projects.create(project, owner)


@router.get("/{project_id}")
async def get_project(project_id: str, request: Request) -> Project:
    runtime, owner = await _owner(request)
    return await runtime.projects.load(project_id, owner)


@router.post("/{project_id}/open")
async def open_project(project_id: str, request: Request) -> dict[str, Any]:
    runtime, owner = await _owner(request)
    project = await runtime.projects.load(project_id, owner)
    async with runtime.lock:
        async with runtime.saver.conn.execute(
            "SELECT 1 FROM browser_sessions WHERE session_id = ? AND user_id = ?",
            (project.session_id, owner),
        ) as cursor:
            exists = await cursor.fetchone()
    if exists:
        try:
            async with runtime.session(request, project.session_id) as key:
                response = await runtime.execute(project.session_id, key, restore=True)
            return {"project": project, "response": response}
        except HTTPException as error:
            if error.status_code != 404:
                raise
    # Явное открытие проекта восстанавливает выбор, но не тему истёкшего чата.
    session_id = secrets.token_hex(16)
    checkpoint_key = hashlib.sha256(f"{owner}:{session_id}".encode()).hexdigest()
    await runtime.saver.conn.execute(
        "INSERT INTO browser_sessions (session_id, user_id, checkpoint_key, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, owner, checkpoint_key, time.time()),
    )
    await runtime.saver.conn.commit()
    previous_revision = project.revision
    project.session_id = session_id
    project = await runtime.projects.save(project, owner, previous_revision)
    if project.proposal:
        # Смена сессии не меняет факты, но старое подтверждение привязано к прежней ревизии.
        project.proposal = None
        project = await runtime.projects.save(project, owner, project.revision)
    source = runtime.source
    snapshots = [source.get_snapshot(key) for key in project.snapshot_ids] if source else []
    query = ""
    if snapshots and all(s is not None for s in snapshots):
        query = ("Сравни " if len(snapshots) > 1 else "ИНН ") + "; ".join(
            s.identity.inn for s in snapshots if s is not None
        )
    async with runtime.session(request, session_id) as key:
        response = await runtime.execute(session_id, key, question=query, restore=not query)
    return {"project": project, "response": response}


@router.post("/{project_id}/commands")
async def command_project(project_id: str, payload: ProjectCommand, request: Request) -> Project:
    runtime, owner = await _owner(request)
    project = await runtime.projects.load(project_id, owner)
    project = await apply_command(project, payload, runtime, request)
    return await runtime.projects.save(project, owner, payload.expected_revision)


@router.post("/{project_id}/documents", status_code=201)
async def upload_document(
    project_id: str, name: str, expected_revision: int, request: Request
) -> Project:
    runtime, owner = await _owner(request)
    project = await runtime.projects.load(project_id, owner)
    require_revision(project, expected_revision)
    if len(project.documents) >= 5:
        raise HTTPException(422, "В одном проекте поддерживается до пяти документов.")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise HTTPException(413, "Документ превышает 2 МБ.")
    document = await asyncio.to_thread(extract_document, name, bytes(content))
    if any(d.content_hash == document.content_hash for d in project.documents):
        raise HTTPException(409, "Этот документ уже прикреплён к проекту.")
    project.documents.append(document)
    invalidate_review(project)
    return await runtime.projects.save(project, owner, expected_revision)


@router.post("/{project_id}/ask")
async def question_project(
    project_id: str, payload: ProjectQuestion, request: Request
) -> dict[str, Any]:
    runtime, owner = await _owner(request)
    project = await runtime.projects.load(project_id, owner)
    require_revision(project, payload.expected_revision)
    if runtime.source is None:
        raise HTTPException(503, "Источник отчётов недоступен.")
    evaluated_at = datetime.now(UTC)
    previous = project.model_dump()
    answer = await ask_project(
        project,
        runtime.source,
        runtime.settings,
        runtime.llm_client,
        payload.question,
        evaluated_at,
    )
    latest = await runtime.projects.load(project_id, owner)
    require_revision(latest, payload.expected_revision)
    evidence = answer_sources(project, runtime.source, answer, evaluated_at)
    if answer.status == "answered":
        project.last_fact_ids = list(answer.fact_ids)
    if answer.status == "answered" or project.model_dump() != previous:
        if project.proposal is not None:
            project.proposal.base_revision += 1
        latest = await runtime.projects.save(project, owner, payload.expected_revision)
    review = latest.deal.model_dump(
        include={
            "goal",
            "role",
            "subject",
            "amount",
            "advance",
            "deadline",
            "general_check",
            "question",
            "context_revision",
        }
    )
    review["steps"] = [step.title for step in latest.plan]
    return {
        "answer": answer.answer,
        "status": answer.status,
        "claims": answer.claims,
        "llm_used": answer.used_llm,
        "project": latest,
        "evidence": evidence,
        "review": review,
    }
