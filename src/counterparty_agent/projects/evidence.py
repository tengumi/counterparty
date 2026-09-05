"""Совместные основания проекта: отчёты, релевантные цитаты и ответы пользователя."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from counterparty_agent.ai.contracts import ApprovedFact, GroundedClaim
from counterparty_agent.ai.deal import validate_deal
from counterparty_agent.models import AnalysisResult, CounterpartySnapshot
from counterparty_agent.projects.models import MemoSource, Project
from counterparty_agent.projects.planning import answer_evidence_id


def document_facts(project: Project, question: str, *, limit: int = 12) -> tuple[ApprovedFact, ...]:
    """Ищем по вопросу и цели во всех фрагментах; не считаем выборку всем документом."""
    words = {
        word[:5] for word in re.findall(r"[а-яёa-z]{4,}", f"{question} {project.goal}".casefold())
    } - {"какие", "какой", "докум", "догов", "покаж", "скажи", "прове", "компа"}
    fragments = [
        (document, fragment)
        for document in project.documents
        if document.status == "ready"
        for fragment in document.fragments
    ]
    ranked = sorted(
        fragments,
        key=lambda item: -sum(word in item[1].text.casefold() for word in words),
    )
    selected = ranked[:limit]
    facts = []
    for document, fragment in selected:
        digest = hashlib.sha256(fragment.evidence_id.encode()).hexdigest()[:24]
        facts.append(
            ApprovedFact(
                f"fact_{digest}",
                GroundedClaim(
                    text=f"Документ «{document.name}», {fragment.location}: «{fragment.text}». "
                    "Сведения пользователя, не подтверждённые банковским отчётом.",
                    evidence_ids=(fragment.evidence_id,),
                ),
                "user_document",
            )
        )
    if selected and len(selected) < len(fragments):
        evidence_ids = tuple(fragment.evidence_id for _, fragment in selected)
        digest = hashlib.sha256("\0".join(evidence_ids).encode()).hexdigest()[:24]
        facts.append(
            ApprovedFact(
                f"coverage_{digest}",
                GroundedClaim(
                    text="Рассмотрена выборка фрагментов по вопросу и цели, не весь документ. "
                    "Отсутствие условия в выборке не означает его отсутствия в файле.",
                    evidence_ids=evidence_ids,
                ),
                "document_coverage",
            )
        )
    return tuple(facts)


def question_facts(project: Project) -> tuple[ApprovedFact, ...]:
    facts = []
    for question in project.questions:
        if question.answer is None:
            continue
        evidence_id = answer_evidence_id(project, question)
        if question.evidence_ids != [evidence_id] or question.answered_at is None:
            raise ValueError("Ответ пользователя потерял своё основание")
        facts.append(
            ApprovedFact(
                f"fact_{evidence_id}",
                GroundedClaim(
                    text=f"На вопрос «{question.text}» пользователь ответил: «{question.answer}». "
                    "Это сообщённое условие, не подтверждение исполнения сделки.",
                    evidence_ids=(evidence_id,),
                ),
                "deal_context",
            )
        )
    return tuple(facts)


def project_sources(
    project: Project,
    snapshots: Sequence[CounterpartySnapshot],
    analyses: Sequence[AnalysisResult],
) -> list[MemoSource]:
    validate_deal(project.deal)
    sources = [
        MemoSource(
            evidence_id=evidence.evidence_id,
            source_name=evidence.source_name,
            company_name=snapshot.identity.short_name or snapshot.identity.full_name,
            report_at=evidence.report_at,
            quality=evidence.quality,
            coverage=evidence.coverage,
            canonical_path=evidence.canonical_path,
        )
        for snapshot, analysis in zip(snapshots, analyses, strict=True)
        for evidence in (*snapshot.evidence, *analysis.derived_evidence)
    ]
    sources.extend(
        MemoSource(
            evidence_id=fragment.evidence_id,
            source_name=document.name,
            report_at=document.uploaded_at,
            quality="user_document",
            coverage="provided",
            canonical_path=fragment.location,
        )
        for document in project.documents
        for fragment in document.fragments
    )
    sources.extend(
        MemoSource(
            evidence_id=term.evidence_id,
            source_name="Условия, сообщённые пользователем",
            report_at=term.recorded_at,
            quality="user_context",
            coverage="provided",
            canonical_path=f"deal.{key}",
        )
        for key, term in project.deal.terms.items()
    )
    question_facts(project)
    sources.extend(
        MemoSource(
            evidence_id=question.evidence_ids[0],
            source_name="Ответ пользователя на уточняющий вопрос",
            report_at=question.answered_at,
            quality="user_context",
            coverage="provided",
            canonical_path=f"questions.{question.question_id}",
        )
        for question in project.questions
        if question.answer is not None and question.answered_at is not None
    )
    return sources
