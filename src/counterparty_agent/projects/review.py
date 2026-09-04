"""Ограниченный LangGraph: три чтения и черновик; сохранение только на HTTP-границе."""

from __future__ import annotations

import difflib
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langsmith import tracing_context

from counterparty_agent.analytics.core import analyze_snapshot, validate_analysis
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import AnalysisResult, CounterpartySnapshot
from counterparty_agent.projects.models import (
    DecisionMemo,
    MemoItem,
    MemoProposal,
    MemoSource,
    Project,
    ReviewStep,
)
from counterparty_agent.projects.planning import PlanChoice, choose_plan, questions_for

BANK_LABELS = {
    "GREEN": "надёжный",
    "YELLOW": "требует внимания",
    "RED": "в зоне риска",
    "GREY": "нет данных для оценки",
}
TOPIC_LABELS = {
    "finance": "финансы",
    "arbitration": "суды",
    "enforcement": "исполнительные производства",
    "reputation": "сигналы источника",
    "licenses": "лицензии",
    "data_quality": "качество данных",
}


class ReviewState(TypedDict, total=False):
    completed_steps: list[str]


@dataclass
class ReviewContext:
    project: Project = field(repr=False)
    source: JsonCounterpartySource = field(repr=False)
    settings: Settings = field(repr=False)
    client: Any = field(repr=False)
    now: datetime
    choice: PlanChoice | None = None
    snapshots: list[CounterpartySnapshot] = field(default_factory=list, repr=False)
    analyses: list[AnalysisResult] = field(default_factory=list, repr=False)
    items: list[MemoItem] = field(default_factory=list, repr=False)


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


async def _plan(state: ReviewState, runtime: Runtime[ReviewContext]) -> ReviewState:
    context = runtime.context
    if not context.project.goal.strip():
        raise HTTPException(422, "Укажите цель проверки перед запуском плана.")
    choice, mode = await choose_plan(context.project.goal, context.settings, context.client)
    context.choice = choice
    context.project.plan_mode = mode  # type: ignore[assignment]
    context.project.questions = questions_for(choice, context.project.questions)
    context.project.plan = [
        ReviewStep(step_id="reports", title="Прочитать отчёты выбранных компаний"),
        ReviewStep(step_id="evidence", title="Проверить факты по выбранным темам"),
        ReviewStep(step_id="documents", title="Прочитать документы и связать открытые вопросы"),
    ]
    return {"completed_steps": []}


def _reports(state: ReviewState, runtime: Runtime[ReviewContext]) -> ReviewState:
    context = runtime.context
    context.snapshots = current_snapshots(context.project, context.source)
    step = context.project.plan[0]
    step.status, step.detail = "complete", f"Прочитано отчётов: {len(context.snapshots)}."
    step.evidence_ids = [
        next(e.evidence_id for e in s.evidence if e.canonical_path == "report_at")
        for s in context.snapshots
    ]
    return {"completed_steps": ["reports"]}


def _evidence(state: ReviewState, runtime: Runtime[ReviewContext]) -> ReviewState:
    context = runtime.context
    assert context.choice is not None
    for snapshot in context.snapshots:
        analysis = analyze_snapshot(snapshot, evaluated_at=context.now)
        validate_analysis(analysis, snapshot)
        context.analyses.append(analysis)
        identity_id = next(
            e.evidence_id for e in snapshot.evidence if e.canonical_path == "identity"
        )
        context.items.append(
            MemoItem(
                kind="fact",
                text=f"{snapshot.identity.short_name}: банковский светофор — "
                f"{BANK_LABELS[snapshot.bank_risk.display_level]}. "
                f"Дата отчёта (UTC): {snapshot.report_at.date()}.",
                evidence_ids=[identity_id, analysis.bank_evidence_id],
                company_id=snapshot.snapshot_id,
            )
        )
        selected = [
            f
            for f in analysis.findings
            if f.category in context.choice.categories
            or ("licenses" in context.choice.categories and f.code == "license_coverage")
        ]
        selected.sort(
            key=lambda f: (
                f.severity != "attention",
                -(f.period if isinstance(f.period, int) else 0),
                f.data_status == "confirmed",
            )
        )
        for finding in selected[:4]:
            context.items.append(
                MemoItem(
                    kind="fact",
                    text=f"{snapshot.identity.short_name}: {finding.statement}",
                    evidence_ids=[identity_id, *finding.evidence_ids],
                    company_id=snapshot.snapshot_id,
                )
            )
    step = context.project.plan[1]
    step.status = "complete"
    step.detail = (
        "Проверены темы: "
        + ", ".join(TOPIC_LABELS[key] for key in context.choice.categories)
        + ". В резюме — выборка, полный отчёт остаётся доступен."
    )
    step.evidence_ids = list(
        dict.fromkeys(key for item in context.items for key in item.evidence_ids)
    )
    return {"completed_steps": [*state["completed_steps"], "evidence"]}


