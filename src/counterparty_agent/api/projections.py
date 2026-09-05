"""Проверенные проекции карточки, матрицы и источников."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.comparison_catalog import build_comparison_fact_catalog
from counterparty_agent.ai.deal import FIELDS, validate_deal
from counterparty_agent.analytics.comparison import validate_comparison
from counterparty_agent.analytics.core import validate_analysis
from counterparty_agent.api.schemas import (
    ChatResponse,
    CompanyCard,
    ComparisonSelectionView,
    EvidenceView,
    ReviewView,
)
from counterparty_agent.models import (
    AnalysisResult,
    CounterpartySnapshot,
    Evidence,
)
from counterparty_agent.workflow.contracts import WorkflowResult
from counterparty_agent.workflow.review import review_catalog, validate_review_run

IDENTITY_FIELDS = {"inn", "ogrn", "full_name", "short_name", "party_type"}


def _evidence_view(item: Evidence) -> EvidenceView:
    value = item.typed_value
    projected = item.canonical_path in {"identity", "status"}
    if item.canonical_path == "identity":
        value = {key: value[key] for key in IDENTITY_FIELDS if key in value}
    elif item.canonical_path == "status":
        value = {key: value[key] for key in ("raw_status", "effective_at") if key in value}
    return EvidenceView(
        evidence_id=item.evidence_id,
        canonical_path=item.canonical_path,
        kind=item.kind,
        value=TypeAdapter(Any).dump_python(value, mode="json"),
        value_is_projection=projected,
        source_name=item.source_name,
        report_at=item.report_at,
        source_hash=item.source_hash,
        record_hash=item.record_hash,
        source_paths=item.source_paths[:8],
        source_paths_total=len(item.source_paths),
        derived_from=item.derived_from[:8],
        derived_from_total=len(item.derived_from),
        quality=item.quality,
        coverage=item.coverage,
        unit=item.unit,
        currency=item.currency,
    )


def _response(session_id: str, result: WorkflowResult) -> ChatResponse:
    response = ChatResponse(
        session_id=session_id,
        status=result.status,
        answer=result.answer,
        candidates=result.candidates,
        mode="llm" if result.mode == "llm" else "deterministic",
        model=result.model,
        llm_used=result.llm_used,
        answer_claims=result.answer_claims,
        focus_snapshot_id=result.focus_snapshot_id,
        comparison_pending=result.comparison_pending,
        comparison_selections=[
            ComparisonSelectionView.model_validate(item) for item in result.comparison_selections
        ],
    )
    review_verified = False
    if result.review is not None:
        deal = result.review
        validate_deal(deal)
        response.review = ReviewView(
            **{key: getattr(deal, key) for key in FIELDS},
            general_check=deal.general_check,
            question=deal.question,
            context_revision=deal.context_revision,
            steps=result.review_steps,
        )
        response.evidence = [
            EvidenceView(
                evidence_id=term.evidence_id,
                canonical_path=f"deal.{key}",
                kind="user_context",
                value=term.text,
                source_name="Сведения пользователя",
                report_at=term.recorded_at,
                source_hash=term.evidence_id,
                record_hash=term.evidence_id,
                source_paths=(f"deal.{key}",),
                source_paths_total=1,
                derived_from=(),
                derived_from_total=0,
                quality="user_context",
                coverage="user_provided",
                unit=None,
                currency=None,
            )
            for key, term in deal.terms.items()
        ]
        if result.review_run is not None:
            run = result.review_run
            validate_review_run(run)
            snapshots = (result.snapshot,) if result.snapshot else result.snapshots
            analyses = (result.analysis,) if result.analysis else result.analyses
            catalog, _ = review_catalog(snapshots, analyses, deal)
            if any(catalog.get(key) != fact for key, fact in run.catalog.items()):
                raise ValueError("Анализ использует посторонний источник")
            if result.answer != run.answer.answer or result.answer_claims != run.answer.claims:
                raise ValueError("Аналитический ответ изменён после проверки")
            review_verified = True
    extra_ids = {e.evidence_id for e in response.evidence}
    if result.comparison is not None:
        validate_comparison(result.comparison, result.snapshots)
        if len(result.snapshots) != len(result.analyses):
            raise ValueError("Не все участники сравнения имеют проверенный анализ")
        response.cards = [
            _company_card(snapshot, analysis)
            for snapshot, analysis in zip(result.snapshots, result.analyses, strict=True)
        ]
        ledgers = {
            card.snapshot_id: {item.evidence_id for item in card.evidence}
            for card in response.cards
        }
        if tuple(card.snapshot_id for card in response.cards) != result.comparison.snapshot_ids:
            raise ValueError("Карточки не соответствуют порядку сравнения")
        for row in result.comparison.rows:
            for cell in row.cells:
                if not cell.evidence_ids or not set(cell.evidence_ids) <= ledgers.get(
                    cell.snapshot_id, set()
                ):
                    raise ValueError("Основание ячейки отсутствует в карточке её компании")
        if result.focus_snapshot_id is not None:
            if result.focus_snapshot_id not in ledgers:
                raise ValueError("Фокус не принадлежит текущему сравнению")
            index = result.comparison.snapshot_ids.index(result.focus_snapshot_id)
            if (
                result.snapshot != result.snapshots[index]
                or result.analysis != result.analyses[index]
            ):
                raise ValueError("Карточка в фокусе не соответствует участнику сравнения")
            response.card = response.cards[index]
            available_ids = ledgers[result.focus_snapshot_id]
            approved = (
                build_fact_catalog(result.snapshots[index], result.analyses[index])
                if result.answer_claims
                else ()
            )
        else:
            if result.snapshot is not None or result.analysis is not None:
                raise ValueError("Одиночная карточка внутри сравнения требует явного фокуса")
            available_ids = set().union(*ledgers.values())
            approved = (
                build_comparison_fact_catalog(result.snapshots, result.comparison)
                if result.answer_claims
                else ()
            )
        # Граф проверяет fact_id; HTTP-граница повторно проверяет точный текст и scope.
        if any(
            not set(claim.evidence_ids) <= available_ids | extra_ids
            or (not review_verified and not any(claim == fact.claim for fact in approved))
            for claim in result.answer_claims
        ):
            raise ValueError("Утверждение ответа не принадлежит выбранному контексту")
        if result.answer_claims and result.answer != "\n\n".join(
            claim.text for claim in result.answer_claims
        ):
            raise ValueError("Текст ответа не соответствует подтверждённым утверждениям")
        response.comparison = result.comparison
        return response
    if result.snapshots or result.analyses or result.focus_snapshot_id is not None:
        raise ValueError("Групповые данные не связаны с проверенным сравнением")
    snapshot, analysis = result.snapshot, result.analysis
    if snapshot is None or analysis is None:
        if response.answer_claims:
            raise ValueError("Утверждения ответа не связаны с проверенной карточкой")
        return response
    response.card = _company_card(snapshot, analysis)
    available_ids = {item.evidence_id for item in response.card.evidence}
    if any(
        not claim.evidence_ids or not set(claim.evidence_ids) <= available_ids | extra_ids
        for claim in response.answer_claims
    ):
        raise ValueError("Основание ответа отсутствует в проверенной карточке")
    return response


def _company_card(snapshot: CounterpartySnapshot, analysis: AnalysisResult) -> CompanyCard:
    """Одинаковая ограниченная проекция для одиночного отчёта и колонок сравнения."""

    validate_analysis(analysis, snapshot)
    # Только разрешённые разделы: исходный ledger целиком в API не попадает.
    source_evidence = {
        item.canonical_path: item
        for item in snapshot.evidence
        if item.canonical_path in {"identity", "status", "report_at", "bank_risk"}
    }
    return CompanyCard(
        company_id=snapshot.company_id,
        snapshot_id=snapshot.snapshot_id,
        name=snapshot.identity.full_name,
        short_name=snapshot.identity.short_name,
        inn=snapshot.identity.inn,
        ogrn=snapshot.identity.ogrn,
        party_type=snapshot.identity.party_type,
        raw_status=snapshot.status.raw_status,
        report_at=snapshot.report_at,
        evaluated_at=analysis.evaluated_at,
        bank_risk=analysis.bank_risk,
        identity_evidence_id=source_evidence["identity"].evidence_id,
        status_evidence_id=source_evidence["status"].evidence_id,
        report_evidence_id=source_evidence["report_at"].evidence_id,
        bank_evidence_id=analysis.bank_evidence_id,
        findings=analysis.findings,
        evidence=[
            _evidence_view(item)
            for item in (
                *source_evidence.values(),
                *analysis.derived_evidence,
            )
        ],
    )
