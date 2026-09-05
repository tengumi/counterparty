"""Связь выбранных компаний, условий текущей сессии и аналитического цикла."""

from __future__ import annotations

import re

from langgraph.runtime import Runtime

from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.comparison_catalog import build_comparison_fact_catalog
from counterparty_agent.ai.contracts import ApprovedFact
from counterparty_agent.ai.deal import DealContext, apply_deal
from counterparty_agent.analytics.comparison import compare_snapshots
from counterparty_agent.analytics.core import analyze_snapshot
from counterparty_agent.workflow.contracts import WorkflowContext, WorkflowResult, WorkflowState
from counterparty_agent.workflow.review import ReviewRun, run_review

_RELATIVE_YEAR = re.compile(
    r"\b(?:предыдущ(?:ий|его|ем)|прошл(?:ый|ого|ом))\s+год(?:а|у|ом|е)?\b", re.I
)
_SHORT_RELATIVE_YEAR = re.compile(
    r"(?:а\s+)?(?:(?:какая|какой|какие|покажи)\s+)?"
    r"(?:(?:выручк[ау]|прибыл[ьи]|убыток|активы|пассивы|капитал)\s+)?"
    r"(?:(?:за|в)\s+)?(?:предыдущ(?:ий|ем)|прошл(?:ый|ом))\s+год(?:у)?",
    re.I,
)


def is_short_relative_question(question: str) -> bool:
    """Короткое уточнение показателя сохраняет строгий прежний выбор финансового года."""
    return _SHORT_RELATIVE_YEAR.fullmatch(" ".join(question.split()).strip(" .!?")) is not None


def previous_topics(state: WorkflowState, context: WorkflowContext) -> list[str]:
    """В роутер попадают только темы/метрики выбранных ID, без текстов прошлых ответов."""
    snapshot_id = state.get("focused_snapshot_id") or state.get("selected_snapshot_id")
    snapshot = context.source.get_snapshot(snapshot_id) if snapshot_id else None
    if snapshot is not None:
        catalog = build_fact_catalog(
            snapshot, analyze_snapshot(snapshot, evaluated_at=context.evaluated_at)
        )
        remembered = state.get("last_fact_ids", [])
    else:
        snapshots = [
            snapshot
            for key in state.get("selected_snapshot_ids", [])
            if (snapshot := context.source.get_snapshot(key)) is not None
        ]
        if len(snapshots) < 2:
            return []
        catalog = build_comparison_fact_catalog(
            snapshots, compare_snapshots(snapshots, evaluated_at=context.evaluated_at)
        )
        remembered = state.get("last_comparison_fact_ids", [])
    return list(
        dict.fromkeys(
            ":".join(
                str(value) for value in (fact.topic, fact.metric, fact.period) if value is not None
            )
            for fact in catalog
            if fact.fact_id in remembered
        )
    )[:16]


def _remembered_facts(result: WorkflowResult, run: ReviewRun) -> WorkflowState:
    selected = [
        run.catalog[key]
        for key in run.answer.fact_ids
        if key in run.catalog and run.catalog[key].topic != "deal_context"
    ]
    if result.comparison is not None and not result.focus_snapshot_id:
        group_catalog = build_comparison_fact_catalog(result.snapshots, result.comparison)
        matched = []
        for fact in group_catalog:
            for prior in selected:
                same_period = fact.period == prior.period
                mapped = (
                    (fact.topic == f"comparison_{prior.topic}" and fact.metric == prior.metric)
                    or (
                        prior.topic == "granular_metric"
                        and fact.topic == "comparison_financial"
                        and fact.metric == prior.metric
                    )
                    or (prior.topic == "financial_period" and fact.topic == "comparison_financial")
                    or (prior.metric == "financial_loss" and fact.topic == "comparison_loss")
                    or (
                        prior.topic == "attention_signal"
                        and fact.topic == "comparison_attention_signals"
                    )
                )
                if mapped and same_period:
                    matched.append(fact)
                    break
        return {"last_comparison_fact_ids": _bounded_ids(matched)}
    return {"last_fact_ids": _bounded_ids(selected)}


