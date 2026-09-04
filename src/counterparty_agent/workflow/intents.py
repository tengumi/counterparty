"""Разбор намерения, группового вопроса и ссылок на участника."""

from __future__ import annotations

import re

from counterparty_agent.models import (
    EntityKind,
    QueryPlan,
)
from counterparty_agent.query import parse_query

_REOPEN_REQUESTS = {
    "карточка",
    "отчет",
    "эта компания",
    "эту компанию",
    "покажи карточку",
    "покажи отчет",
    "покажи полный отчет",
    "покажи эту компанию",
    "покажи текущую компанию",
    "покажи ее карточку",
    "покажи карточку этой компании",
    "обнови карточку",
}


_REOPEN_COMPARISON_REQUESTS = {"сравнение", "покажи сравнение", "обнови сравнение"}


_ADD_COMPARISON = re.compile(
    r"^(?:добавь|добавьте|добавить)(?:\s+ещ[её])?\s+"
    r"(?:(?:к|в)\s+сравнени[ею]\s+)?(?P<entities>.+)$",
    re.IGNORECASE,
)


_GROUP_QUESTION = re.compile(
    r"\b(?:у\s+кого|у\s+всех|по\s+группе|по\s+всем|среди\s+них|"
    r"среди\s+компаний|всех\s+компаний|сравни\s+их|сравни\s+группу)\b"
)


_ORDINAL_NUMBER = re.compile(
    r"\b(?:карточк[ауи]|компани[яию]|контрагент[аы]?|номер)\s*(?:№\s*)?(\d{1,6})(?!\d)"
    r"|№\s*(\d{1,6})(?!\d)|\b(\d{1,6})-(?:ю|я|й|го|ой)\b"
    r"|(?<![\w.,/:-])(\d{1,6})(?![\w./:-]|,\d)"
)


_ORDINAL_WORD = re.compile(
    r"\b(перв|втор|трет|четверт|пят|шест|седьм|восьм|девят|десят)"
    r"(?:ая|ую|ой|ого|ый|ий|ья|ью|ей|ьего|ое|ее)\b"
)


_ORDINAL_POSITIONS = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четверт": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
}


_ORDINAL_CONTEXT_BEFORE = re.compile(
    r"(?:\b(?:у|про|о|об|для|покажи|открой|почему)(?:\s+именно)?|"
    r"карточк[ауи]|компани[яию])\s*$"
)


_ORDINAL_CONTEXT_AFTER = re.compile(r"^\s+(?:компани[яию]|контрагент(?:а|ы)?)\b")


_ORDINAL_NON_COMPANY_VALUE = re.compile(
    r"^\s*(?:[./:-]\s*\d|,\d|[%₽$€]|\d|"
    r"(?:руб\w*|тыс\w*|млн|миллион\w*|млрд|миллиард\w*|копе\w*|"
    r"доллар\w*|евро|процент\w*|квартал\w*|год\w*|месяц\w*|"
    r"полугоди\w*|день|дня|дней|январ\w*|феврал\w*|март\w*|апрел\w*|"
    r"мая|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*|"
    r"иск(?:а|ов)?|суд(?:а|ов)?|судебн(?:ое|ых)|производств\w*|платеж\w*|фактор\w*)\b)"
)


_ORDINAL_SUBJECT_AFTER = re.compile(
    r"^\s+(?:требует\s+внимания|в\s+зоне\s+риска|"
    r"желт\w*|красн\w*|зелен\w*|сер\w*)\b"
)


_ORDINAL_PERIOD = re.compile(
    _ORDINAL_WORD.pattern + r"\s+(?:квартал\w*|год\w*|месяц\w*|полугоди\w*)"
)


_FOCUS_CARD_REQUEST = re.compile(
    r"^(?:(?:покажи|открой)\s+)?карточк[ау]|^подробнее\s+(?:про|о)|"
    r"^(?:покажи|открой)\s+(?:перв|втор|трет|четверт|пят|шест|седьм|восьм|девят|десят)"
)


_QUESTION_START = re.compile(
    r"^(?:а\s+)?(?:сколько|почему|когда|как|насколько|зачем|где|кто|чем|"
    r"како(?:й|е|в|вы|му|м|го)|какая|какую|какие|каких|"
    r"есть(?:\s+ли)?|что|можно\s+ли|стоит\s+ли|поясни|объясни|уточни|"
    r"расскажи|подробнее|(?:за|в)\s+(?:предыдущий|прошлый|[12][0-9]{3}))\b"
)


