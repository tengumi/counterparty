"""Компактное состояние графа и неперсистентный runtime-контекст."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

from counterparty_agent.ai.contracts import GroundedAnswer, GroundedClaim
from counterparty_agent.ai.router import IntentPlan
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import (
    AnalysisResult,
    ComparisonResult,
    CounterpartyCandidate,
    CounterpartySnapshot,
    QueryPlan,
)


class ComparisonSlotState(TypedDict):
    """Одна позиция списка: только служебные статусы и непрозрачные ID."""

    selection_id: str
    position: int
    status: str
    snapshot_id: str | None
    candidate_snapshot_ids: list[str]


@dataclass(slots=True)
class ComparisonSelection:
    """Временная проекция позиции списка; реквизиты восстанавливаются из источника."""

    selection_id: str
    position: int
    status: str
    snapshot_id: str | None = None
    candidates: list[CounterpartyCandidate] = field(default_factory=list, repr=False)
    message: str = ""


class WorkflowState(TypedDict, total=False):
    """Единственная прикладная структура, разрешённая для сохранения в SQLite."""

    selected_snapshot_id: str | None
    pending_snapshot_ids: list[str]
    source_hash: str
    status: str
    last_fact_ids: list[str]
    selected_snapshot_ids: list[str]
    comparison_slots: list[ComparisonSlotState]
    focused_snapshot_id: str | None
    last_comparison_fact_ids: list[str]
    comparison_extension_pending: bool


@dataclass(slots=True)
class WorkflowResult:
    """Временный предметный результат; API явно выбирает поля для браузера."""

    status: str
    answer: str
    candidates: list[CounterpartyCandidate] = field(default_factory=list, repr=False)
    snapshot: CounterpartySnapshot | None = field(default=None, repr=False)
    analysis: AnalysisResult | None = field(default=None, repr=False)
    answer_claims: tuple[GroundedClaim, ...] = field(default=(), repr=False)
    mode: str = "deterministic"
    model: str | None = None
    llm_used: bool = False
    comparison: ComparisonResult | None = field(default=None, repr=False)
    snapshots: tuple[CounterpartySnapshot, ...] = field(default=(), repr=False)
    analyses: tuple[AnalysisResult, ...] = field(default=(), repr=False)
    comparison_selections: list[ComparisonSelection] = field(default_factory=list, repr=False)
    focus_snapshot_id: str | None = None
    comparison_pending: bool = False


@dataclass(slots=True)
class WorkflowContext:
    """Контекст одного запуска: не вход графа и не содержимое checkpoint."""

    source: JsonCounterpartySource = field(repr=False)
    evaluated_at: datetime
    question: str = field(default="", repr=False)
    candidate_snapshot_id: str | None = None
    restore: bool = False
    settings: Settings | None = field(default=None, repr=False)
    llm_client: Any | None = field(default=None, repr=False)
    candidate_selection_id: str | None = None
    result: WorkflowResult | None = field(default=None, init=False, repr=False)
    _plan: QueryPlan | None = field(default=None, init=False, repr=False)
    _target_snapshot_id: str | None = field(default=None, init=False, repr=False)
    _snapshot: CounterpartySnapshot | None = field(default=None, init=False, repr=False)
    _analysis: AnalysisResult | None = field(default=None, init=False, repr=False)
    _qa_requested: bool = field(default=False, init=False, repr=False)
    _grounded_answer: GroundedAnswer | None = field(default=None, init=False, repr=False)
    _target_snapshot_ids: list[str] = field(default_factory=list, init=False, repr=False)
    _snapshots: tuple[CounterpartySnapshot, ...] = field(default=(), init=False, repr=False)
    _analyses: tuple[AnalysisResult, ...] = field(default=(), init=False, repr=False)
    _comparison: ComparisonResult | None = field(default=None, init=False, repr=False)
    _comparison_question: bool = field(default=False, init=False, repr=False)
    _focus_question: bool = field(default=False, init=False, repr=False)
    _focus_snapshot_id: str | None = field(default=None, init=False, repr=False)
    _base_snapshot_ids: list[str] = field(default_factory=list, init=False, repr=False)
    _comparison_extension: bool = field(default=False, init=False, repr=False)
    _staged_comparison_slots: list[ComparisonSlotState] | None = field(
        default=None, init=False, repr=False
    )
    _pending_response_status: str | None = field(default=None, init=False, repr=False)
    _pending_response_message: str = field(default="", init=False, repr=False)
    _preserve_comparison_state: bool = field(default=False, init=False, repr=False)
    _clear_focus_requested: bool = field(default=False, init=False, repr=False)
    _intent_plan: IntentPlan | None = field(default=None, init=False, repr=False)
    _routing_used_llm: bool = field(default=False, init=False, repr=False)
    _routing_model: str | None = field(default=None, init=False, repr=False)
    _routing_preserve_single: bool = field(default=False, init=False, repr=False)


class InvalidCandidateSelection(ValueError):
    """Выбор не принадлежит текущему серверному списку кандидатов."""
