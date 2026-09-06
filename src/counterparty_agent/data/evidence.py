"""Исходные доказательства, provenance и пути нормализованных полей."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from counterparty_agent.models import (
    ActivityProfile,
    ArbitrationSummary,
    ArbitrationYearSummary,
    BankRiskAssessment,
    CompanyIdentity,
    CompanyStatus,
    EnforcementProceeding,
    Evidence,
    EvidenceCoverage,
    EvidenceKind,
    FinancialCoefficients,
    FinancialStatement,
    LicenseRecord,
    PartyType,
    PiiClass,
    ReputationPolarity,
    ReputationProfile,
)


def _build_evidence(
    *,
    company_id: str,
    snapshot_id: str,
    report_at: datetime,
    source_name: str,
    source_hash: str,
    record_hash: str,
    identity: CompanyIdentity,
    status: CompanyStatus,
    bank_risk: BankRiskAssessment,
    base_risk_level_raw: str | None,
    financial_statements: tuple[FinancialStatement, ...] | None,
    financial_coefficients: FinancialCoefficients | None,
    arbitration_summary: ArbitrationSummary,
    arbitration_by_year: tuple[ArbitrationYearSummary, ...] | None,
    enforcement_proceedings: tuple[EnforcementProceeding, ...],
    activities: ActivityProfile,
    licenses: tuple[LicenseRecord, ...] | None,
    reputation: ReputationProfile,
) -> tuple[Evidence, ...]:
    evidence: list[Evidence] = []

    def add(
        canonical_path: str,
        stable_key: str,
        source_paths: tuple[str, ...],
        typed_value: object,
        *,
        kind: EvidenceKind = EvidenceKind.OBSERVED,
        coverage: EvidenceCoverage = EvidenceCoverage.PRESENT,
        period: int | str | None = None,
        unit: str | None = None,
        currency: str | None = None,
        pii_class: PiiClass = PiiClass.NONE,
    ) -> None:
        identifier_source = json.dumps(
            {
                "version": "evidence-v1",
                "snapshot_id": snapshot_id,
                "canonical_path": canonical_path,
                "stable_key": stable_key,
                "kind": kind.value,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        evidence_id = f"evidence_{hashlib.sha256(identifier_source.encode()).hexdigest()[:24]}"
        evidence.append(
            Evidence(
                evidence_id=evidence_id,
                company_id=company_id,
                snapshot_id=snapshot_id,
                canonical_path=canonical_path,
                stable_key=stable_key,
                source_paths=source_paths,
                kind=kind,
                typed_value=typed_value,
                report_at=report_at,
                source_name=source_name,
                source_hash=source_hash,
                record_hash=record_hash,
                period=period,
                unit=unit,
                currency=currency,
                coverage=coverage,
                pii_class=pii_class,
            )
        )

    add(
        "report_at",
        "reportDate",
        ("/report/reportDate",),
        report_at,
    )
    add(
        "identity",
        "identity",
        ("/report/baseInfo",),
        identity.model_dump(mode="python"),
        pii_class=PiiClass.ORGANIZATION,
    )
    add(
        "status",
        "status",
        ("/report/status",),
        status.model_dump(mode="python"),
        kind=EvidenceKind.PROVIDER_ASSERTION,
    )
    add(
        "bank_risk",
        "zskRiskLevel",
        ("/report/zskRiskLevel", "/report/reportDate"),
        bank_risk.model_dump(mode="python"),
        kind=EvidenceKind.PROVIDER_ASSERTION,
        coverage=(
            EvidenceCoverage.PRESENT
            if bank_risk.raw_level is not None
            else EvidenceCoverage.MISSING
        ),
    )
    add(
        "base_risk_level_raw",
        "baseInfo.riskLevel",
        ("/report/baseInfo/riskLevel",),
        base_risk_level_raw,
        kind=EvidenceKind.PROVIDER_ASSERTION,
        coverage=(
            EvidenceCoverage.PRESENT
            if base_risk_level_raw is not None
            else EvidenceCoverage.MISSING
        ),
    )

    if financial_statements is None:
        add(
            "financial_statements",
            "section",
            ("/report/finReports",),
            None,
            kind=EvidenceKind.DATA_GAP,
            coverage=(
                EvidenceCoverage.NOT_APPLICABLE
                if identity.party_type is PartyType.INDIVIDUAL_ENTREPRENEUR
                else EvidenceCoverage.MISSING
            ),
        )
    elif not financial_statements:
        add(
            "financial_statements",
            "section",
            ("/report/finReports",),
            (),
            coverage=EvidenceCoverage.EMPTY,
        )
    else:
        for index, statement in enumerate(financial_statements):
            add(
                "financial_statements.item",
                f"year:{statement.year}",
                (f"/report/finReports/{index}",),
                statement.model_dump(mode="python"),
                period=statement.year,
                unit="ruble",
                currency="RUB",
            )

    if financial_coefficients is None:
        add(
            "financial_coefficients",
            "section",
            ("/report/coefficient",),
            None,
            kind=EvidenceKind.DATA_GAP,
            coverage=EvidenceCoverage.MISSING,
        )
    else:
        add(
            "financial_coefficients",
            f"year:{financial_coefficients.year}",
            ("/report/coefficient",),
            financial_coefficients.model_dump(mode="python"),
            kind=EvidenceKind.PROVIDER_ASSERTION,
            period=financial_coefficients.year,
        )

    add(
        "arbitration_summary",
        "summary",
        ("/report/arbitrationByStatus",),
        arbitration_summary.model_dump(mode="python"),
        kind=EvidenceKind.PROVIDER_ASSERTION,
        unit="ruble",
        currency="RUB",
    )
    if arbitration_by_year is None:
        add(
            "arbitration_by_year",
            "section",
            ("/report/arbitrationCases",),
            None,
            kind=EvidenceKind.DATA_GAP,
            coverage=EvidenceCoverage.MISSING,
        )
    elif not arbitration_by_year:
        add(
            "arbitration_by_year",
            "section",
            ("/report/arbitrationCases",),
            (),
            coverage=EvidenceCoverage.EMPTY,
        )
    else:
        for index, year_summary in enumerate(arbitration_by_year):
            add(
                "arbitration_by_year.item",
                f"year:{year_summary.year}",
                (f"/report/arbitrationCases/{index}",),
                year_summary.model_dump(mode="python"),
                period=year_summary.year,
                unit="ruble",
                currency="RUB",
            )

    if not enforcement_proceedings:
        add(
            "enforcement_proceedings",
            "section",
            ("/report/executionProceedings",),
            (),
            coverage=EvidenceCoverage.EMPTY,
        )
    else:
        for index, proceeding in enumerate(enforcement_proceedings):
            stable_value = f"{proceeding.number}|{proceeding.opened_at.isoformat()}"
            stable_key = f"item:{hashlib.sha256(stable_value.encode()).hexdigest()[:16]}"
            add(
                "enforcement_proceedings.item",
                stable_key,
                (f"/report/executionProceedings/{index}",),
                proceeding.model_dump(mode="python"),
                unit="ruble",
                currency="RUB",
                pii_class=PiiClass.ORGANIZATION,
            )

    add(
        "activities.main",
        f"code:{activities.main.code}",
        ("/report/kindsOfActivityInfo/mainKindOfActivity",),
        activities.main.model_dump(mode="python"),
        kind=EvidenceKind.PROVIDER_ASSERTION,
    )
    if activities.others is None:
        add(
            "activities.others",
            "section",
            ("/report/kindsOfActivityInfo/otherKindsOfActivity",),
            None,
            kind=EvidenceKind.DATA_GAP,
            coverage=EvidenceCoverage.MISSING,
        )
    elif not activities.others:
        add(
            "activities.others",
            "section",
            ("/report/kindsOfActivityInfo/otherKindsOfActivity",),
            (),
            coverage=EvidenceCoverage.EMPTY,
        )
    else:
        for index, activity in enumerate(activities.others):
            add(
                "activities.others.item",
                f"code:{activity.code}",
                (f"/report/kindsOfActivityInfo/otherKindsOfActivity/{index}",),
                activity.model_dump(mode="python"),
                kind=EvidenceKind.PROVIDER_ASSERTION,
            )

    if licenses is None:
        add(
            "licenses",
            "section",
            ("/report/licenses",),
            None,
            kind=EvidenceKind.DATA_GAP,
            coverage=EvidenceCoverage.MISSING,
        )
    elif not licenses:
        add(
            "licenses",
            "section",
            ("/report/licenses",),
            (),
            coverage=EvidenceCoverage.EMPTY,
        )
    else:
        for index, license_record in enumerate(licenses):
            stable_key = f"number:{hashlib.sha256(license_record.number.encode()).hexdigest()[:16]}"
            add(
                "licenses.item",
                stable_key,
                (f"/report/licenses/{index}",),
                license_record.model_dump(mode="python"),
                kind=EvidenceKind.PROVIDER_ASSERTION,
                pii_class=PiiClass.ORGANIZATION,
            )

    for polarity, signals in (
        (ReputationPolarity.POSITIVE, reputation.positive),
        (ReputationPolarity.NEGATIVE, reputation.negative),
    ):
        source_path = f"/report/reputationalRisks/{polarity.value}"
        if not signals:
            add(
                f"reputation.{polarity.value}",
                "section",
                (source_path,),
                (),
                kind=EvidenceKind.PROVIDER_ASSERTION,
                coverage=EvidenceCoverage.EMPTY,
            )
            continue
        for index, signal in enumerate(signals):
            add(
                f"reputation.{polarity.value}.item",
                f"code:{signal.canonical_code}",
                (f"{source_path}/{index}",),
                signal.model_dump(mode="python"),
                kind=EvidenceKind.PROVIDER_ASSERTION,
            )

    return tuple(evidence)
