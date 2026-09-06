"""Отбор обстоятельств и понятная резервная сводка без новых фактов о компании."""

from __future__ import annotations

import re
from collections.abc import Mapping

from counterparty_agent.ai.contracts import ApprovedFact, ReviewBlock, ReviewDraft
from counterparty_agent.ai.deal import FIELDS, DealContext, counterparty_role
from counterparty_agent.ai.topics import needs_bank_assessment, needs_bank_reason

_COMPANY = re.compile(r"^(?P<label>.+?) \(ИНН (?P<inn>\d{10,12})\):\s*")
_GAPS = re.compile(r"не\s+хватает|недостающ\w*|пробел\w*|ограничени\w*|каких\s+данных\s+нет", re.I)
_CAPABILITY = re.compile(r"опыт\w*|качеств\w*|команд\w*|персонал\w*", re.I)
_DEBT_TOTAL = re.compile(r"полн\w*\s+(?:сумм\w*|долг\w*)|общ\w*\s+долг\w*|сложить", re.I)
_WINNER = re.compile(r"победител\w*|кого\s+выбра\w*|кто\s+лучше", re.I)
_FIRST_CHECK = re.compile(
    r"какой\s+факт\b.*(?:важнее|главн\w*)|что\s+проверить\s+в\s+первую\s+очередь", re.I
)
_QUALITY = {
    "financial_balance_mismatch",
    "financial_assets_components_mismatch",
    "financial_liabilities_components_mismatch",
    "enforcement_after_report",
    "report_future",
    "report_stale",
    "registration_after_report",
}
_GAP_TOPICS = {
    "financial_fields_missing",
    "financial_missing",
    "arbitration_history_missing",
    "license_coverage",
    "report_date",
}


def issue_group(fact: ApprovedFact) -> str:
    """Объединить отметку источника и подробности той же темы, не считать их дважды."""

    code = fact.metric or fact.topic
    if (
        code in {"pending_defendant_cases", "arbitration_summary", "arbitration_history_missing"}
        or fact.signal_code == "arbitrationDefendant"
    ):
        return "Суды"
    if code == "enforcement_summary" or fact.signal_code == "executionProceedings":
        return "Взыскания"
    if code in _QUALITY:
        return "Согласованность данных"
    if (
        code in {"financial_loss", "negative_equity", "financial_zero_revenue"}
        or fact.signal_code == "profit"
    ):
        return "Финансы"
    if fact.topic == "attention_signal" and fact.metric not in {"none", "reputation_summary"}:
        return "Отметки в отчёте"
    return fact.topic


def fact_priority(fact: ApprovedFact) -> int:
    """Очередность чтения, не скоринг компании: конкретные обстоятельства до счётчиков."""

    code = fact.metric or fact.topic
    if code == "comparison_enforcement_focus":
        return 0
    if code == "pending_defendant_cases":
        return 0
    if code == "enforcement_summary" and fact.topic == "attention_signal":
        return 1
    if code == "financial_zero_revenue":
        return 1
    if code in {"negative_equity", "financial_loss"}:
        return 2
    if code == "provider_negative_signal":
        return 3
    if code in _QUALITY:
        return 5
    if code == "arbitration_summary":
        return 4
    if fact.topic == "company_status":
        return 8
    if fact.topic in _GAP_TOPICS:
        return 7
    if code == "none":
        return 10
    if fact.topic in {"granular_metric", "bank_signal"}:
        return 12
    if code == "reputation_summary" or fact.topic == "report_age":
        return 30
    return 15


def company_rows(catalog: Mapping[str, ApprovedFact]) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for key, fact in catalog.items():
        if fact.topic.startswith("comparison_"):
            # Групповой вывод может упоминать ИНН, но не принадлежит одной компании.
            continue
        match = _COMPANY.match(fact.claim.text)
        if match:
            rows.setdefault(match["inn"], []).append(key)
    return rows