def _documents(state: ReviewState, runtime: Runtime[ReviewContext]) -> ReviewState:
    context = runtime.context
    for document in context.project.documents:
        for fragment in document.fragments[:2]:
            context.items.append(
                MemoItem(
                    kind="document",
                    text=f"Документ «{document.name}», {fragment.location}: «{fragment.text}». "
                    "Это текст пользователя, не подтверждённый банковский факт.",
                    evidence_ids=[fragment.evidence_id],
                )
            )
    step = context.project.plan[2]
    ready = [d for d in context.project.documents if d.status == "ready"]
    step.status = "complete" if ready else "limited"
    step.detail = (
        f"Прочитано документов: {len(ready)}. В резюме первые два фрагмента каждого; "
        "вопросы требуют подтверждения."
        if ready
        else "Нет документов с доступным текстом. Открытые вопросы не считаются решёнными."
    )
    step.evidence_ids = [f.evidence_id for d in ready for f in d.fragments]
    return {"completed_steps": [*state["completed_steps"], "documents"]}


def _draft(state: ReviewState, runtime: Runtime[ReviewContext]) -> ReviewState:
    context = runtime.context
    context.items.append(
        MemoItem(
            kind="limitation",
            text="Резюме содержит выбранные факты, а не весь отчёт. "
            "Пропуски не равны отсутствию риска. "
            "Денежное ранжирование и новый риск-скоринг не выполняются.",
        )
    )
    context.items.extend(MemoItem(kind="action", text=q.text) for q in context.project.questions)
    needed = {key for item in context.items for key in item.evidence_ids}
    sources = []
    for snapshot, analysis in zip(context.snapshots, context.analyses, strict=True):
        for item in (*snapshot.evidence, *analysis.derived_evidence):
            if item.evidence_id in needed:
                sources.append(
                    MemoSource(
                        evidence_id=item.evidence_id,
                        source_name=item.source_name,
                        company_name=snapshot.identity.short_name or snapshot.identity.full_name,
                        report_at=item.report_at,
                        quality=item.quality,
                        coverage=item.coverage,
                        canonical_path=item.canonical_path,
                    )
                )
    for document in context.project.documents:
        sources.extend(
            MemoSource(
                evidence_id=f.evidence_id,
                source_name=document.name,
                report_at=document.uploaded_at,
                quality="user_document",
                coverage="provided",
                canonical_path=f.location,
            )
            for f in document.fragments
            if f.evidence_id in needed
        )
    memo = DecisionMemo(
        goal=context.project.goal,
        created_at=context.now,
        items=context.items,
        source_hash=context.source.source_hash,
        selected_snapshot_ids=[s.snapshot_id for s in context.snapshots],
        document_hashes={d.document_id: d.content_hash for d in context.project.documents},
        sources=sources,
    )
    validate_memo(memo, context)
    old = [item.text for item in context.project.memo.items] if context.project.memo else []
    diff = [
        {"kind": "add" if line.startswith("+ ") else "remove", "text": line[2:]}
        for line in difflib.ndiff(old, [i.text for i in memo.items])
        if line.startswith(("+ ", "- "))
    ]
    context.project.proposal = MemoProposal(
        proposal_id=f"proposal_{secrets.token_hex(12)}",
        base_revision=context.project.revision + 1,
        memo=memo,
        diff=diff,
    )
    return state


def validate_memo(memo: DecisionMemo, context: ReviewContext) -> None:
    """Факты не покидают свой snapshot; документ имеет отдельный namespace evidence."""
    ledgers = {
        s.snapshot_id: {e.evidence_id for e in (*s.evidence, *a.derived_evidence)}
        for s, a in zip(context.snapshots, context.analyses, strict=True)
    }
    docs = {f.evidence_id for d in context.project.documents for f in d.fragments}
    for item in memo.items:
        if item.kind == "fact" and (
            not item.evidence_ids
            or not set(item.evidence_ids) <= ledgers.get(item.company_id or "", set())
        ):
            raise ValueError("Факт резюме не принадлежит выбранной компании")
        if item.kind == "document" and (
            not item.evidence_ids or not set(item.evidence_ids) <= docs
        ):
            raise ValueError("Фрагмент не принадлежит документам проекта")


async def run_review(
    project: Project, source: JsonCounterpartySource, settings: Settings, client: Any, now: datetime
) -> Project:
    context = ReviewContext(project, source, settings, client, now)
    graph = StateGraph(ReviewState, context_schema=ReviewContext)
    for name, function in (
        ("plan", _plan),
        ("reports", _reports),
        ("evidence", _evidence),
        ("documents", _documents),
        ("draft", _draft),
    ):
        graph.add_node(name, function)
    for start, end in zip(
        (START, "plan", "reports", "evidence", "documents", "draft"),
        ("plan", "reports", "evidence", "documents", "draft", END),
        strict=True,
    ):
        graph.add_edge(start, end)
    with tracing_context(enabled=False):
        await graph.compile().ainvoke({}, context=context)
    return context.project
