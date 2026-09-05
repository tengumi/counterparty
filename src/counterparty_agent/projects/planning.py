"""Контекст цели и открытые вопросы проекта с происхождением ответов пользователя."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from counterparty_agent.ai.deal import (
    FIELDS,
    DealContext,
    DealField,
    DealPatch,
    apply_deal,
    extract_deal,
)
from counterparty_agent.config import Settings
from counterparty_agent.projects.models import OpenQuestion, Project


def context_hash(project: Project) -> str:
    """Вопрос агента не меняет условия; ответ пользователя меняет основания резюме."""
    value = {
        "goal": project.goal,
        "general_check": project.deal.general_check,
        "terms": {key: term.text for key, term in project.deal.terms.items()},
        "answers": {
            question.question_id: question.answer
            for question in project.questions
            if question.answer is not None
        },
    }
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def answer_evidence_id(project: Project, question: OpenQuestion) -> str:
    return (
        "project_answer_"
        + hashlib.sha256(
            f"{project.project_id}\0{question.question_id}\0{question.answer}".encode()
        ).hexdigest()[:24]
    )


def synchronize_goal(project: Project) -> None:
    """Поле цели заполняет сам пользователь; дополнительный вызов модели не нужен."""
    if project.goal.strip() and project.goal != project.deal.goal:
        project.deal = apply_deal(project.deal, DealPatch(goal=project.goal), project.goal)


def remember_question(project: Project, text: str | None, field: DealField | None = None) -> None:
    if not text or not text.strip():
        return
    key = "question_" + hashlib.sha256(text.strip().encode()).hexdigest()[:20]
    if field is None and project.deal.question == text and project.deal.asked_fields:
        field = next((key for key in FIELDS if key == project.deal.asked_fields[-1]), None)
    if not any(item.question_id == key for item in project.questions):
        project.questions.append(OpenQuestion(question_id=key, text=text.strip(), field=field))


def accept_context(project: Project, deal: DealContext) -> bool:
    """Новое условие инвалидирует только ещё не принятое резюме."""
    previous = context_hash(project)
    project.deal = deal
    if deal.goal is not None:
        project.goal = deal.goal
    remember_question(project, deal.question)
    changed = previous != context_hash(project)
    if changed:
        project.proposal = None
        project.plan = []
        project.last_fact_ids = []
        if project.memo is not None:
            project.memo_stale = True
    return changed


async def update_context(project: Project, message: str, settings: Settings, client: Any) -> bool:
    synchronize_goal(project)
    deal = await extract_deal(settings, message, project.deal, client=client)
    return accept_user_context(project, deal, message)


def accept_user_context(project: Project, deal: DealContext, message: str) -> bool:
    """Связываем ответ с заданным вопросом только при извлечённом новом условии."""
    pending = project.deal.question
    asked = project.deal.asked_fields[-1] if project.deal.asked_fields else None
    previous_term = project.deal.terms.get(asked or "")
    current_term = deal.terms.get(asked or "")
    changed_fields = {
        key for key, term in deal.terms.items() if term != project.deal.terms.get(key)
    }
    answered = bool(
        pending
        and (
            (current_term is not None and current_term != previous_term)
            or (deal.general_check and not project.deal.general_check)
        )
    )
    changed = accept_context(project, deal)
    for question in project.questions:
        # Ответ мог прийти позже, когда другой вопрос или условие уже сняли pending.
        # Закрываем также ещё открытые вопросы, сохраняя источник фактического ответа.
        if question.field in changed_fields:
            record_answer(project, question, message.strip())
    if answered:
        pending_question = next((item for item in project.questions if item.text == pending), None)
        if pending_question is not None and pending_question.answer != message.strip():
            record_answer(project, pending_question, message.strip())
    return changed or answered


def record_answer(project: Project, question: OpenQuestion, answer: str) -> None:
    """Ответ хранится как сведения пользователя, а не подтверждение исполнения сделки."""
    question.answer = answer
    question.status = "answered"
    question.answered_at = datetime.now(UTC)
    question.evidence_ids = [answer_evidence_id(project, question)]
    project.proposal = None
    project.plan = []
    project.last_fact_ids = []
    if project.memo is not None:
        project.memo_stale = True
