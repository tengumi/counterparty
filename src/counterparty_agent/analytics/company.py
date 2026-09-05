"""Проверки статуса компании, дат и доступности источника."""

from __future__ import annotations

from datetime import UTC, datetime

from counterparty_agent.analytics.common import _AnalysisBuilder
from counterparty_agent.models import (
    AnalysisPolicy,
    FindingCategory,
    FindingDataStatus,
    FindingSeverity,
)


def _analyze_company(
    builder: _AnalysisBuilder, evaluated_at: datetime, policy: AnalysisPolicy
) -> None:
    snapshot = builder.snapshot
    report_input = builder.inputs("report_at", (snapshot.report_at,))
    age_days = (evaluated_at.date() - snapshot.report_at.astimezone(UTC).date()).days
    age_values: dict[str, object] = {
        "age_days": max(0, age_days),
        "report_at": snapshot.report_at,
        "evaluated_at": evaluated_at,
        "max_report_age_days": policy.max_report_age_days,
    }
    if snapshot.report_at > evaluated_at:
        builder.add(
            "report_future",
            FindingCategory.DATA_QUALITY,
            "Дата отчёта находится после заданного момента анализа; актуальность требует проверки.",
            age_values,
            report_input,
            status=FindingDataStatus.CONFLICTING,
            severity=FindingSeverity.ATTENTION,
        )
    else:
        builder.add(
            "report_age",
            FindingCategory.DATA_QUALITY,
            f"На дату анализа возраст отчёта составляет {age_days} календарных дней.",
            age_values,
            report_input,
            unit="days",
        )
        if policy.max_report_age_days is not None and age_days > policy.max_report_age_days:
            builder.add(
                "report_stale",
                FindingCategory.DATA_QUALITY,
                f"Возраст отчёта превышает настроенный порог {policy.max_report_age_days} дней. "
                "Это политика приложения, не норматив банка.",
                age_values,
                report_input,
                severity=FindingSeverity.ATTENTION,
            )
    status_input = builder.inputs("status", (snapshot.status.model_dump(mode="python"),))
    known_status = snapshot.status.raw_status == "CURRENT"
    builder.add(
        "company_status",
        FindingCategory.COMPANY,
        "Источник указывает статус CURRENT на дату отчёта; это не гарантия исполнения сделки."
        if known_status
        else "Статус источника сохранён, но его трактовка правилами не задана.",
        {"raw_status": snapshot.status.raw_status, "effective_at": snapshot.status.effective_at},
        status_input,
        status=(
            FindingDataStatus.CONFLICTING
            if snapshot.status.effective_at > snapshot.report_at
            else FindingDataStatus.CONFIRMED
            if known_status
            else FindingDataStatus.PARTIAL
        ),
    )
    identity_input = builder.inputs("identity", (snapshot.identity.model_dump(mode="python"),))
    if snapshot.identity.registration_at > snapshot.report_at:
        builder.add(
            "registration_after_report",
            FindingCategory.DATA_QUALITY,
            "Дата регистрации находится после даты отчёта.",
            {"registration_at": snapshot.identity.registration_at, "report_at": snapshot.report_at},
            (*identity_input, *report_input),
            status=FindingDataStatus.CONFLICTING,
            severity=FindingSeverity.ATTENTION,
        )
    if snapshot.status.effective_at > snapshot.report_at:
        builder.add(
            "status_after_report",
            FindingCategory.DATA_QUALITY,
            "Дата статуса находится после даты отчёта.",
            {"effective_at": snapshot.status.effective_at, "report_at": snapshot.report_at},
            (*status_input, *report_input),
            status=FindingDataStatus.CONFLICTING,
            severity=FindingSeverity.ATTENTION,
        )
    if snapshot.bank_risk.recognized_level is None:
        parents = builder.inputs("bank_risk", (snapshot.bank_risk.model_dump(mode="python"),))
        builder.add(
            "bank_risk_unavailable",
            FindingCategory.DATA_QUALITY,
            "Оценка отсутствует или её значение не распознано. "
            "Это не означает низкий риск.",
            {"raw_level": snapshot.bank_risk.raw_level},
            parents,
            status=FindingDataStatus.INSUFFICIENT,
        )
