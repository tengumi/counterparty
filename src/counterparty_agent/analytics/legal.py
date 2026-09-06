"""Суды, исполнительные производства и сигналы поставщика."""

from __future__ import annotations

from decimal import Decimal

from counterparty_agent.analytics.common import (
    _NEGATIVE_SIGNAL_TOPICS,
    AnalysisValidationError,
    _AnalysisBuilder,
    _contains_none,
    _encode,
    _money,
    _number,
)
from counterparty_agent.models import (
    Evidence,
    FindingCategory,
    FindingDataStatus,
    FindingSeverity,
)


def _analyze_arbitration(builder: _AnalysisBuilder) -> None:
    summary = builder.snapshot.arbitration_summary
    parents = builder.inputs("arbitration_summary", (summary.model_dump(mode="python"),))
    values = summary.model_dump(mode="python")
    partial = _contains_none(values)
    amount = (
        f"{_money(summary.total_amount)} рублей"
        if summary.total_amount is not None
        else "не указана"
    )
    summary_text = (
        f"Судебных дел в отчёте: {_number(summary.total_count)}. Сумма требований: {amount}. "
        f"Завершённых дел в роли истца: {_number(summary.as_plaintiff.finished_count)}; "
        f"в роли ответчика: {_number(summary.as_defendant.finished_count)}. "
        f"Незавершённых дел в роли ответчика: {_number(summary.as_defendant.pending_count)}. "
        "Наличие дела не означает проигрыш или подтверждённый долг."
    )
    if (
        summary.total_count is None
        and summary.total_amount is None
        and all(
            value is None
            for role in (summary.as_plaintiff, summary.as_defendant)
            for value in role.model_dump().values()
        )
    ):
        summary_text = "Сводных данных о судебных делах нет. Это не означает, что дел не было."
    builder.add(
        "arbitration_summary",
        FindingCategory.ARBITRATION,
        summary_text,
        values,
        parents,
        status=FindingDataStatus.PARTIAL if partial else FindingDataStatus.CONFIRMED,
        unit="ruble",
        currency="RUB",
    )
    defendant = summary.as_defendant
    if defendant.pending_count is not None and defendant.pending_count > 0:
        builder.add(
            "pending_defendant_cases",
            FindingCategory.ARBITRATION,
            f"В сводке указаны незавершённые дела в роли ответчика: {defendant.pending_count}. "
            "Исход дел и обоснованность требований из этого показателя неизвестны.",
            {"count": defendant.pending_count, "amount": defendant.pending_amount},
            parents,
            severity=FindingSeverity.ATTENTION,
            unit="ruble",
            currency="RUB",
            status=FindingDataStatus.PARTIAL
            if defendant.pending_amount is None
            else FindingDataStatus.CONFIRMED,
        )
    years = builder.snapshot.arbitration_by_year
    if not years:
        history_inputs = builder.inputs("arbitration_by_year", (years,))
        builder.add(
            "arbitration_history_missing",
            FindingCategory.DATA_QUALITY,
            "Годовая статистика судов отсутствует или пуста; это не означает отсутствия дел.",
            {"missing": years is None},
            history_inputs,
            status=FindingDataStatus.INSUFFICIENT,
        )
    else:
        history_inputs = builder.inputs(
            "arbitration_by_year.item", tuple(item.model_dump(mode="python") for item in years)
        )
        builder.add(
            "arbitration_coverage_unknown",
            FindingCategory.DATA_QUALITY,
            "Есть годовая статистика и отдельная сводка судов. Их покрытие и "
            "непересекаемость ролей не подтверждены; агрегаты не складываются между собой.",
            {"years": tuple(sorted(item.year for item in years))},
            (*parents, *history_inputs),
            status=FindingDataStatus.PARTIAL,
        )