_CONTEXT_REFERENCE = re.compile(
    r"^(?:у\s+)?(?:ее|его|него|нее|ней|них|их|этой|этого|текущей|выбранной)\b"
)


_TOPIC_REQUEST = re.compile(
    r"^(?:(?:покажи|показать|расскажи|объясни|поясни)\s+)?"
    r"(?:про\s+|о\s+|об\s+)?(?:выручк[ауие]|прибыл[ьи]|убыт(?:ок|ки|ках)|"
    r"финанс(?:ы|ах|ов)|финансовые\s+показатели|риск(?:и|ах|ов)?|"
    r"требует\s+внимания|в\s+зоне\s+риска|"
    r"суд(?:ы|ах|ов)|арбитраж(?:е)?|"
    r"судебные\s+дела|исполнительные\s+производства|взыскания|"
    r"светофор(?:е)?|налог(?:и|ах)|оквэд|лицензи(?:и|ях)|контакты|госзакупки|"
    r"предыдущий\s+год|прошлый\s+год)(?:\s|$)"
)


_QUOTED_NAME = re.compile(r'«[^»]+»|"[^\"]+"|„[^“]+“')


_COMPARISON_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


_COMPARISON_PERIOD = re.compile(
    r'\b(?:за|в|на|до|после|с)\s+["«„]?(?:19|20)\d{2}(?!\d)|'
    r"(?<!\d)(?:19|20)\d{2}\s+год(?:а|у|ы|ов)?\b",
    re.IGNORECASE,
)


_LEGAL_FORM_IN_QUESTION = re.compile(r"\b(?:ооо|пао|нао|зао|оао|ао|ип|ано|гск)\b")


_LEGAL_FORM_BEFORE_YEAR = re.compile(r"\b(?:ооо|пао|нао|зао|оао|ао|ип|ано|гск)\s*$", re.IGNORECASE)


_IMPLICIT_COMPANY_TAIL = re.compile(r"\bу\s+(.+)$")


_IMPLICIT_ABOUT_TAIL = re.compile(r"\bпо\s+(.+)$")


_METRIC_NAMED_TAIL = re.compile(
    r"^(?:а\s+)?(?:какая|какой|какие|каковы|покажи)\s+"
    r"(?:выручка|выручку|прибыль|риски|суды|светофор)\s+([а-яa-z-]+)$"
)


_SAFE_COMPANY_TAIL = re.compile(
    r"(?:нее|него|них|ее|его|компании|контрагента|этой\s+компании|"
    r"этого\s+контрагента|текущей\s+компании|выбранной\s+компании)"
    r"(?:\s+(?:в|за)\s+(?:[12][0-9]{3}|предыдущий|прошлый)(?:\s+год(?:у|а)?)?)?"
)


_SIMILAR_REQUEST = re.compile(r"\b(?:похож(?:ие|их|ую)|аналог(?:и|ов))\b")


_UNSUPPORTED_ANSWER = (
    "Доступны поиск, карточка, вопросы по одной компании и сравнение не менее 2 компаний. "
    "Подбор похожих компаний ещё не подключён. "
    "Введите ИНН, ОГРН или название; для сравнения укажите весь список компаний."
)


_CONFIRM_ANSWER = (
    "Нужно подтвердить компанию. Выберите подходящего кандидата по названию и реквизитам. "
    "Ни один кандидат ещё не выбран автоматически."
)


_COMPARISON_SLOT_MESSAGES = {
    "resolved": "Компания найдена и включена в список.",
    "needs_confirmation": "Подтвердите одну компанию по названию и реквизитам.",
    "not_found": "Компания не найдена в подключённом JSON. Исправьте весь список запроса.",
    "invalid_identifier": "Проверьте формат и контрольную сумму реквизитов в этой позиции.",
    "duplicate": "Эта компания уже встречается в списке. Укажите разные компании.",
}


