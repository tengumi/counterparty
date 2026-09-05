"""Проверка под цель и версионируемое резюме с явным подтверждением пользователя."""

from __future__ import annotations

import difflib
import secrets
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim
from counterparty_agent.ai.deal import DealField
from counterparty_agent.analytics.core import analyze_snapshot, validate_analysis
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import AnalysisResult, CounterpartySnapshot
from counterparty_agent.projects.evidence import document_facts, project_sources, question_facts
from counterparty_agent.projects.models import (
    DecisionMemo,
    MemoItem,
    MemoProposal,
    Project,
    ReviewStep,
)
from counterparty_agent.projects.planning import (
    accept_context,
    context_hash,
    remember_question,
    synchronize_goal,
)
from counterparty_agent.workflow.review import run_review as run_agent_review
from counterparty_agent.workflow.review import validate_review_run


def current_snapshots(
    project: Project, source: JsonCounterpartySource
) -> list[CounterpartySnapshot]:
    if project.source_hash != source.source_hash:
        raise HTTPException(
            409, "Источник изменился. Заново найдите компании и обновите состав проекта."
        )
    ids = project.shortlist_ids or project.snapshot_ids
    if not ids:
        raise HTTPException(422, "Сначала добавьте хотя бы одного контрагента в проект.")
    snapshots = [source.get_snapshot(key) for key in ids]
    if any(item is None for item in snapshots):
        raise HTTPException(409, "Не все отчёты проекта доступны. Обновите состав проверки.")
    return [item for item in snapshots if item is not None]


def _offline_items(
    snapshots: Sequence[CounterpartySnapshot],
    analyses: Sequence[AnalysisResult],
    extra_facts: Sequence[ApprovedFact],
) -> list[MemoItem]:
    """Без модели доступен явно ограниченный просмотр фактов, без агентского заключения."""
    items = []
    for snapshot, analysis in zip(snapshots, analyses, strict=True):
        catalog = build_fact_catalog(snapshot, analysis)
        bank = next(item for item in catalog if item.topic == "bank_signal" and not item.metric)
        attention = [item for item in catalog if item.topic == "attention_signal"][:3]
        identity_id = next(
            item.evidence_id for item in snapshot.evidence if item.canonical_path == "identity"
        )
        for fact in (bank, *attention):
            items.append(
                MemoItem(
                    kind="fact",
                    text=f"{snapshot.identity.short_name}: {fact.claim.text}",
                    evidence_ids=list(dict.fromkeys((identity_id, *fact.claim.evidence_ids))),
                    company_id=snapshot.snapshot_id,
                )
            )
    for fact in extra_facts:
        items.append(
            MemoItem(
                kind="document"
                if fact.topic in {"user_document", "document_coverage"}
                else "condition",
                text=fact.claim.text,
                evidence_ids=list(fact.claim.evidence_ids),
            )
        )
    items.append(
        MemoItem(
            kind="limitation",
            text="Модель недоступна. Показана ограниченная выборка проверенных фактов и цитат. "
            "Сопоставление с целью и аналитическое заключение не выполнялись.",
        )
    )
    return items


def _claim_items(
    claims: Sequence[GroundedClaim],
    project: Project,
) -> list[MemoItem]:
    document_ids = {item.evidence_id for doc in project.documents for item in doc.fragments}
    condition_ids = {item.evidence_id for item in project.deal.terms.values()} | {
        key for question in project.questions for key in question.evidence_ids
    }
    items = []
    for claim in claims:
        ids = set(claim.evidence_ids)
        kind = (
            "document"
            if ids <= document_ids
            else "condition"
            if ids <= condition_ids
            else "analysis"
        )
        items.append(
            MemoItem(kind=kind, text=claim.text, evidence_ids=list(claim.evidence_ids))  # type: ignore[arg-type]
        )
    return items


