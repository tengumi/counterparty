"""Повторная проверка текста и доказательств ответа."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from counterparty_agent.ai.catalog import build_fact_catalog
from counterparty_agent.ai.comparison_catalog import build_comparison_fact_catalog
from counterparty_agent.ai.contracts import (
    ApprovedFact,
    GroundedAnswer,
    GroundedStatus,
    LlmInvalidResponseError,
    ReviewDraft,
)
from counterparty_agent.ai.prompts import (
    _INSUFFICIENT,
    _INVALID,
    _NOT_CONFIGURED,
    _UNAVAILABLE,
    MAX_ANSWER_FACTS,
)
from counterparty_agent.models import (
    AnalysisResult,
    ComparisonResult,
    CounterpartySnapshot,
)

# Здесь запрещается отрицание наличия целого выбранного отчёта, а не честное
# указание на отсутствующий показатель. Смысл остальных фраз проверяет верификатор.
_COMPANY_NOUN = (
    r"(?:(?:выбранн\w*|эт\w*|данн\w*|перв\w*|втор\w*|треть\w*)\s+)?"
    r"(?:компани\w*|контрагент\w*)"
)
_REPORT_SUBJECT = (
    rf"(?:данны[ех]|сведени[яй]|информаци[яи]|отч[её]т\w*)\s+(?:о|об|по|для)\s+{_COMPANY_NOUN}"
)
_NO_REPORT = re.compile(
    rf"\b(?:нет|отсутству\w*|не\s+предоставлен\w*)\s+(?:никак\w*\s+)?{_REPORT_SUBJECT}"
    rf"|\b{_REPORT_SUBJECT}\s+(?:(?:в\s+отч[её]те|здесь|сейчас)\s+)?"
    r"(?:нет|отсутству\w*|не\s+(?:предоставлен\w*|загружен\w*|представлен\w*|доступн\w*))\b",
    re.I,
)


def validate_report_availability(draft: ReviewDraft, catalog: Mapping[str, ApprovedFact]) -> None:
    """Сведения выбранной компании не могут одновременно означать отсутствие её отчёта."""

    if not any(re.match(r".+? \(ИНН \d{10,12}\):", fact.claim.text) for fact in catalog.values()):
        return
    for index, block in enumerate(draft.blocks):
        if _NO_REPORT.search(block.text):
            raise ValueError(
                f"Блок {index}: отчёт выбранной компании уже передан. "
                "Ответь о ней по каталогу; назови конкретные пробелы, не отрицай наличие отчёта."
            )


def validate_grounded_answer(
    answer: GroundedAnswer, snapshot: CounterpartySnapshot, analysis: AnalysisResult
) -> None:
    """Повторить серверный рендер и отклонить подмену текста, ID или области."""

    catalog = None
    if answer.status == "answered":
        catalog = {item.fact_id: item for item in build_fact_catalog(snapshot, analysis)}
    _validate_catalog_answer(answer, catalog)


def _validate_catalog_answer(
    answer: GroundedAnswer, catalog: dict[str, ApprovedFact] | None
) -> None:
    """Проверить одинаковые строгие ограничения одиночного и группового ответа."""

    if answer.status != "answered":
        allowed = {
            "insufficient_data": (_INSUFFICIENT,),
            "llm_unavailable": (_UNAVAILABLE, _NOT_CONFIGURED),
            "validation_failed": (_INVALID,),
        }
        if answer.claims or answer.fact_ids or answer.answer not in allowed.get(answer.status, ()):
            raise LlmInvalidResponseError("Неподтверждённый ответ в безопасном исходе")
        return
    if (
        catalog is None
        or not answer.used_llm
        or not 1 <= len(answer.fact_ids) <= MAX_ANSWER_FACTS
        or len(set(answer.fact_ids)) != len(answer.fact_ids)
        or any(key not in catalog for key in answer.fact_ids)
    ):
        raise LlmInvalidResponseError("Ответ ссылается на недоступные факты")
    claims = tuple(catalog[key].claim for key in answer.fact_ids)
    if answer.claims != claims or answer.answer != "\n\n".join(claim.text for claim in claims):
        raise LlmInvalidResponseError("Текст ответа не совпадает с подтверждёнными фактами")


def _safe_answer(status: GroundedStatus, *, used_llm: bool, model: str | None) -> GroundedAnswer:
    text = {
        "insufficient_data": _INSUFFICIENT,
        "llm_unavailable": _UNAVAILABLE if used_llm else _NOT_CONFIGURED,
        "validation_failed": _INVALID,
    }[status]
    return GroundedAnswer(status, text, (), (), model, used_llm)


def invalid_grounded_answer(*, used_llm: bool, model: str | None = None) -> GroundedAnswer:
    """Единый безопасный исход для дополнительного валидатора графа."""

    return _safe_answer("validation_failed", used_llm=used_llm, model=model)


def validate_comparison_answer(
    answer: GroundedAnswer,
    snapshots: Sequence[CounterpartySnapshot],
    comparison: ComparisonResult,
) -> None:
    """Проверить групповой текст, позиции и область всех источников повторным рендером."""

    catalog = None
    if answer.status == "answered":
        catalog = {
            item.fact_id: item for item in build_comparison_fact_catalog(snapshots, comparison)
        }
    _validate_catalog_answer(answer, catalog)
