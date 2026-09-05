"""Изменения проекта и защита подтверждаемого резюме от устаревшего контекста."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request

from counterparty_agent.projects.models import Project, ProjectCommand
from counterparty_agent.projects.planning import (
    context_hash,
    record_answer,
    synchronize_goal,
    update_context,
)
from counterparty_agent.projects.review import current_snapshots, run_review


def require_revision(project: Project, revision: int) -> None:
    if project.revision != revision:
        raise HTTPException(409, "Проект изменился. Обновите страницу и повторите действие.")


def invalidate_review(project: Project) -> None:
    project.proposal = None
    project.plan = []
    project.last_fact_ids = []
    if project.focused_snapshot_id not in (project.shortlist_ids or project.snapshot_ids):
        project.focused_snapshot_id = None
    if project.memo is not None:
        project.memo_stale = True


async def apply_command(
    project: Project, command: ProjectCommand, runtime: Any, request: Request
) -> Project:
    require_revision(project, command.expected_revision)
    if command.action == "set_goal":
        project.goal = command.value.strip()
        if project.goal:
            synchronize_goal(project)
        else:
            project.deal.goal = None
            project.deal.terms.pop("goal", None)
            project.deal.context_revision += 1
            project.deal.question = None
        invalidate_review(project)
    elif command.action == "set_focus":
        if runtime.source is None:
            raise HTTPException(503, "Источник отчётов недоступен.")
        allowed = {snapshot.snapshot_id for snapshot in current_snapshots(project, runtime.source)}
        focus = command.value.strip() or None
        if focus is not None and focus not in allowed:
            raise HTTPException(422, "Выберите компанию из текущего состава проверки.")
        if project.focused_snapshot_id != focus:
            project.last_fact_ids = []
        project.focused_snapshot_id = focus
        if project.proposal is not None:
            # Фокус диалога не меняет факты и состав уже подготовленного резюме.
            project.proposal.base_revision += 1
    elif command.action == "set_shortlist":
        if len(set(command.snapshot_ids)) != len(command.snapshot_ids) or not set(
            command.snapshot_ids
        ) <= set(project.snapshot_ids):
            raise HTTPException(422, "Отбор должен содержать уникальные компании текущего проекта.")
        project.shortlist_ids = command.snapshot_ids
        invalidate_review(project)
    elif command.action == "capture_selection":
        async with runtime.session(request, project.session_id) as key:
            result = await runtime.execute(project.session_id, key, restore=True)
        if (
            result.comparison_pending
            or any(s.status != "resolved" for s in result.comparison_selections)
            or result.candidates
        ):
            raise HTTPException(409, "Сначала подтвердите всех участников сравнения.")
        project.snapshot_ids = (
            [c.snapshot_id for c in result.cards]
            if result.comparison
            else [result.card.snapshot_id]
            if result.card
            else []
        )
        project.shortlist_ids = [
            key for key in project.shortlist_ids if key in project.snapshot_ids
        ]
        project.source_hash = runtime.source.source_hash
        invalidate_review(project)
    elif command.action == "link_document":
        document = next(
            (d for d in project.documents if d.document_id == command.document_id), None
        )
        question = next(
            (q for q in project.questions if q.question_id == command.question_id), None
        )
        if document is None or question is None:
            raise HTTPException(422, "Выберите документ и открытый вопрос этого проекта.")
        for item in project.questions:
            item.document_ids = [key for key in item.document_ids if key != document.document_id]
        document.question_id = question.question_id
        question.document_ids.append(document.document_id)
        if question.answer is None:
            question.status = "needs_confirmation"
        project.proposal = None
    elif command.action == "answer_question":
        question = next(
            (item for item in project.questions if item.question_id == command.question_id), None
        )
        if question is None or not command.value.strip():
            raise HTTPException(422, "Выберите вопрос проекта и укажите ответ.")
        record_answer(project, question, command.value.strip())
        await update_context(project, command.value, runtime.settings, runtime.llm_client)
    elif command.action == "run":
        if runtime.source is None:
            raise HTTPException(503, "Источник отчётов недоступен.")
        project = await run_review(
            project, runtime.source, runtime.settings, runtime.llm_client, datetime.now(UTC)
        )
    elif command.action == "accept_memo":
        proposal = project.proposal
        if (
            proposal is None
            or command.proposal_id != proposal.proposal_id
            or proposal.base_revision != project.revision
        ):
            raise HTTPException(
                409, "Предложение устарело или уже принято. Запустите проверку снова."
            )
        if runtime.source is None:
            raise HTTPException(503, "Источник недоступен: актуальность резюме не подтверждена.")
        snapshots = current_snapshots(project, runtime.source)
        if proposal.memo.selected_snapshot_ids != [
            s.snapshot_id for s in snapshots
        ] or proposal.memo.document_hashes != {
            d.document_id: d.content_hash for d in project.documents
        }:
            raise HTTPException(
                409, "Состав или документы изменились. Сформируйте новое предложение."
            )
        if proposal.memo.context_hash != context_hash(project):
            raise HTTPException(409, "Условия проверки изменились. Сформируйте новое предложение.")
        project.memo = proposal.memo
        project.memo_stale = False
        project.proposal = None
    return project