def validate_memo(
    memo: DecisionMemo,
    project: Project,
    snapshots: Sequence[CounterpartySnapshot],
    analyses: Sequence[AnalysisResult],
) -> None:
    """Проверяем и принадлежность отдельного факта, и источники совместного вывода."""
    ledgers = {
        snapshot.snapshot_id: {
            item.evidence_id for item in (*snapshot.evidence, *analysis.derived_evidence)
        }
        for snapshot, analysis in zip(snapshots, analyses, strict=True)
    }
    sources = project_sources(project, snapshots, analyses)
    document_ids = {item.evidence_id for doc in project.documents for item in doc.fragments}
    condition_ids = {term.evidence_id for term in project.deal.terms.values()} | {
        key for question in project.questions for key in question.evidence_ids
    }
    allowed = {item.evidence_id for item in sources}
    needed = {key for item in memo.items for key in item.evidence_ids}
    if not needed <= allowed or {item.evidence_id for item in memo.sources} != needed:
        raise ValueError("Резюме содержит источники вне текущего проекта")
    for item in memo.items:
        if item.kind in {"fact", "document", "analysis", "condition"} and not item.evidence_ids:
            raise ValueError("Содержательный вывод должен иметь основание")
        if item.kind == "fact" and not set(item.evidence_ids) <= ledgers.get(
            item.company_id or "", set()
        ):
            raise ValueError("Факт резюме не принадлежит выбранной компании")
        if item.kind == "document" and not set(item.evidence_ids) <= document_ids:
            raise ValueError("Цитата не принадлежит документам проекта")
        if item.kind == "condition" and not set(item.evidence_ids) <= condition_ids:
            raise ValueError("Условия не сообщены пользователем этого проекта")


async def run_review(
    project: Project, source: JsonCounterpartySource, settings: Settings, client: Any, now: datetime
) -> Project:
    synchronize_goal(project)
    snapshots = current_snapshots(project, source)
    analyses = [analyze_snapshot(snapshot, evaluated_at=now) for snapshot in snapshots]
    for snapshot, analysis in zip(snapshots, analyses, strict=True):
        validate_analysis(analysis, snapshot)
    project.deal.snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
    project.deal.source_hash = source.source_hash
    question = "Проанализируй выбранных контрагентов с учётом цели и условий проверки."
    extra_facts = (*document_facts(project, question), *question_facts(project))
    if settings.llm_configured and client is not None:
        result = await run_agent_review(
            settings,
            question,
            snapshots,
            analyses,
            project.deal,
            client=client,
            extra_facts=extra_facts,
        )
        validate_review_run(result)
        accept_context(project, result.deal)
        project.plan_mode = "ai"
        project.plan = [
            ReviewStep(
                step_id=f"step_{index}",
                title=step,
                status="complete" if result.answer.status == "answered" else "limited",
            )
            for index, step in enumerate(result.steps, start=1)
        ]
        if result.answer.status != "answered":
            project.proposal = None
            project.plan.append(
                ReviewStep(step_id="result", title=result.answer.answer, status="limited")
            )
            return project
        items = _claim_items(result.answer.claims, project)
        project.last_fact_ids = list(result.answer.fact_ids)
    else:
        project.plan_mode = "fallback"
        items = _offline_items(snapshots, analyses, extra_facts)
        project.plan = [
            ReviewStep(
                step_id="facts",
                title="Просмотр доступных фактов",
                status="limited",
                detail="Для анализа под цель подключите модель.",
                evidence_ids=list(
                    dict.fromkeys(key for item in items for key in item.evidence_ids)
                ),
            )
        ]
        field: DealField = "advance" if project.goal.strip() else "goal"
        if (
            not project.deal.general_check
            and not getattr(project.deal, field)
            and field not in project.deal.asked_fields
            and len(project.deal.asked_fields) < 2
        ):
            question_text = (
                "Какие условия оплаты согласованы?"
                if field == "advance"
                else "Для какого решения вы проверяете эти компании?"
            )
            # Вопрос уже показан: последующее включение модели не начинает счётчик заново.
            project.deal.question = question_text
            project.deal.asked_fields.append(field)
            remember_question(project, question_text, field=field)
    items.extend(
        MemoItem(kind="action", text=question.text)
        for question in project.questions
        if question.status != "answered"
    )
    needed = {key for item in items for key in item.evidence_ids}
    sources = [
        item for item in project_sources(project, snapshots, analyses) if item.evidence_id in needed
    ]
    memo = DecisionMemo(
        goal=project.goal,
        created_at=now,
        items=items,
        source_hash=source.source_hash,
        selected_snapshot_ids=[snapshot.snapshot_id for snapshot in snapshots],
        document_hashes={doc.document_id: doc.content_hash for doc in project.documents},
        context_hash=context_hash(project),
        sources=sources,
    )
    validate_memo(memo, project, snapshots, analyses)
    old = [item.text for item in project.memo.items] if project.memo else []
    diff = [
        {"kind": "add" if line.startswith("+ ") else "remove", "text": line[2:]}
        for line in difflib.ndiff(old, [item.text for item in memo.items])
        if line.startswith(("+ ", "- "))
    ]
    project.proposal = MemoProposal(
        proposal_id=f"proposal_{secrets.token_hex(12)}",
        base_revision=project.revision + 1,
        memo=memo,
        diff=diff,
    )
    return project