def select_issues(ids: list[str], catalog: Mapping[str, ApprovedFact], limit: int) -> list[str]:
    """Сохранить разные темы и более позднее значение при историческом убытке/капитале."""

    ordered = sorted(
        ids, key=lambda key: (fact_priority(catalog[key]), -(catalog[key].period or 0))
    )
    selected: list[str] = []
    groups: set[str] = set()
    for key in ordered:
        fact = catalog[key]
        group = issue_group(fact)
        if group in groups or fact.topic in {"report_age", "report_date"}:
            continue
        if len(groups) >= limit:
            break
        groups.add(group)
        selected.append(key)
        if fact.metric in {"financial_loss", "negative_equity"}:
            # Прибыль и капитал — разные показатели; один не должен вытеснять другой.
            companion_metric = (
                "negative_equity" if fact.metric == "financial_loss" else "financial_loss"
            )
            selected.extend(
                other
                for other in ordered
                if catalog[other].metric == companion_metric
                and catalog[other].period == fact.period
            )
        if group in {"Суды", "Взыскания"} and fact.topic == "attention_signal":
            # Конкретная сводка дополняет отметку; это один вопрос для проверки.
            companion = next(
                (
                    other
                    for other in ordered
                    if other != key
                    and issue_group(catalog[other]) == group
                    and catalog[other].topic in {"arbitration_summary", "enforcement_summary"}
                ),
                None,
            )
            if companion:
                if fact.metric == "provider_negative_signal":
                    # В кратком ответе конкретная сводка полезнее повторения отметки
                    # той же темы. Не объявляем сводку причиной отметки источника.
                    selected.remove(key)
                selected.append(companion)
        metric = {"financial_loss": "profit", "negative_equity": "equity"}.get(fact.metric or "")
        if metric:
            newer = [
                other
                for other in ids
                if catalog[other].topic == "granular_metric"
                and catalog[other].metric == metric
                and (catalog[other].period or 0) > (fact.period or 0)
            ]
            if newer:
                selected.append(max(newer, key=lambda other: catalog[other].period or 0))
    return selected or ordered[:1]


def _body(fact: ApprovedFact) -> str:
    return _COMPANY.sub("", fact.claim.text).removeprefix(
        "Отдельный сигнал внимания по данным отчёта:\n"
    )


def _select_gaps(ids: list[str], catalog: Mapping[str, ApprovedFact]) -> list[str]:
    """Разные пробелы, начиная с последнего года, вместо повторения одной метрики за все годы."""

    selected: list[str] = []
    topics: set[str] = set()
    for key in sorted(ids, key=lambda key: -(catalog[key].period or 0)):
        fact = catalog[key]
        is_gap = fact.topic in _GAP_TOPICS - {"report_date"} or (
            fact.topic == "arbitration_summary"
            and _body(fact).startswith("Сводных данных о судебных делах нет.")
        )
        if is_gap and fact.topic not in topics:
            selected.append(key)
            topics.add(fact.topic)
        if len(selected) == 2:
            break
    return selected or [key for key in ids if catalog[key].topic == "report_date"][:1] or ids[:1]


def next_steps(selected: list[str], catalog: Mapping[str, ApprovedFact], deal: DealContext) -> str:
    groups = {issue_group(catalog[key]) for key in selected}
    actions: list[str] = []
    buyer = counterparty_role(deal) == "buyer"
    if buyer:
        actions.append(
            "сопоставьте сумму поставки и срок оплаты с актуальными сведениями "
            "о денежных средствах и обязательствах покупателя"
        )
    if "Суды" in groups:
        actions.append("уточните наличие, предмет и результаты судебных дел")
    if "Взыскания" in groups:
        actions.append("запросите подтверждение текущего состояния исполнительных производств")
    if "Финансы" in groups:
        actions.append("запросите актуальную отчётность и пояснения к отмеченным показателям")
    if "Согласованность данных" in groups:
        actions.append("сверьте противоречивые сведения с исходными документами")
    if "Отметки в отчёте" in groups:
        actions.append("запросите основание отмеченных обстоятельств и проверьте, актуальны ли они")
    if "capability_coverage" in groups:
        actions.append("запросите примеры похожих выполненных проектов и подтверждения заказчиков")
    if groups & {"financial_fields_missing", "financial_missing"}:
        actions.append("запросите отсутствующие финансовые показатели за указанные годы")
    if "license_coverage" in groups:
        actions.append("уточните нужные для вашей задачи разрешения и запросите их подтверждение")
    if not actions:
        actions.append("уточните, чем контрагент подтверждает опыт выполнения похожих обязательств")
    text = " ".join(action[0].upper() + action[1:] + "." for action in actions[:3])
    context = " ".join(filter(None, (deal.goal, deal.role, deal.subject))).casefold()
    if deal.advance and not buyer:
        result = "работ" if any(word in context for word in ("подряд", "работ")) else "результата"
        text += f" Согласуйте этапы оплаты и критерии приёмки {result}."
    # Не задаём повторную анкету в резервном тексте: уточнениями управляет граф с памятью.
    if buyer and not deal.amount:
        text += " Для оценки размера обязательства нужна сумма поставки."
    elif not deal.general_check and not deal.subject:
        text += " Без предмета сделки нельзя проверить, какие разрешения и опыт нужны."
    return text