def _bounded_ids(facts: list[ApprovedFact]) -> list[str]:
    """Разные финансовые основания остаются разными: обрезка не создаёт ложный якорь года."""
    anchors: dict[tuple[int, str, str | None], str] = {}
    for fact in facts:
        if fact.period is not None:
            anchors.setdefault((fact.period, fact.topic, fact.metric), fact.fact_id)
    return list(dict.fromkeys([*anchors.values(), *(fact.fact_id for fact in facts)]))[:8]


def wants_review(context: WorkflowContext) -> bool:
    return bool(
        context.deal is not None
        and context._intent_plan is not None
        and context._intent_plan.answer_mode == "analysis"
    )


async def review_session(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> WorkflowState:
    context = runtime.context
    result = context.result
    if context.deal is None or result is None:
        return {}
    if (
        result.status not in {"analyzed", "compared", "focused", "answered", "insufficient_data"}
        or result.comparison_pending
    ):
        return {}
    snapshots = result.snapshots or ((result.snapshot,) if result.snapshot else ())
    analyses = result.analyses or ((result.analysis,) if result.analysis else ())
    if not snapshots:
        return {}
    deal = context.deal.model_copy(deep=True)
    ids = [s.snapshot_id for s in snapshots]
    plan = context._intent_plan
    # Новая независимая проверка не получает условия старой сделки. Фокус внутри группы
    # и дополнение состава сохраняют общие условия этой же проверки.
    same_scope = not deal.snapshot_ids or set(deal.snapshot_ids) == set(ids)
    extends = bool(
        plan
        and plan.action in {"add_to_comparison", "compare"}
        and set(deal.snapshot_ids) <= set(ids)
    )
    if not same_scope and not extends:
        deal = DealContext()
    deal.snapshot_ids, deal.source_hash = ids, context.source.source_hash
    if plan is not None:
        deal = apply_deal(deal, plan.deal_patch, context.question)
    result.review = context.deal = deal
    if context.restore:
        if deal.question:
            result.answer, result.answer_claims = deal.question, ()
        return {}
    analytical = wants_review(context) or result.status in {"analyzed", "compared"}
    if not analytical:
        return {}
    if deal.question and not wants_review(context):
        result.answer, result.answer_claims = deal.question, ()
        return {}
    if (
        not deal.goal
        and not deal.role
        and not deal.general_check
        and "goal" not in deal.asked_fields
    ):
        deal.question = (
            "Для чего проверяете контрагента: выбираете поставщика, проверяете покупателя "
            "или решаете другую задачу? Можно начать с общей проверки."
        )
        deal.asked_fields.append("goal")
        result.answer, result.answer_claims = deal.question, ()
        return {}
    if context.settings is None:
        return {}
    if _RELATIVE_YEAR.search(context.question):
        result.status = "insufficient_data"
        result.answer = (
            "Уточните показатель и год. Относительный год сейчас определяю для конкретного "
            "показателя из предыдущего ответа; общий анализ за относительный период не поддержан."
        )
        result.answer_claims = ()
        return {"status": result.status}
    scope_snapshots = (
        (result.snapshot,) if result.focus_snapshot_id and result.snapshot else snapshots
    )
    scope_analyses = (
        (result.analysis,) if result.focus_snapshot_id and result.analysis else analyses
    )
    run = await run_review(
        context.settings,
        context.question or "Выполните проверку для указанной цели",
        scope_snapshots,
        scope_analyses,
        deal,
        client=context.llm_client,
    )
    result.review_run = run
    result.review = context.deal = run.deal
    result.review_steps = run.steps
    result.answer, result.answer_claims = run.answer.answer, run.answer.claims
    result.status = run.answer.status
    result.mode = "llm" if run.answer.used_llm else "deterministic"
    result.model = run.answer.model
    result.llm_used = result.llm_used or run.answer.used_llm
    # Не сохраняем тексты/условия в checkpoint. SQLite-граница запишет компактную
    # память отдельно в строку принадлежащей пользователю сессии.
    memory = _remembered_facts(result, run) if run.answer.status == "answered" else {}
    return {**memory, "status": result.status}
