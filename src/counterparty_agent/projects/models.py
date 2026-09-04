"""Контракты проекта; отчёты компаний здесь не сохраняются."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentFragment(ProjectModel):
    evidence_id: str
    text: str = Field(repr=False)
    location: str


class ProjectDocument(ProjectModel):
    document_id: str
    name: str = Field(repr=False)
    content_hash: str
    uploaded_at: datetime
    question_id: str | None = None
    fragments: list[DocumentFragment] = Field(default_factory=list, repr=False)
    status: Literal["ready", "no_text"]
    note: str


class ReviewStep(ProjectModel):
    step_id: str
    title: str
    status: Literal["pending", "complete", "limited"] = "pending"
    detail: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class OpenQuestion(ProjectModel):
    question_id: str
    text: str
    document_ids: list[str] = Field(default_factory=list)


class MemoItem(ProjectModel):
    kind: Literal["fact", "document", "limitation", "action"]
    text: str = Field(repr=False)
    evidence_ids: list[str] = Field(default_factory=list)
    company_id: str | None = None


class MemoSource(ProjectModel):
    evidence_id: str
    source_name: str
    company_name: str | None = None
    report_at: datetime
    quality: str
    coverage: str
    canonical_path: str


class DecisionMemo(ProjectModel):
    title: str = "Резюме проверки"
    goal: str = Field(repr=False)
    created_at: datetime
    items: list[MemoItem]
    source_hash: str
    selected_snapshot_ids: list[str]
    document_hashes: dict[str, str]
    sources: list[MemoSource] = Field(default_factory=list)
    note: str = "Черновик для решения пользователя. Не является одобрением сделки."


class MemoProposal(ProjectModel):
    proposal_id: str
    base_revision: int
    memo: DecisionMemo
    diff: list[dict[str, str]]


class Project(ProjectModel):
    project_id: str
    revision: int = 1
    title: str = Field(min_length=1, max_length=120, repr=False)
    goal: str = Field(default="", max_length=2000, repr=False)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_hash: str
    snapshot_ids: list[str] = Field(default_factory=list)
    shortlist_ids: list[str] = Field(default_factory=list)
    session_id: str
    plan: list[ReviewStep] = Field(default_factory=list)
    questions: list[OpenQuestion] = Field(default_factory=list)
    documents: list[ProjectDocument] = Field(default_factory=list, repr=False)
    memo: DecisionMemo | None = Field(default=None, repr=False)
    proposal: MemoProposal | None = Field(default=None, repr=False)
    plan_mode: Literal["manual", "ai", "fallback"] = "manual"
    last_fact_ids: list[str] = Field(default_factory=list)


class CreateProject(ProjectModel):
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(default="", max_length=2000)
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class ProjectCommand(ProjectModel):
    action: Literal[
        "set_goal", "set_shortlist", "capture_selection", "link_document", "run", "accept_memo"
    ]
    expected_revision: int = Field(ge=1)
    value: str = Field(default="", max_length=2000, repr=False)
    snapshot_ids: list[str] = Field(default_factory=list, max_length=1000)
    document_id: str | None = None
    question_id: str | None = None
    proposal_id: str | None = None


class ProjectQuestion(ProjectModel):
    question: str = Field(min_length=1, max_length=2000, repr=False)
    expected_revision: int = Field(ge=1)