def safe_analysis_fallback(
    question: str, deal: DealContext, catalog: Mapping[str, ApprovedFact]
) -> ReviewDraft | None:
    """Сохранить смысл задачи, несколько обстоятельств и конкретное действие при отказе LLM."""

    rows = company_rows(catalog)
    if not rows or len(rows) > 6:
        return None
    gaps = bool(_GAPS.search(question))
    capability = bool(_CAPABILITY.search(question))
    bank_reason = needs_bank_reason(question)
    bank_assessment = needs_bank_assessment(question)
    debt_total = bool(_DEBT_TOTAL.search(question))
    capital_status = "банкрот" in question.casefold() and "капитал" in question.casefold()
    first_check = len(rows) == 1 and bool(_FIRST_CHECK.search(question))
    profit_question = bool(
        re.search(r"выручк\w*", question, re.I)
        and re.search(r"прибыл\w*|прибыль\w*", question, re.I)
    )
    payment = next(
        (
            key
            for key, fact in catalog.items()
            if fact.topic == "deal_context" and fact.metric == "payment_effect"
        ),
        None,
    )
    blocks: list[ReviewBlock] = []
    if len(rows) > 1 and re.search(r"кого.*провер|особенно\s+внимательн", question, re.I):
        contrast = next(
            (key for key, fact in catalog.items() if fact.topic == "comparison_enforcement_focus"),
            None,
        )
        if contrast:
            blocks.append(
                ReviewBlock(
                    kind="interpretation", text=catalog[contrast].claim.text, fact_ids=[contrast]
                ),
            )
    if payment and not (
        gaps
        or bank_reason
        or capability
        or debt_total
        or profit_question
        or first_check
        or capital_status
    ):
        blocks.append(
            ReviewBlock(kind="interpretation", text=catalog[payment].claim.text, fact_ids=[payment])
        )
    selected: list[str] = []
    if len(rows) > 1 and _WINNER.search(question):
        limits = [key for key, fact in catalog.items() if fact.topic == "capability_coverage"]
        if not limits:
            return None
        blocks.append(
            ReviewBlock(
                kind="limitation",
                text="По этим отчётам нельзя обоснованно назвать победителя. "
                "Они не подтверждают опыт и качество исполнения именно вашей задачи. "
                "Можно сопоставить обнаруженные обстоятельства и определить, "
                "что уточнить у кандидатов.",
                fact_ids=limits,
            )
        )
    for ids in rows.values():
        if bank_assessment:
            bank_ids = [
                key
                for key in ids
                if catalog[key].topic == "bank_signal"
                and catalog[key].metric in {None, "assessment_limits"}
            ]
            if not any(catalog[key].metric == "assessment_limits" for key in bank_ids):
                return None
            selected.extend(bank_ids)
            blocks.append(
                ReviewBlock(
                    kind="interpretation",
                    text=" ".join(_body(catalog[key]) for key in bank_ids),
                    fact_ids=bank_ids,
                )
            )
        if capital_status:
            boundary = [key for key in ids if catalog[key].metric == "capital_status_boundary"]
            if not boundary:
                return None
            chosen = [max(boundary, key=lambda key: catalog[key].period or 0)]
        elif debt_total:
            chosen = [
                key
                for key in ids
                if catalog[key].topic
                in {
                    "debt_total_unavailable",
                    "enforcement_summary",
                    "financial_missing",
                    "financial_empty",
                }
                or catalog[key].metric == "enforcement_summary"
            ]
            if not any(catalog[key].topic == "debt_total_unavailable" for key in chosen):
                return None
        elif profit_question:
            chosen = [key for key in ids if catalog[key].topic == "profitability_unknown"]
            if not chosen:
                return None
        elif bank_reason:
            chosen = sorted(
                ids,
                key=lambda key: (
                    catalog[key].metric != "reason_unavailable",
                    catalog[key].topic != "bank_signal",
                ),
            )[:1]
        elif capability and any(catalog[key].topic == "capability_coverage" for key in ids):
            chosen = [key for key in ids if catalog[key].topic == "capability_coverage"]
        elif gaps:
            chosen = _select_gaps(ids, catalog)
        else:
            issue_ids = [key for key in ids if catalog[key].topic != "bank_signal"]
            quiet = [key for key in issue_ids if catalog[key].metric == "none"]
            revenue = [
                key
                for key in issue_ids
                if catalog[key].topic == "granular_metric" and catalog[key].metric == "proceeds"
            ]
            if quiet and revenue:
                # Отсутствие отмеченных сигналов не скрываем за списком незаполненных полей.
                # Показываем последний показатель и его ограничение, без гарантии надёжности.
                chosen = [quiet[0], max(revenue, key=lambda key: catalog[key].period or 0)]
                chosen.extend(
                    key for key in issue_ids if catalog[key].topic == "profitability_unknown"
                )
            elif counterparty_role(deal) == "buyer":
                finance = [
                    key
                    for key in issue_ids
                    if catalog[key].metric in {"financial_loss", "negative_equity"}
                ]
                # Убыток за год — основание для вопросов, а не диагноз платёжеспособности.
                chosen = (
                    list(
                        dict.fromkeys(
                            [
                                *select_issues(finance, catalog, 1),
                                *select_issues(issue_ids, catalog, 3),
                            ]
                        )
                    )[:3]
                    if finance
                    else select_issues(issue_ids, catalog, 3)
                )
            else:
                chosen = select_issues(
                    issue_ids, catalog, 2 if bank_assessment or len(rows) > 1 else 3
                )
            if not chosen:
                return None
        if first_check:
            chosen = select_issues(
                [key for key in ids if catalog[key].topic != "bank_signal"], catalog, 1
            )
        selected.extend(chosen)
        match = _COMPANY.match(catalog[chosen[0]].claim.text)
        assert match is not None
        # ИНН нужен для одноимённых компаний в группе, но не в каждом абзаце одной карточки.
        label = match["label"] if len(rows) == 1 else f"{match['label']} (ИНН {match['inn']})"
        if first_check:
            blocks.append(
                ReviewBlock(
                    kind="interpretation",
                    text="Для первоочередной проверки я бы выделил это обстоятельство: "
                    + " ".join(_body(catalog[key]) for key in chosen)
                    + " Это приоритет уточнения, а не доказательство срыва сделки.",
                    fact_ids=chosen,
                )
            )
        elif len(rows) == 1 and not bank_reason:
            # Несколько оснований одной темы — один абзац, без повторов названия компании.
            grouped: dict[str, list[str]] = {}
            for key in chosen:
                grouped.setdefault(issue_group(catalog[key]), []).append(key)
            for position, keys in enumerate(grouped.values()):
                blocks.append(
                    ReviewBlock(
                        kind="limitation" if gaps else "fact",
                        text=(f"{label}. " if position == 0 else "")
                        + " ".join(_body(catalog[key]) for key in keys),
                        fact_ids=keys,
                    )
                )
            if counterparty_role(deal) == "buyer" and any(
                catalog[key].metric == "financial_loss" for key in chosen
            ):
                losses = [key for key in chosen if catalog[key].metric == "financial_loss"]
                blocks.append(
                    ReviewBlock(
                        kind="interpretation",
                        text=(
                            "Убыток за указанный год — обстоятельство для проверки, "
                            "а не доказательство "
                            "неспособности покупателя оплатить вашу поставку. По одному годовому "
                            "показателю нельзя подтвердить оплату в согласованный срок."
                        ),
                        fact_ids=losses,
                    )
                )
        else:
            text = f"{label}: " + " ".join(_body(catalog[key]) for key in chosen)
            blocks.append(ReviewBlock(kind="fact", text=text, fact_ids=chosen))
    # Возраст — известное число, а ограничение — отсутствие сведений после даты отчёта.
    dates = [
        key
        for ids in rows.values()
        for key in ids
        if catalog[key].topic == "report_date" and key not in selected
    ]
    if dates and not bank_reason and len(blocks) < 7:
        if len(rows) == 1:
            text = _body(catalog[dates[0]])
        else:
            text = (
                "Сведения относятся к датам отчётов. Изменения после этих дат здесь не проверены."
            )
        blocks.append(ReviewBlock(kind="limitation", text=text, fact_ids=dates))
    if not bank_reason and not profit_question and not capital_status and len(blocks) < 8:
        terms = [
            key
            for key, fact in catalog.items()
            if fact.topic == "deal_context" and fact.metric in FIELDS
        ]
        support = list(dict.fromkeys([*selected, *terms, *([payment] if payment else [])]))[:32]
        blocks.append(
            ReviewBlock(kind="action", text=next_steps(selected, catalog, deal), fact_ids=support)
        )
    if len(blocks) > 8:
        return None
    return ReviewDraft(blocks=blocks)
