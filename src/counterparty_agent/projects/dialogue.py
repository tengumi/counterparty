"""Проектный диалог объединяет отчёты, условия сделки и релевантные цитаты."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from typing import Any

from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.comparison_catalog import build_comparison_fact_catalog
from counterparty_agent.ai.contracts import ApprovedFact, GroundedAnswer
from counterparty_agent.ai.deal import apply_deal
from counterparty_agent.ai.periods import _has_nonannual_period, _select_relative_period
from counterparty_agent.ai.router import route_intent
from counterparty_agent.ai.validation import _safe_answer
from counterparty_agent.analytics.comparison import compare_snapshots
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import (
    AnalysisResult,
    CounterpartySnapshot,
    EntityKind,
    ResolutionStatus,
)
from counterparty_agent.projects.evidence import document_facts, project_sources, question_facts
from counterparty_agent.projects.models import Project, ReviewStep
from counterparty_agent.projects.planning import (
    accept_context,
    accept_user_context,
    synchronize_goal,
)
from counterparty_agent.projects.review import current_snapshots
from counterparty_agent.query import QueryParseError, resolve_query
from counterparty_agent.workflow.intents import (
    _LEGAL_FORM_IN_QUESTION,
    _QUOTED_NAME,
    _has_group_reference,
    _has_named_target,
    _ordinal_positions,
    _parse_workflow_query,
)
from counterparty_agent.workflow.review import run_review, validate_review_run

_FINANCIAL_QUESTION = re.compile(
    r"\b(?:выручк|прибыл|убыт|финанс|актив|пассив|капитал|рентабельн)\w*", re.I
)
_RELATIVE_YEAR = re.compile(r"\b(?:предыдущ|прошл)\w*\s+год\w*", re.I)


def _period_question(
    project: Project,
    question: str,
    snapshots: list[CounterpartySnapshot],
    analyses: list[AnalysisResult],
    now: datetime,
) -> str | None:
    """Сохраняем прежние ограничения периодов перед вызовом аналитического цикла."""
    if not (_FINANCIAL_QUESTION.search(question) or _RELATIVE_YEAR.search(question)):
        return question
    if _has_nonannual_period(question):
        return None
    facts = (
        build_fact_catalog(snapshots[0], analyses[0])
        if len(snapshots) == 1
        else build_comparison_fact_catalog(
            snapshots, compare_snapshots(snapshots, evaluated_at=now)
        )
    )
    catalog = {fact.fact_id: fact for fact in facts}
    previous = [catalog[key] for key in project.last_fact_ids[-8:] if key in catalog]
    selected, period = _select_relative_period(question, catalog, previous)
    if not selected:
        return None
    years = {int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", question)}
    available = {fact.period for fact in selected.values() if fact.period is not None}
    if years and not years <= available:
        return None
    if period is not None:
        metrics = {fact.metric for fact in selected.values() if fact.metric}
        metric = next(iter(metrics)) if len(metrics) == 1 else ""
        return question + f" Уточнение по предыдущему ответу: год {period}, показатель {metric}."
    return question


async def ask_project(
    project: Project,
    source: JsonCounterpartySource,
    settings: Settings,
    client: Any,
    question: str,
    now: datetime,
) -> GroundedAnswer:
    if not settings.llm_configured:
        return _safe_answer("llm_unavailable", used_llm=False, model=None)
    snapshots = current_snapshots(project, source)
    project_snapshots = snapshots
    try:
        plan = _parse_workflow_query(question)
    except QueryParseError:
        return _safe_answer("insufficient_data", used_llm=False, model=None)
    # «Сопоставь условия договора» не является именем компании только потому,
    # что старый парсер распознал команду сравнения. До LLM проверяем лишь явные
    # реквизиты и названия; прочие адресаты проверяются по плану роутера ниже.
    named = _has_named_target(plan) and bool(
        any(mention.kind is not EntityKind.NAME for mention in plan.mentions)
        or _LEGAL_FORM_IN_QUESTION.search(question)
        or _QUOTED_NAME.search(question)
    )
    positions = _ordinal_positions(question.casefold())
    if named:
        targets = resolve_query(plan, source)
        if any(result.status is not ResolutionStatus.RESOLVED for result in targets.results):
            return _safe_answer("insufficient_data", used_llm=False, model=None)
        selected = {result.candidates[0].snapshot_id for result in targets.results}
        if not selected <= {snapshot.snapshot_id for snapshot in snapshots}:
            return _safe_answer("insufficient_data", used_llm=False, model=None)
        snapshots = [snapshot for snapshot in snapshots if snapshot.snapshot_id in selected]
    elif any(mention.kind is not EntityKind.NAME for mention in plan.mentions):
        return _safe_answer("insufficient_data", used_llm=False, model=None)
    elif positions:
        if len(positions) != 1 or not 1 <= positions[0] <= len(snapshots):
            return _safe_answer("insufficient_data", used_llm=False, model=None)
        snapshots = [snapshots[positions[0] - 1]]
    analyses = [analyze_snapshot(snapshot, evaluated_at=now) for snapshot in snapshots]
    if (
        not _RELATIVE_YEAR.search(question)
        and _period_question(project, question, snapshots, analyses, now) is None
    ):
        return _safe_answer("insufficient_data", used_llm=False, model=None)
    remembered_focus = next(
        (s for s in project_snapshots if s.snapshot_id == project.focused_snapshot_id), None
    )
    synchronize_goal(project)
    routed = await route_intent(
        settings,
        question,
        {
            "companies": [
                {
                    "position": index,
                    "name": snapshot.identity.short_name or snapshot.identity.full_name,
                    "inn": snapshot.identity.inn,
                }
                for index, snapshot in enumerate(project_snapshots, start=1)
            ],
            "focused_position": positions[0]
            if len(positions) == 1
            else project_snapshots.index(remembered_focus) + 1
            if remembered_focus is not None
            else None,
            "review_context": project.deal.model_dump(mode="json"),
        },
        client=client,
    )
    if routed.plan is None:
        return _safe_answer("llm_unavailable", used_llm=routed.used_llm, model=routed.model)
    intent = routed.plan
    if (
        intent.action in {"ask", "show"}
        and len(project_snapshots) >= 2
        and intent.position is None
        and not intent.targets
        and _has_group_reference(question)
    ):
        intent = intent.model_copy(update={"scope": "group"})
    if intent.action not in {"ask", "lookup", "show", "compare"}:
        return _safe_answer("insufficient_data", used_llm=True, model=routed.model)
    if intent.targets:
        selected = set()
        for target in intent.targets:
            try:
                results = resolve_query(_parse_workflow_query(target), source).results
            except QueryParseError:
                return _safe_answer("insufficient_data", used_llm=True, model=routed.model)
            if any(item.status is not ResolutionStatus.RESOLVED for item in results):
                return _safe_answer("insufficient_data", used_llm=True, model=routed.model)
            selected.update(item.candidates[0].snapshot_id for item in results)
        if not selected or not selected <= {snapshot.snapshot_id for snapshot in snapshots}:
            return _safe_answer("insufficient_data", used_llm=True, model=routed.model)
        snapshots = [snapshot for snapshot in snapshots if snapshot.snapshot_id in selected]
    elif intent.position is not None and positions != [intent.position]:
        return _safe_answer("insufficient_data", used_llm=True, model=routed.model)
    explicit_target = bool(named or positions or intent.targets)
    focus = None
    if explicit_target and len(snapshots) == 1:
        focus = snapshots[0]
    elif intent.scope == "current" and remembered_focus is not None:
        focus = remembered_focus
        snapshots = [focus]
    # scope=group оставляет весь разрешённый состав и явно снимает прежний фокус.
    analyses = [analyze_snapshot(snapshot, evaluated_at=now) for snapshot in snapshots]
    resolved = _period_question(project, question, snapshots, analyses, now)
    if resolved is None:
        return _safe_answer("insufficient_data", used_llm=True, model=routed.model)
    new_focus_id = focus.snapshot_id if focus is not None else None
    if project.focused_snapshot_id != new_focus_id:
        project.last_fact_ids = []
    project.focused_snapshot_id = new_focus_id
    accept_user_context(project, apply_deal(project.deal, intent.deal_patch, question), question)
    project.deal.snapshot_ids = [snapshot.snapshot_id for snapshot in project_snapshots]
    project.deal.source_hash = source.source_hash
    extra_facts: tuple[ApprovedFact, ...] = (
        *document_facts(project, question),
        *question_facts(project),
    )
    result = await run_review(
        settings,
        resolved,
        snapshots,
        analyses,
        project.deal,
        client=client,
        extra_facts=extra_facts,
        initial_topics=intent.review_topics if intent.answer_mode == "analysis" else (),
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
    answer = result.answer
    # Если использованы цитаты выборки, ограничение остаётся видно даже при коротком ответе.
    coverage = next((fact for fact in extra_facts if fact.topic == "document_coverage"), None)
    document_ids = {fragment.evidence_id for doc in project.documents for fragment in doc.fragments}
    if (
        answer.status == "answered"
        and coverage is not None
        and any(set(claim.evidence_ids) & document_ids for claim in answer.claims)
        and coverage.claim.text not in answer.answer
    ):
        answer = replace(
            answer,
            answer=answer.answer + "\n\n" + coverage.claim.text,
            claims=(*answer.claims, coverage.claim),
        )
    return answer


def answer_sources(
    project: Project, source: JsonCounterpartySource, answer: GroundedAnswer, now: datetime
) -> list[dict[str, Any]]:
    needed = {key for claim in answer.claims for key in claim.evidence_ids}
    snapshots = current_snapshots(project, source)
    analyses = [analyze_snapshot(snapshot, evaluated_at=now) for snapshot in snapshots]
    sources = [
        item.model_dump()
        for item in project_sources(project, snapshots, analyses)
        if item.evidence_id in needed
    ]
    if needed != {item["evidence_id"] for item in sources}:
        raise ValueError("Источники ответа не принадлежат проекту")
    return sources
