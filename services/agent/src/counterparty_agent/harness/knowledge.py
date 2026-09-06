"""Versioned domain-knowledge reference the agent must be given (Specs 04 §6).

The reference is a small, reviewed corpus kept in the repository: every entry
carries a ``version``, a ``source`` category (a real case, a checked Q&A, or a
verified reference) and at least one worked example of the framing it protects.
The model reads the fragments relevant to a question through the plain keyword
:func:`lookup` below -- an internal lookup, not a vector search -- and the full
compact list is always rendered into the system prompt as the standing domain
notes.

Legal definitions and numeric thresholds are deliberately absent: Specs 04 §6
forbids adding them without a checked source and a date.
"""

from dataclasses import dataclass
from typing import Literal

KnowledgeSource = Literal["case", "qa", "verified_reference"]

REFERENCE_VERSION = 1
"""Bump on any change to :data:`REFERENCE`; a test pins it so an edit is visible."""


@dataclass(frozen=True, slots=True)
class KnowledgeExample:
    """One worked example: the signal, the correct reading, the mistake to avoid."""

    signal: str
    correct: str
    incorrect: str


@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    """One reviewed piece of domain knowledge with its provenance and tests."""

    id: str
    version: int
    source: KnowledgeSource
    topics: tuple[str, ...]
    statement: str
    examples: tuple[KnowledgeExample, ...]


REFERENCE: tuple[KnowledgeEntry, ...] = (
    KnowledgeEntry(
        id="okved_mass",
        version=1,
        source="qa",
        topics=("оквэд", "вид деятельности", "массов"),
        statement=(
            "Коды ОКВЭД называются с описаниями. «Массовый ОКВЭД» — признак того, что "
            "вид деятельности часто встречается у проблемных компаний, а не порог по "
            "числу кодов у одной компании: это повод уточнить, не доказательство нарушения."
        ),
        examples=(
            KnowledgeExample(
                signal="У компании семь кодов ОКВЭД, два помечены как массовые.",
                correct="Отметить как повод уточнить профиль деятельности.",
                incorrect="Записать «много массовых ОКВЭД» в нарушения.",
            ),
        ),
    ),
    KnowledgeEntry(
        id="bank_traffic_light",
        version=1,
        source="verified_reference",
        topics=("светофор", "комплаенс", "капитал", "состоятельность"),
        statement=(
            "Банковский светофор — комплаенс-оценка. Он может быть зелёным при "
            "отрицательном капитале; финансовая состоятельность оценивается отдельно."
        ),
        examples=(
            KnowledgeExample(
                signal="Светофор зелёный, капитал по последнему периоду отрицательный.",
                correct="Светофор — про комплаенс; отдельно отметить отрицательный капитал.",
                incorrect="Вывести из зелёного светофора финансовую устойчивость.",
            ),
        ),
    ),
    KnowledgeEntry(
        id="zsk_vs_bank_risk",
        version=1,
        source="verified_reference",
        topics=("зск", "светофор", "риск"),
        statement=(
            "Оценка ЗСК и банковский риск — разные сигналы. Сырое значение YELLOW/RED "
            "ЗСК сохраняется как есть, отображение — по отдельной подтверждённой политике, "
            "закрытая методика не объясняется."
        ),
        examples=(
            KnowledgeExample(
                signal="ЗСК YELLOW, банковский светофор зелёный.",
                correct="Показать сырое ЗСК и не смешивать его с банковской оценкой.",
                incorrect="Свести ЗСК и светофор к одному «уровню риска».",
            ),
        ),
    ),
    KnowledgeEntry(
        id="enforcement_proceedings",
        version=1,
        source="case",
        topics=("производств", "исполнительн", "пристав", "долг"),
        statement=(
            "Исполнительное производство даже на небольшую сумму не является "
            "автоматическим запретом: важны сумма, давность, масштаб, активность и "
            "задача сделки. Не делить на нулевые или отрицательные чистые активы и не "
            "выдавать необычный процент за норму."
        ),
        examples=(
            KnowledgeExample(
                signal="Одно производство на 15 тыс. ₽, закрыто два года назад.",
                correct="Отметить малую сумму и давность, оценить в контексте сделки.",
                incorrect="Назвать любое исполнительное производство стоп-фактором.",
            ),
        ),
    ),
    KnowledgeEntry(
        id="fns_block",
        version=1,
        source="case",
        topics=("фнс", "блокировк", "счёт", "счет"),
        statement=(
            "Блокировка ФНС — отрицательный фактор, но известная кратковременная "
            "блокировка не доказывает невозможность любых платежей. Из флага без дат "
            "длительность не выводится."
        ),
        examples=(
            KnowledgeExample(
                signal="Флаг «была блокировка ФНС» без дат начала и снятия.",
                correct="Назвать отрицательным фактором и уточнить период.",
                incorrect="Заключить, что компания не может проводить платежи.",
            ),
        ),
    ),
    KnowledgeEntry(
        id="relocation_vs_capital_decrease",
        version=1,
        source="qa",
        topics=("переезд", "адрес", "уставн", "капитал", "уменьшен"),
        statement=(
            "Переезд и уменьшение уставного капитала — разные изменения. Проверить "
            "контекст каждого и не называть их банкротством."
        ),
        examples=(
            KnowledgeExample(
                signal="За год сменился адрес и уменьшен уставный капитал.",
                correct="Рассмотреть два изменения отдельно и запросить контекст.",
                incorrect="Свести оба факта к «признакам банкротства».",
            ),
        ),
    ),
    KnowledgeEntry(
        id="no_universal_signals",
        version=1,
        source="qa",
        topics=("аванс", "отсрочк", "поставщик", "покупатель", "сигнал"),
        statement=(
            "Универсальных 3–5 решающих сигналов нет. Поставщик, получающий аванс, и "
            "покупатель с отсрочкой требуют разных акцентов проверки."
        ),
        examples=(
            KnowledgeExample(
                signal="Сделка: контрагент — поставщик, просит аванс 80%.",
                correct="Сместить акцент на способность выполнить обязательство и вернуть аванс.",
                incorrect="Применить один общий чек-лист «красных флагов» к любой роли.",
            ),
        ),
    ),
    KnowledgeEntry(
        id="annual_report_cash",
        version=1,
        source="verified_reference",
        topics=("отчётност", "отчетност", "остаток", "денежные средства", "пассив", "долг"),
        statement=(
            "Данные о деньгах из годовой отчётности не означают текущий остаток на "
            "счёте. Итог пассива баланса не равен долгу."
        ),
        examples=(
            KnowledgeExample(
                signal="В отчёте «денежные средства» 43 тыс. ₽ на конец года.",
                correct="Назвать это значением из годовой отчётности, не текущим остатком.",
                incorrect="Утверждать, что сейчас на счёте компании 43 тыс. ₽.",
            ),
        ),
    ),
    KnowledgeEntry(
        id="counts_vs_performance",
        version=1,
        source="case",
        topics=("закупк", "контракт", "арбитраж", "спор"),
        statement=(
            "Число закупок или контрактов не доказывает их успешное исполнение. "
            "Арбитражный агрегат не раскрывает предмет спора."
        ),
        examples=(
            KnowledgeExample(
                signal="120 контрактов в реестре, три арбитражных дела как ответчик.",
                correct="Не выводить из количества исполнение; по спорам запросить предмет.",
                incorrect="Считать большое число контрактов подтверждением надёжности.",
            ),
        ),
    ),
)


