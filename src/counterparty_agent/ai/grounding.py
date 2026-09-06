"""Проверка связей между фактами: наличие чисел не подтверждает сравнение или общий итог."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from counterparty_agent.ai.contracts import ApprovedFact, ReviewBlock, ReviewDraft

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSE = re.compile(r";\s*|,\s*(?:(?:но|однако|а\s+вот|при\s+этом)\s+|(?=если\b))", re.I)
_RISK_PROMISE = re.compile(
    r"\b(?:(?:сниз\w*|снижа\w*|уменьш\w*|исключ\w*|устран\w*)\s+"
    r"(?:\w+\s+){0,3}(?:риск\w*|вероятност\w*)|"
    r"(?:защитит|защитят|защищает|защищают)\s+"
    r"(?:\w+\s+){0,3}(?:деньг\w*|средств\w*|аванс\w*)|"
    r"(?:перенес[её]т|перенесут|переносит|переносят)\s+"
    r"(?:\w+\s+){0,3}риск\w*)\b",
    re.I,
)
_RISK_QUESTION = re.compile(
    r"\b(?:сниз\w*|снижа\w*|уменьш\w*|исключ\w*|устран\w*|"
    r"защитит|защитят|защищает|защищают|"
    r"перенес[её]т|перенесут|переносит|переносят)\s+ли\b",
    re.I,
)
_RISK_DISCUSSION = re.compile(
    r"\b(?:обсуд\w*|оценить|оцените|выясн\w*|уточн\w*)\b[^.!?;]{0,120}"
    r"\bмог(?:ли|ла|ло)?\s+бы\s+(?:помочь\s+)?"
    r"(?P<effect>(?:снизить|снижать|уменьшить|уменьшать|исключить|устранить)\s+"
    r"(?:\w+\s+){0,3}(?:риск\w*|вероятност\w*))\b",
    re.I,
)
_MONEY = re.compile(
    r"\b(?:сумм\w*|аванс\w*|предоплат\w*|выручк\w*|прибыл\w*|убыт\w*|"
    r"актив(?:ы|ов|ам|ами|ах|а|у|ом|е)?|капитал(?:а|у|ом|е)?|"
    r"долг(?:а|у|ом|е|и|ов|ам|ами|ах)?|стоимост\w*|цен(?:а|ы|е|у|ой|ам|ами|ах)|"
    r"сделк\w*|рубл\w*|денежн\w*|обязательств\w*|RUB)\b|₽",
    re.I,
)
_MAGNITUDE = re.compile(
    r"\b(?:небольш\w*|больш\w*|маленьк\w*|невелик\w*|крупн\w*|незначительн\w*|"
    r"некритичн\w*|существенн\w*|значительн\w*|посильн\w*|сопоставим\w*|"
    r"умеренн\w*|необременительн\w*|минимальн\w*|максимальн\w*)\b",
    re.I,
)
_RELATION = re.compile(
    r"\b(?:по\s+сравнени\w*(?:\s+с)?|относительно|превыша\w*|меньше|больше|ниже|выше)\b|"
    r"\b(?:дол[яюеи]|част[ьи])\s+(?:от\s+)?(?:актив\w*|выручк\w*|капитал\w*|сумм\w*)\b|"
    r"\bсоставля\w*[^.!?;]{0,50}(?:%|процент\w*|долю\b|часть\b)|"
    r"\bв\s+\d+(?:[.,]\d+)?\s+раз\w*\b",
    re.I,
)
_BOUNDARY = re.compile(
    r"\b(?:нельзя|невозможно|не\s+уда[её]тся)\s+(?:сравн\w*|сопостав\w*|оцен\w*|"
    r"назва\w*|счита\w*|подтверд\w*|определ\w*|сказа\w*|утвержда\w*)\b|"
    r"\bне\s+(?:гарантир\w*|доказыва\w*|означа\w*|подтвержд\w*|равн\w*)\b|"
    r"\bнедостаточно\s+(?:данных|сведений|оснований)\b|"
    r"\bнет\s+(?:данных|оснований)\b",
    re.I,
)
_REQUEST = re.compile(
    r"^(?:(?:сначала|затем|пожалуйста)\s+)?(?:сопоставьте|сравните|оцените|уточните),?\s+"
    r"(?:сумм\w*|соотношени\w*|размер\w*|насколько\b|можно\s+ли\b)|"
    r"^(?:насколько|можно\s+ли|есть\s+ли\s+основания)\b",
    re.I,
)
_REFERENCE = re.compile(r"^(?:он[ао]?|это|такой\s+(?:размер|объ[её]м))\b", re.I)
_CHECK_PRIORITY = re.compile(
    r"\b(?:(?:существенн\w*|значительн\w*)\s+(?:основан\w*|обстоятельств\w*|"
    r"сигнал\w*|вопрос\w*|ограничени\w*|различи\w*|повод\w*)\b|"
    r"существенно(?=\s+(?:(?:сначала|прежде\s+всего)\s+)?"
    r"(?:выяснить|проверить|уточнить)\b))",
    re.I,
)
_PAYMENT_TARGET = (
    r"(?:аванс\w*|предоплат\w*|(?:сумм\w*|размер\w*)\s+"
    r"(?:аванс\w*|предоплат\w*|сделк\w*))"
)
_PAYMENT_SIZE = (
    r"(?:меньш\w*|больш\w*|небольш\w*|маленьк\w*|умеренн\w*|"
    r"незначительн\w*|минимальн\w*|ниже|выше)"
)
_PAYMENT_OPTION = re.compile(
    r"\b(?:обсудите|предложите|рассмотрите|согласуйте|"
    r"можно\s+(?:обсудить|предложить|рассмотреть|согласовать))\s+"
    r"(?:(?:вариант|условия)\s+с\s+)?(?:более\s+|менее\s+)?"
    rf"(?:{_PAYMENT_SIZE}\s+{_PAYMENT_TARGET}|{_PAYMENT_TARGET}\s+{_PAYMENT_SIZE})\b",
    re.I,
)
_FINANCIAL_OPERAND = re.compile(
    r"^\s*(?:(?:чем|относительно)\s+)?(?:актив(?:ы|ов|а)?|капитал\w*|выручк\w*|"
    r"прибыл\w*|долг\w*|обязательств\w*)\b",
    re.I,
)
_OPERAND_LINK_WORD = re.compile(
    r"(?:компани\w*|контрагент\w*|поставщик\w*|подрядчик\w*|покупател\w*|"
    r"эт\w*|так\w*|его|е[её]|их|для|за|год\w*|период\w*|"
    r"явля\w*|счита\w*|остал\w*|оста[её]тся|оказал\w*|"
    r"текущ\w*|общ\w*|собственн\w*|заявленн\w*|указанн\w*)",
    re.I,
)
_FINISHED_DEFENDANT = re.compile(
    r"\bЗаверш[её]н\w*\s+дел[^.!?\n]{0,150}\bответчик\w*\s*:\s*(\d+)\b",
    re.I,
)
_UNKNOWN_PENDING = re.compile(
    r"\bНезаверш[её]н\w*\s+дел\s+в\s+роли\s+ответчик\w*\s*:\s*нет\s+данных",
    re.I,
)
_TOTAL_CASES = re.compile(r"\bСудебных\s+дел\s+в\s+отч[её]те\s*:\s*(\d+)\b", re.I)
_TOTAL_DEFENDANT = re.compile(
    r"\b(?:Всего|Общее\s+(?:число|количество))\s+дел\s+в\s+роли\s+"
    r"ответчик\w*\s*:\s*(\d+)\b",
    re.I,
)
_SMALL_ROLE_COUNTS = {
    form: str(number)
    for number, forms in enumerate(
        (
            "один одна одно одну одного одной одному одним одном",
            "два две двух двум двумя",
            "три трёх трех трём трем тремя",
            "четыре четырёх четырех четырём четырем четырьмя",
            "пять пяти пятью",
            "шесть шести шестью",
            "семь семи семью",
            "восемь восьми восемью восьмью",
            "девять девяти девятью",
            "десять десяти десятью",
        ),
        start=1,
    )
    for form in forms.split()
}
_ROLE_NUMBER = r"(?:\d+|" + "|".join(_SMALL_ROLE_COUNTS) + ")"
_ROLE_COUNT = re.compile(
    rf"\bответчик\w*\s*(?:[:—–-]|(?:всего|в|по))?\s*({_ROLE_NUMBER})\b|"
    rf"\b({_ROLE_NUMBER})\s+(?:(?:судебн\w*|арбитражн\w*|"
    r"заверш[её]н\w*|законч[её]н\w*|рассмотренн\w*)\s+){0,3}"
    r"(?:дел\w*|раз\w*)\s*,?\s*"
    r"(?:(?:где|в\s+которых)\s+)?(?:с\s+)?"
    r"(?:(?:компани\w*|контрагент\w*|она)\s+)?"
    r"(?:(?:выступа\w*|явля\w*|был[аи]?)\s+)?"
    r"(?:(?:в\s+роли|как)\s+)?ответчик\w*\b|"
    rf"\b({_ROLE_NUMBER})\b\s*[—–-]?\s*(?:в\s+роли|как)\s+ответчик\w*\b",
    re.I,
)
_FINISHED = re.compile(r"\b(?:заверш[её]н\w*|законч[её]н\w*|рассмотренн\w*)\b", re.I)
_REFUSAL_EVENT = re.compile(
    r"\b(?:отказал[аи]?(?:сь|ся)?|отказались|отказали|отказан[оаы]?|"
    r"отказывал[аи]?(?:сь|ся)?|отказывались|отказывали|"
    r"отказывается|отказываются|откажется|откажутся|откажет|откажут|"
    r"скрыва(?:ет|ют|л[аи]?|ли)|скры(?:л[аи]?|ли|т[аыо]?))\b|"
    r"\bотказ\w*[^.!?;,]{0,35}\b(?:не\s+было|нет|не\s+получен\w*|получен\w*|"
    r"состоял\w*|произош\w*)\b",
    re.I,
)
_DOCUMENT_EVENT = re.compile(
    r"\b(?:предостав(?:ил[аи]?|или|лен[аыо]?|ляет|ляют|ит|ят)|"
    r"представ(?:ил[аи]?|или|лен[аыо]?)|переда(?:л[аи]?|ли|н[аыо]?)|"
    r"присла(?:л[аи]?|ли|н[аыо]?)|получен[аыо]?|"
    r"скрыва(?:ет|ют|л[аи]?|ли)|скры(?:л[аи]?|ли|т[аыо]?))\b",
    re.I,
)
_DOCUMENT_CONTEXT = re.compile(
    r"\b(?:документ\w*|отч[её]т\w*|сведени\w*|подтверждени\w*|данн\w*|"
    r"информаци\w*|бумаг\w*|письм\w*|проверк\w*|копи\w*)\b",
    re.I,
)
_CONDITION = re.compile(
    r"\b(?:если|в\s+случае|при\s+(?:отказе|непредоставлении)|допустим|предположим)\b",
    re.I,
)
_EVENT_BOUNDARY = re.compile(
    r"\b(?:неизвестн\w*|неясн\w*)\b|\bнет\s+(?:данных|сведений|подтверждения)\b|"
    r"\bнельзя\s+(?:утверждать|сказать|считать)\b|"
    r"\bне\s+(?:утверждаем|подтвержден\w*|подтвержд[аё]тся)\b",
    re.I,
)


def _normalized(text: str) -> str:
    return " ".join(re.sub(r"[^\w%]+", " ", text.casefold().replace("ё", "е")).split())


def _without_payment_options(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return match.group() if _FINANCIAL_OPERAND.match(text[match.end() :]) else ""

    return _PAYMENT_OPTION.sub(replace, text)


def _has_money_operand(text: str, *, context_has_money: bool) -> bool:
    """Связать оценку с суммой, а не с любым упоминанием оплаты в предложении."""

    def linked(start: int, end: int) -> bool:
        gap = text[start:end]
        if len(gap) > 80 or re.search(r"[.!?;,]", re.sub(r"(?<=\d)[.,](?=\d)", "", gap)):
            return False
        words = re.findall(r"[^\W\d_]+", gap)
        # Между показателем и оценкой допустимы его владелец, период и связка.
        # Произвольное действие вроде «запросить ... до аванса» их не связывает.
        return len(words) <= 5 and all(
            _OPERAND_LINK_WORD.fullmatch(word) or word[0].isupper() for word in words
        )

    operands = list(_MONEY.finditer(text))
    if context_has_money and (reference := _REFERENCE.match(text)):
        operands.append(reference)
    for assessment in (*_MAGNITUDE.finditer(text), *_RELATION.finditer(text)):
        for operand in operands:
            if operand.end() <= assessment.start():
                if linked(operand.end(), assessment.start()):
                    return True
            elif assessment.end() <= operand.start():
                if linked(assessment.end(), operand.start()):
                    return True
            else:
                # «Доля активов» уже содержит денежный операнд внутри отношения.
                return True
    return False


def _money_assertions(text: str, *, context_has_money: bool = False) -> list[str]:
    """Не путать оценку суммы с просьбой её проверить или границей такого вывода."""

    assertions = []
    for sentence in _SENTENCE.split(text):
        for clause in _CLAUSE.split(sentence):
            clause = clause.strip()
            # «Существенно выяснить» оценивает важность проверки, не величину суммы.
            # Остальные оценки и соотношения в том же абзаце остаются под проверкой.
            assessed = _CHECK_PRIORITY.sub("", clause)
            # «Обсудите меньший аванс» меняет возможное условие, не оценивает компанию.
            # Удаляется только предложенный вариант, а не весь action-блок: пояснение
            # «долг небольшой относительно активов» после него всё равно проверяется.
            assessed = _without_payment_options(assessed)
            if not _has_money_operand(assessed, context_has_money=context_has_money):
                continue
            if _BOUNDARY.search(clause) or _REQUEST.search(clause):
                continue
            assertions.append(clause)
    return assertions


def validate_relational_grounding(
    block: ReviewBlock, facts: Sequence[ApprovedFact], *, block_index: int = 0
) -> None:
    """Дополнительный локальный барьер; семантическая проверка всего ответа сохраняется."""

    sources = [fact.claim.text for fact in facts]
    for sentence in _SENTENCE.split(block.text):
        for clause in _CLAUSE.split(sentence):
            questions = {match.start() for match in _RISK_QUESTION.finditer(clause)}
            discussions = [match.span("effect") for match in _RISK_DISCUSSION.finditer(clause)]
            promises = [
                match
                for match in _RISK_PROMISE.finditer(clause)
                if match.start() not in questions
                and not any(
                    start <= match.start() and match.end() <= end for start, end in discussions
                )
            ]
            if not promises or _BOUNDARY.search(clause):
                continue
            if not any(_normalized(clause) in _normalized(source) for source in sources):
                raise ValueError(
                    f"Блок {block_index}: результат меры не подтверждён источниками. "
                    "Предложи обсудить вариант условий, не обещай защиту денег, перенос "
                    "рисков или снижение вероятности потери денег и неисполнения сделки."
                )
    money_context = any(_MONEY.search(text) for text in sources)
    approved = [
        _normalized(clause)
        for text in sources
        for clause in _money_assertions(text, context_has_money=money_context)
    ]
    for clause in _money_assertions(block.text, context_has_money=money_context):
        if not any(_normalized(clause) in source for source in approved):
            raise ValueError(
                f"Блок {block_index}: денежное сравнение или оценка величины не подтверждены "
                "отдельным фактом. Наличие обеих сумм не разрешает называть одну небольшой "
                "относительно другой, считать долю или делать вывод о посильности сделки."
            )

    # Общий итог всех ролей и число завершённых дел не становятся итогом ответчика.
    finished = {
        match.group(1)
        for text in sources
        if _UNKNOWN_PENDING.search(text)
        for match in _FINISHED_DEFENDANT.finditer(text)
    }
    completed = {
        match.group(1) for text in sources for match in _FINISHED_DEFENDANT.finditer(text)
    }
    totals = {match.group(1) for text in sources for match in _TOTAL_CASES.finditer(text)}
    role_totals = {
        match.group(1) for text in sources for match in _TOTAL_DEFENDANT.finditer(text)
    }
    if not finished and not totals:
        return
    for sentence in _SENTENCE.split(block.text):
        if _BOUNDARY.search(sentence):
            continue
        for match in _ROLE_COUNT.finditer(sentence):
            count = next(group for group in match.groups() if group is not None)
            # Словесное количество проверяется только здесь, не в денежных вычислениях.
            count = _SMALL_ROLE_COUNTS.get(count.casefold(), count)
            qualified = bool(
                _FINISHED.search(match.group())
                or _FINISHED.match(sentence[match.end() :].lstrip())
                or any(
                    match.start() <= item.start(1) < match.end()
                    for item in _FINISHED_DEFENDANT.finditer(sentence)
                )
            )
            if (
                count in totals
                and count not in role_totals
                and not (qualified and count in completed)
            ):
                raise ValueError(
                    f"Блок {block_index}: общий итог судебных дел подменён числом дел "
                    "в роли ответчика. Сохрани общий итог отдельно; число дел в конкретной "
                    "роли требует собственного основания."
                )
            if qualified or count in role_totals:
                continue
            if count in finished:
                raise ValueError(
                    f"Блок {block_index}: число завершённых дел ответчика подменено общим "
                    "числом дел в этой роли. Сохрани слово «завершённых»; незавершённые "
                    "дела неизвестны, а не равны нулю."
                )


def _scenario_events(text: str) -> list[str]:
    events = []
    for sentence in _SENTENCE.split(text):
        boundary = _EVENT_BOUNDARY.search(sentence)
        # «Неизвестно, почему отказали» уже предполагает отказ, неизвестна лишь причина.
        uncertain = bool(boundary) and not re.search(r"\b(?:почему|причин\w*)\b", sentence, re.I)
        if uncertain:
            continue
        for clause in re.split(r"[,;]\s*", sentence):
            clause = clause.strip()
            event = _REFUSAL_EVENT.search(clause)
            if event is None and _DOCUMENT_CONTEXT.search(clause):
                event = _DOCUMENT_EVENT.search(clause)
            if event is None:
                continue
            condition = _CONDITION.search(clause)
            if condition is not None and condition.start() < event.start():
                continue
            if re.search(r"\bли\b", clause[event.end() : event.end() + 8], re.I):
                continue
            events.append(clause)
    return events


def validate_scenario_grounding(draft: ReviewDraft, catalog: Mapping[str, ApprovedFact]) -> None:
    """Гипотетический отказ не доказывает ни произошедшего отказа, ни его отсутствия."""

    for index, block in enumerate(draft.blocks):
        source_events = [
            _normalized(event)
            for key in block.fact_ids
            for event in _scenario_events(catalog[key].claim.text)
        ]
        for event in _scenario_events(block.text):
            if not any(_normalized(event) in source for source in source_events):
                raise ValueError(
                    f"Блок {index}: гипотеза не подтверждает факт отказа, предоставления "
                    "или сокрытия документов — включая утверждение, что события не было. "
                    "Сохрани условную формулировку «если» и предложи следующий шаг, "
                    "не приписывая контрагенту уже совершённые действия."
                )
