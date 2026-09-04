"""Разрешение годов и безопасный отказ для неподдержанных периодов."""

from __future__ import annotations

import re
from collections.abc import Sequence

from counterparty_agent.ai.contracts import ApprovedFact


def _select_relative_period(
    question: str,
    catalog: dict[str, ApprovedFact],
    previous_facts: Sequence[ApprovedFact],
) -> tuple[dict[str, ApprovedFact], int | None]:
    """Вычислить прошлый период обычным кодом и исключить другой год или показатель."""

    normalized = question.lower().replace("ё", "е")
    if not re.search(
        r"\b(?:предыдущ(?:ий|его|ем)|прошл(?:ый|ого|ом))\s+год(?:а|у|ом|е)?\b", normalized
    ):
        return catalog, None
    anchors = {(item.period, item.topic, item.metric) for item in previous_facts if item.period}
    if len(anchors) != 1:
        return {}, None
    period, topic, metric = anchors.pop()
    if period is None:
        return {}, None
    target = period - 1
    explicit_years = {int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", normalized)}
    if explicit_years and explicit_years != {target}:
        return {}, target
    named_metrics = {
        name
        for name, pattern in (
            ("proceeds", r"\bвыручк"),
            ("profit", r"\bприбыл"),
            ("assets_total", r"\bактив"),
            ("liabilities_total", r"\bпассив"),
            ("equity", r"\bкапитал|\bрезерв"),
        )
        if re.search(pattern, normalized)
    }
    if named_metrics and named_metrics != {metric}:
        return {}, target
    return {
        key: item
        for key, item in catalog.items()
        if item.period == target and item.topic == topic and item.metric == metric
    }, target


def _has_nonannual_period(question: str) -> bool:
    """Не подменять запрос квартального или месячного показателя годовым значением."""

    return bool(
        re.search(
            r"\b(?:квартал\w*|полугод\w*|полгод\w*|месяц\w*|помесячн\w*|ежемесячн\w*|"
            r"январ[ьяею]|феврал[ьяею]|март[аеу]?|апрел[ьяею]|ма[йея]|"
            r"июн[ьяею]|июл[ьяею]|август[аеу]?|сентябр[ьяею]|октябр[ьяею]|"
            r"ноябр[ьяею]|декабр[ьяею])\b",
            question.lower(),
        )
    )