def _analyze_enforcement(builder: _AnalysisBuilder) -> None:
    records = builder.snapshot.enforcement_proceedings
    parents = builder.inputs(
        "enforcement_proceedings.item" if records else "enforcement_proceedings",
        tuple(item.model_dump(mode="python") for item in records) if records else ((),),
    )
    active = tuple(item for item in records if item.is_active)
    known = tuple(item.amount for item in records if item.amount is not None)
    active_known = tuple(item.amount for item in active if item.amount is not None)
    missing = sum(item.amount is None for item in records)
    active_missing = sum(item.amount is None for item in active)
    future_count = sum(item.opened_at > builder.snapshot.report_at for item in records)
    values: dict[str, object] = {
        "total_count": len(records),
        "active_count": len(active),
        "inactive_count": len(records) - len(active),
        "known_amount": sum(known, Decimal(0)) if known else None,
        "missing_amount_count": missing,
        "active_known_amount": sum(active_known, Decimal(0)) if active_known else None,
        "active_missing_amount_count": active_missing,
        "active_known_amount_count": len(active_known),
        "future_opened_count": future_count,
    }
    builder.add(
        "enforcement_summary",
        FindingCategory.ENFORCEMENT,
        f"Исполнительных производств в отчёте: {len(records)}, "
        f"из них отмечены активными: {len(active)}. "
        + (
            f"Известная сумма по активным записям: {_money(sum(active_known, Decimal(0)))} рублей. "
            f"Сумма указана у {len(active_known)} из {len(active)} активных записей. "
            if active_known
            else "Суммы активных записей неизвестны. "
            if active
            else "В выгрузке активных записей нет; это не подтверждает отсутствие долга. "
        )
        + (f"У активных записей без суммы: {active_missing}. " if active_missing else "")
        + "Это сведения на дату отчёта, не общий долг компании на сегодня.",
        values,
        (*parents, *builder.inputs("report_at", (builder.snapshot.report_at,))),
        unit="ruble",
        currency="RUB",
        status=(
            FindingDataStatus.CONFLICTING
            if future_count
            else FindingDataStatus.PARTIAL
            if missing
            else FindingDataStatus.CONFIRMED
        ),
        severity=FindingSeverity.ATTENTION if active else FindingSeverity.INFO,
    )
    builder.add(
        "debt_total_unavailable",
        FindingCategory.ENFORCEMENT,
        "Суммы судебных требований и исполнительных производств нельзя складывать "
        "в общий долг: их связь, пересечение и текущие остатки в этих сводках не установлены. "
        "Известная сумма производств не подтверждает полную задолженность компании.",
        {"overlap_verified": False, "current_total_debt_known": False},
        (
            *parents,
            *builder.inputs(
                "arbitration_summary",
                (builder.snapshot.arbitration_summary.model_dump(mode="python"),),
            ),
        ),
        status=FindingDataStatus.INSUFFICIENT,
    )
    if future_count:
        builder.add(
            "enforcement_after_report",
            FindingCategory.DATA_QUALITY,
            f"Производств с датой открытия после даты отчёта: {future_count}. "
            "Временная согласованность требует проверки.",
            {"count": future_count, "report_at": builder.snapshot.report_at},
            (*parents, *builder.inputs("report_at", (builder.snapshot.report_at,))),
            status=FindingDataStatus.CONFLICTING,
            severity=FindingSeverity.ATTENTION,
        )


def _analyze_reputation(builder: _AnalysisBuilder) -> None:
    profile = builder.snapshot.reputation
    inputs: list[Evidence] = []
    negative_inputs: dict[str, Evidence] = {}
    for polarity, signals in (("positive", profile.positive), ("negative", profile.negative)):
        parents = builder.inputs(
            f"reputation.{polarity}.item" if signals else f"reputation.{polarity}",
            tuple(item.model_dump(mode="python") for item in signals) if signals else ((),),
        )
        inputs.extend(parents)
        if polarity == "negative":
            negative_inputs = {item.stable_key: item for item in parents}
    builder.add(
        "reputation_summary",
        FindingCategory.REPUTATION,
        f"В отчёте поставщика положительных сигналов: {len(profile.positive)}, "
        f"отрицательных: {len(profile.negative)}. "
        "Положительные сигналы не отменяют отрицательные.",
        {"positive_count": len(profile.positive), "negative_count": len(profile.negative)},
        inputs,
        severity=FindingSeverity.ATTENTION if profile.negative else FindingSeverity.INFO,
    )
    for signal in sorted(profile.negative, key=lambda item: item.canonical_code):
        evidence = negative_inputs.get(f"code:{signal.canonical_code}")
        if evidence is None or _encode(evidence.typed_value) != _encode(
            signal.model_dump(mode="python")
        ):
            raise AnalysisValidationError("Доказательство относится к другому сигналу поставщика")
        topic = _NEGATIVE_SIGNAL_TOPICS.get(signal.canonical_code)
        builder.add(
            "provider_negative_signal",
            FindingCategory.REPUTATION,
            f"В отчёте отмечено обстоятельство для проверки: {topic}. "
            "Это отметка источника; её основание и актуальность нужно уточнить."
            if topic
            else "В отрицательном разделе есть неизвестный правилам сигнал поставщика; "
            "его значение не интерпретируется.",
            {"raw_code": signal.raw_code, "canonical_code": signal.canonical_code},
            (evidence,),
            period=signal.canonical_code,
            severity=FindingSeverity.ATTENTION,
            status=FindingDataStatus.CONFIRMED if topic else FindingDataStatus.PARTIAL,
        )


def _analyze_licenses(builder: _AnalysisBuilder) -> None:
    licenses = builder.snapshot.licenses
    parents = builder.inputs(
        "licenses.item" if licenses else "licenses",
        tuple(item.model_dump(mode="python") for item in licenses) if licenses else (licenses,),
    )
    builder.add(
        "license_coverage",
        FindingCategory.COMPANY,
        "Сведения о лицензиях отсутствуют или пусты. Это не доказывает работу без "
        "обязательной лицензии: требования конкретной сделки не заданы."
        if not licenses
        else f"В отчёте записей о лицензиях: {len(licenses)}. Их достаточность для конкретной "
        "сделки не оценивалась.",
        {"missing": licenses is None, "count": len(licenses) if licenses is not None else None},
        parents,
        status=FindingDataStatus.INSUFFICIENT if not licenses else FindingDataStatus.CONFIRMED,
    )