def _ordinal_positions(normalized: str) -> list[int]:
    text = _QUOTED_NAME.sub(" ", normalized)
    if _LEGAL_FORM_IN_QUESTION.search(text):
        return []
    text = _ORDINAL_PERIOD.sub(" ", text)
    positions: set[int] = set()
    # Единый порядок важен для смешанных ссылок «первая или №2».
    matches = sorted(
        [*_ORDINAL_NUMBER.finditer(text), *_ORDINAL_WORD.finditer(text)],
        key=lambda match: match.start(),
    )
    for match in matches:
        before, after = text[: match.start()], text[match.end() :]
        numeric = match.re is _ORDINAL_NUMBER
        explicit = numeric and match.group(1) is not None
        bare_number = numeric and match.group(4) is not None
        if bare_number and (
            _ORDINAL_NON_COMPANY_VALUE.search(after)
            or re.fullmatch(r"(?:19|20)\d{2}", match.group())
        ):
            continue
        if (
            explicit
            or _ORDINAL_CONTEXT_BEFORE.search(before)
            or _ORDINAL_CONTEXT_AFTER.search(after)
            or _ORDINAL_SUBJECT_AFTER.search(after)
            or (numeric and match.group(2) is not None and not before.strip())
            or (positions and re.search(r"(?:\bи|\bили|,)\s*$", before))
        ):
            position = (
                int(next(value for value in match.groups() if value is not None))
                if numeric
                else _ORDINAL_POSITIONS[match.group(1)]
            )
            positions.add(position)
    return sorted(positions)


def _has_unsupported_comparison_period(question: str, plan: QueryPlan) -> bool:
    """Не заменять указанный пользователем год автоматически выбранным периодом."""

    quotes = list(_QUOTED_NAME.finditer(question))
    for match in _COMPARISON_YEAR.finditer(question):
        if any(quote.start() <= match.start() < quote.end() for quote in quotes):
            continue
        if _LEGAL_FORM_BEFORE_YEAR.search(question[: match.start()]):
            continue
        if not any(item.span_start <= match.start() < item.span_end for item in plan.mentions):
            return True
    return any(
        not any(quote.start() <= match.start() < quote.end() for quote in quotes)
        for match in _COMPARISON_PERIOD.finditer(question)
    )


def _is_question(normalized: str) -> bool:
    return bool(
        _QUESTION_START.search(normalized)
        or _CONTEXT_REFERENCE.search(normalized)
        or _TOPIC_REQUEST.search(normalized)
        or _GROUP_QUESTION.search(normalized)
    )


def _unclear_named_company(normalized: str) -> bool:
    """Не подменять нераспознанное имя в вопросе прежней выбранной компанией."""

    if _LEGAL_FORM_IN_QUESTION.search(normalized):
        return True
    about = _IMPLICIT_ABOUT_TAIL.search(normalized)
    if about is not None:
        target = about.group(1)
        if not (
            _SAFE_COMPANY_TAIL.fullmatch(target)
            or _TOPIC_REQUEST.search(target)
            or re.fullmatch(r"(?:отчету|данным|годам|[12][0-9]{3}(?:\s+год)?)", target)
        ):
            return True
    bare_name = _METRIC_NAMED_TAIL.fullmatch(normalized)
    if bare_name is not None and bare_name.group(1) not in {
        "компании",
        "контрагента",
        "организации",
        "сейчас",
        "доступна",
        "есть",
        "обнаружены",
        "выявлены",
        "видны",
        "основные",
        "известны",
    }:
        return True
    match = _IMPLICIT_COMPANY_TAIL.search(normalized)
    if match is None:
        return False
    # Для «Сколько у неё судов?» объект стоит после местоимения и остаётся темой.
    tail = match.group(1)
    if re.match(r"^(?:нее|него|них|ее|его)\b", tail):
        return False
    return _SAFE_COMPANY_TAIL.fullmatch(tail) is None


def _has_named_target(plan: QueryPlan) -> bool:
    if not plan.mentions:
        return False
    mention = plan.mentions[0]
    if mention.kind is not EntityKind.NAME:
        return True
    if _CONTEXT_REFERENCE.search(mention.normalized_value):
        return False
    if _TOPIC_REQUEST.search(mention.normalized_value):
        return False
    return mention.explicit


def _parse_workflow_query(question: str) -> QueryPlan:
    """Сохранить явное имя в вопросе вроде «Какая выручка у «Компания»?».

    Базовый resolver консервативно пропускает кавычки без поисковой команды.
    Темы отчёта в кавычках не превращаются в названия компаний.
    """

    plan = parse_query(question, preserve_duplicates=True)
    explicit = [item for item in plan.mentions if item.kind is not EntityKind.NAME or item.explicit]
    for match in _QUOTED_NAME.finditer(question):
        if any(item.span_start <= match.start() < item.span_end for item in explicit):
            continue
        quoted_plan = parse_query(match.group())
        for item in quoted_plan.mentions:
            if _TOPIC_REQUEST.search(item.normalized_value):
                continue
            explicit.append(
                item.model_copy(update={"span_start": match.start(), "span_end": match.end()})
            )
    if explicit and any(item not in plan.mentions for item in explicit):
        return plan.model_copy(update={"mentions": tuple(explicit)})
    return plan
