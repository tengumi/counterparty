"""Публичные HTTP-контракты без полного исходного отчёта."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from counterparty_agent.ai.contracts import GroundedClaim
from counterparty_agent.ai.deal import DealPatch
from counterparty_agent.api.constants import SESSION_PATTERN
from counterparty_agent.models import (
    BankRiskAssessment,
    ComparisonResult,
    CounterpartyCandidate,
    Finding,
)


class ChatRequest(BaseModel):
    """Клиент передаёт запрос или подтверждение, но не факты для анализа."""

    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(pattern=SESSION_PATTERN)
    question: str = Field(default="", max_length=12_000, repr=False)
    candidate_snapshot_id: str | None = Field(default=None, pattern=r"^snapshot_[0-9a-f]{24}$")
    candidate_selection_id: str | None = Field(default=None, pattern=r"^selection_[0-9a-f]{24}$")

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if bool(self.question.strip()) == bool(self.candidate_snapshot_id):
            raise ValueError("Передайте непустой вопрос либо одного выбранного кандидата")
        if self.candidate_selection_id is not None and self.candidate_snapshot_id is None:
            raise ValueError("Позиция сравнения должна сопровождаться выбранным кандидатом")
        return self


class EvidenceView(BaseModel):
    """Явная проекция доказательства; полный ledger и контакты не сериализуются."""

    evidence_id: str
    canonical_path: str
    kind: str
    value: Any = Field(repr=False)
    value_is_projection: bool = False
    source_name: str
    report_at: datetime
    source_hash: str
    record_hash: str
    source_paths: tuple[str, ...]
    source_paths_total: int
    derived_from: tuple[str, ...]
    derived_from_total: int
    quality: str
    coverage: str
    unit: str | None
    currency: str | None


class CompanyCard(BaseModel):
    """Карточка проверенной компании без полного исходного отчёта."""

    company_id: str
    snapshot_id: str
    name: str = Field(repr=False)
    short_name: str | None = Field(default=None, repr=False)
    inn: str = Field(repr=False)
    ogrn: str = Field(repr=False)
    party_type: str
    raw_status: str
    report_at: datetime
    evaluated_at: datetime
    bank_risk: BankRiskAssessment
    identity_evidence_id: str
    status_evidence_id: str
    report_evidence_id: str
    bank_evidence_id: str
    findings: tuple[Finding, ...]
    evidence: list[EvidenceView]


class ComparisonSelectionView(BaseModel):
    """Позиция запроса без исходного текста: результат поиска или выбор кандидата."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")
    selection_id: str
    position: int
    status: str
    snapshot_id: str | None = None
    candidates: list[CounterpartyCandidate] = Field(default_factory=list)
    message: str


class ReviewView(DealPatch):
    question: str | None = None
    context_revision: int = 0
    steps: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Единый ответ поиска, уточнения и восстановления текущей карточки."""

    session_id: str
    status: str
    answer: str
    mode: Literal["deterministic", "llm"] = "deterministic"
    model: str | None = None
    llm_used: bool = False
    answer_claims: tuple[GroundedClaim, ...] = ()
    card: CompanyCard | None = None
    candidates: list[CounterpartyCandidate] = Field(default_factory=list)
    cards: list[CompanyCard] = Field(default_factory=list)
    comparison: ComparisonResult | None = None
    comparison_selections: list[ComparisonSelectionView] = Field(default_factory=list)
    focus_snapshot_id: str | None = None
    comparison_pending: bool = False
    review: ReviewView | None = None
    evidence: list[EvidenceView] = Field(default_factory=list)