def lookup(text: str, *, limit: int = 4) -> tuple[KnowledgeEntry, ...]:
    """Return the reference entries whose topics the text mentions, best first.

    A plain case-insensitive substring match over each entry's ``topics``; an
    entry that matches more distinct topics ranks higher. Specs 04 §6 states a
    vector search is not required, and this stays deterministic and explainable.
    """
    haystack = text.casefold()
    scored = [
        (sum(1 for topic in entry.topics if topic in haystack), index, entry)
        for index, entry in enumerate(REFERENCE)
    ]
    hits = sorted(
        (item for item in scored if item[0] > 0),
        key=lambda item: (-item[0], item[1]),
    )
    return tuple(entry for _, _, entry in hits[:limit])


def render_reference(entries: tuple[KnowledgeEntry, ...] = REFERENCE) -> str:
    """Render the whole reference as the standing domain-notes block."""
    lines = [f"Предметные оговорки (Specs 04 §6, справочник v{REFERENCE_VERSION}):"]
    lines.extend(f"- {entry.statement}" for entry in entries)
    return "\n".join(lines)


def render_relevant(entries: tuple[KnowledgeEntry, ...]) -> str:
    """Render the fragments selected for one question, with a worked example.

    Empty when nothing matched, so the caller adds no empty section.
    """
    if not entries:
        return ""
    lines = ["## Релевантные оговорки предметной области"]
    for entry in entries:
        lines.append(f"- {entry.statement}")
        example = entry.examples[0]
        lines.append(f"  Верно: {example.correct}")
        lines.append(f"  Ошибка: {example.incorrect}")
    return "\n".join(lines)
