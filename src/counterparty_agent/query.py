"""Детерминированный разбор запроса и разрешение упоминаний контрагентов."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from counterparty_agent.data.identifiers import (
    company_core_name,
    company_legal_form,
    is_valid_inn,
    is_valid_ogrn,
    normalize_company_name,
    normalize_identifier,
)
from counterparty_agent.data.repository import CounterpartySource
from counterparty_agent.models import (
    EntityKind,
    EntityMention,
    QueryIntent,
    QueryPlan,
    QueryResolution,
    ResolutionResult,
    ResolutionStatus,
)

_LEGAL_FORM_PATTERN = (
    r"(?:общество с ограниченной ответственностью|"
    r"публичное акционерное общество|непубличное акционерное общество|"
    r"акционерное общество|индивидуальный предприниматель|"
    r"автономная некоммерческая организация|гаражно[- ]строительный кооператив|"
    r"закрытое акционерное общество|открытое акционерное общество|"
    r"ассоциация|ООО|ПАО|НАО|АО|ИП|ЗАО|ОАО|АНО|ГСК)"
)
_ENTITY_START_PATTERN = rf"(?:{_LEGAL_FORM_PATTERN}|ИНН|ОГРН(?:ИП)?|[0-9]{{10,15}})"
_LABELED_IDENTIFIER_RE = re.compile(
    r"(?P<label>ОГРНИП|ОГРН|ИНН)\s*(?:№|#|:|=|-)?\s*"
    r"(?P<value>[0-9](?:[0-9 -]*[0-9])?)",
    re.IGNORECASE,
)
_UNLABELED_IDENTIFIER_RE = re.compile(
    r"(?<![0-9])(?P<value>[0-9]{15}|[0-9]{13}|[0-9]{12}|[0-9]{10})(?![0-9])"
)
_QUOTED_NAME_RE = re.compile(r"«(?P<angle>[^»]+)»|\"(?P<double>[^\"]+)\"|„(?P<low>[^“]+)“")
_LEGAL_FORM_BEFORE_QUOTE_RE = re.compile(
    rf"(?P<form>{_LEGAL_FORM_PATTERN})\s*$",
    re.IGNORECASE,
)
_COMPANY_MARKER_BEFORE_QUOTE_RE = re.compile(
    r"(?:контрагент(?:а|е|ом)?|компани(?:ю|и|я|ей)|"
    r"организаци(?:ю|и|я|ей))\s*$",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(
    r"\b(?:сравн(?:и|ить|ите)|сопостав(?:ь|ьте|ить)|против)\b",
    re.IGNORECASE,
)
_COMMAND_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"сравн(?:и|ить|ите)|сопостав(?:ь|ьте|ить)|"
    r"провер(?:ь|ьте|ить)|най(?:ди|дите|ти)|"
    r"проанализир(?:уй|уйте|овать)|"
    r"(?:покажи|покажите|показать)(?:\s+отч[её]т)?(?:\s+по)?|"
    r"что\s+известно\s+(?:об|о)\b|"
    r"какие\s+риски\s+(?:у|есть\s+у)|"
    r"расскажи(?:те)?\s+(?:об|о)\b"
    r")\s*[:—-]?\s*",
    re.IGNORECASE,
)
_OBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:контрагент(?:а|е|ом)?|компани(?:ю|и|я|ей)|"
    r"организаци(?:ю|и|я|ей))\s*[:—-]?\s*",
    re.IGNORECASE,
)
_COMPARISON_SEPARATOR_RE = re.compile(
    rf"[;\r\n]+\s*(?={_ENTITY_START_PATTERN}\b)|"
    rf"\s+(?:и|с|против)\s+(?={_ENTITY_START_PATTERN}\b)|"
    rf",\s*(?={_ENTITY_START_PATTERN}\b)",
    re.IGNORECASE,
)
_TRAILING_CLAUSE_RE = re.compile(
    rf"[;\r\n]+(?!\s*{_ENTITY_START_PATTERN}\b).*$",
    re.IGNORECASE | re.DOTALL,
)
_ENTITY_CONNECTOR_BEFORE_QUOTE_RE = re.compile(
    r"(?:\bи\b|\bс\b|\bпротив\b|[;,])\s*$",
    re.IGNORECASE,
)
_INSTRUCTION_ONLY = {
    "проверь",
    "проверить",
    "найди",
    "найти",
    "покажи отчет",
    "сравни",
    "сравнить",
    "компания",
    "организация",
    "контрагент",
    "какие риски",
    "что известно",
}
_REPORT_TOPIC_TERMS = {
    "арбитраж",
    "выручка",
    "выручку",
    "госзакупки",
    "исполнительные производства",
    "контакты",
    "лицензии",
    "налоги",
    "оквэд",
    "прибыль",
    "риски",
    "светофор",
    "суды",
    "судебные дела",
    "финансы",
}


class QueryParseError(ValueError):
    """Безопасная ошибка пустого или неподдерживаемого входа."""


@dataclass(frozen=True, slots=True)
class _ParsedMention:
    kind: EntityKind
    raw_text: str
    normalized_value: str
    checksum_valid: bool | None
    span_start: int
    span_end: int
    explicit: bool


def parse_query(text: str, *, preserve_duplicates: bool = False) -> QueryPlan:
    """Извлечь сущности без LLM; для группового UI сохранить повторные позиции."""

    normalized_text = unicodedata.normalize("NFKC", text).strip()
    if not normalized_text:
        raise QueryParseError("Запрос не должен быть пустым")

    parsed: list[_ParsedMention] = []
    occupied_spans: list[tuple[int, int]] = []
    compare_requested = bool(_COMPARE_RE.search(normalized_text))

    for match in _LABELED_IDENTIFIER_RE.finditer(normalized_text):
        label = match.group("label").casefold()
        identifier = normalize_identifier(match.group("value"))
        kind = EntityKind.INN if label == "инн" else EntityKind.OGRN
        parsed.append(
            _ParsedMention(
                kind=kind,
                raw_text=match.group(0),
                normalized_value=identifier,
                checksum_valid=_identifier_is_valid(kind, identifier),
                span_start=match.start(),
                span_end=match.end(),
                explicit=True,
            )
        )
        occupied_spans.append((match.start(), match.end()))

    for match in _UNLABELED_IDENTIFIER_RE.finditer(normalized_text):
        if _overlaps(match.start(), match.end(), occupied_spans):
            continue
        identifier = match.group("value")
        kind = EntityKind.INN if len(identifier) in {10, 12} else EntityKind.OGRN
        parsed.append(
            _ParsedMention(
                kind=kind,
                raw_text=identifier,
                normalized_value=identifier,
                checksum_valid=_identifier_is_valid(kind, identifier),
                span_start=match.start(),
                span_end=match.end(),
                explicit=False,
            )
        )
        occupied_spans.append((match.start(), match.end()))

    for match in _QUOTED_NAME_RE.finditer(normalized_text):
        form_match = _LEGAL_FORM_BEFORE_QUOTE_RE.search(normalized_text[: match.start()])
        raw_name = next(group for group in match.groups() if group is not None).strip()
        has_company_marker = bool(
            _COMPANY_MARKER_BEFORE_QUOTE_RE.search(normalized_text[: match.start()])
        )
        if (
            form_match is None
            and not has_company_marker
            and normalize_company_name(raw_name) in _REPORT_TOPIC_TERMS
        ):
            continue
        if form_match is None and not _quote_has_company_context(
            normalized_text,
            match.start(),
            compare_requested=compare_requested,
        ):
            continue
        span_start = form_match.start() if form_match is not None else match.start()
        if _overlaps(span_start, match.end(), occupied_spans):
            continue
        if form_match is not None:
            raw_name = f"{form_match.group('form')} {raw_name}"
        normalized_name = normalize_company_name(raw_name)
        if not _is_usable_name(normalized_name):
            continue
        parsed.append(
            _ParsedMention(
                kind=EntityKind.NAME,
                raw_text=raw_name,
                normalized_value=normalized_name,
                checksum_valid=None,
                span_start=span_start,
                span_end=match.end(),
                explicit=True,
            )
        )
        occupied_spans.append((span_start, match.end()))

    split_requested = compare_requested or bool(_COMPARISON_SEPARATOR_RE.search(normalized_text))
    if not parsed or split_requested:
        for mention in _parse_unquoted_names(normalized_text, split_requested):
            if not _overlaps(mention.span_start, mention.span_end, occupied_spans):
                parsed.append(mention)

    parsed.sort(key=lambda mention: (mention.span_start, mention.span_end))
    unique_mentions: list[_ParsedMention] = []
    seen: set[tuple[EntityKind, str]] = set()
    for mention in parsed:
        key = (mention.kind, mention.normalized_value)
        if key in seen and not preserve_duplicates:
            continue
        seen.add(key)
        unique_mentions.append(mention)

    intent = (
        QueryIntent.COMPARE_EXPLICIT
        if compare_requested or len(unique_mentions) > 1
        else QueryIntent.LOOKUP
    )
    mentions = tuple(
        EntityMention(
            mention_id=f"mention_{index}",
            kind=mention.kind,
            raw_text=mention.raw_text,
            normalized_value=mention.normalized_value,
            checksum_valid=mention.checksum_valid,
            span_start=mention.span_start,
            span_end=mention.span_end,
            explicit=mention.explicit,
        )
        for index, mention in enumerate(unique_mentions, start=1)
    )
    return QueryPlan(raw_query=normalized_text, intent=intent, mentions=mentions)


def resolve_query(plan: QueryPlan, source: CounterpartySource) -> QueryResolution:
    """Разрешить все упоминания, используя exact-поиск до fuzzy-кандидатов."""

    results = tuple(_resolve_mention(mention, source) for mention in plan.mentions)
    resolved_company_ids = tuple(
        dict.fromkeys(
            result.candidates[0].company_id
            for result in results
            if result.status is ResolutionStatus.RESOLVED
        )
    )
    requires_clarification = (
        not plan.mentions
        or any(result.status is not ResolutionStatus.RESOLVED for result in results)
        or (plan.intent is QueryIntent.COMPARE_EXPLICIT and len(resolved_company_ids) < 2)
    )
    return QueryResolution(
        plan=plan,
        results=results,
        resolved_company_ids=resolved_company_ids,
        requires_clarification=requires_clarification,
    )


def parse_and_resolve_query(text: str, source: CounterpartySource) -> QueryResolution:
    """Выполнить полный детерминированный контур шага 2."""

    return resolve_query(parse_query(text), source)


def _resolve_mention(
    mention: EntityMention,
    source: CounterpartySource,
) -> ResolutionResult:
    if mention.kind is EntityKind.INN:
        return source.find_by_inn(mention.normalized_value)
    if mention.kind is EntityKind.OGRN:
        return source.find_by_ogrn(mention.normalized_value)

    exact = source.find_by_name_exact(mention.normalized_value)
    if exact.status is not ResolutionStatus.NOT_FOUND:
        return exact
    return source.find_by_name_fuzzy(mention.normalized_value, limit=3)


def _identifier_is_valid(kind: EntityKind, value: str) -> bool:
    return is_valid_inn(value) if kind is EntityKind.INN else is_valid_ogrn(value)


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(
        start < occupied_end and end > occupied_start for occupied_start, occupied_end in spans
    )


def _quote_has_company_context(
    text: str,
    quote_start: int,
    *,
    compare_requested: bool,
) -> bool:
    prefix = text[:quote_start]
    if _COMPANY_MARKER_BEFORE_QUOTE_RE.search(prefix):
        return True
    if compare_requested and _ENTITY_CONNECTOR_BEFORE_QUOTE_RE.search(prefix):
        return True
    if not prefix.strip():
        return True

    command_match = _COMMAND_PREFIX_RE.match(text)
    if command_match is None or command_match.end() > quote_start:
        return False
    remainder = prefix[command_match.end() :]
    remainder = _OBJECT_PREFIX_RE.sub("", remainder, count=1)
    return not remainder.strip(" \t\r\n:—-")


def _parse_unquoted_names(text: str, split_requested: bool) -> list[_ParsedMention]:
    command_match = _COMMAND_PREFIX_RE.match(text)
    without_command = _COMMAND_PREFIX_RE.sub("", text, count=1)
    without_object = _OBJECT_PREFIX_RE.sub("", without_command, count=1)
    without_trailing_clause = _TRAILING_CLAUSE_RE.sub("", without_object, count=1)
    cleaned = without_trailing_clause.strip(" \t\r\n.,!?;:—-")
    if not cleaned:
        return []

    pieces = [cleaned]
    if split_requested:
        split_pieces = [piece.strip() for piece in _COMPARISON_SEPARATOR_RE.split(cleaned)]
        if len(split_pieces) > 1 and all(split_pieces):
            pieces = split_pieces

    mentions: list[_ParsedMention] = []
    search_from = 0
    for piece in pieces:
        normalized_name = normalize_company_name(piece)
        if not _is_usable_name(normalized_name):
            continue
        start = text.find(piece, search_from)
        if start < 0:
            start = 0
        end = start + len(piece)
        search_from = end
        mentions.append(
            _ParsedMention(
                kind=EntityKind.NAME,
                raw_text=piece,
                normalized_value=normalized_name,
                checksum_valid=None,
                span_start=start,
                span_end=end,
                explicit=command_match is not None or _starts_with_legal_form(normalized_name),
            )
        )
    return mentions


def _starts_with_legal_form(normalized_name: str) -> bool:
    return company_legal_form(normalized_name) is not None


def _is_usable_name(normalized_name: str) -> bool:
    compact = company_core_name(normalized_name).replace(" ", "")
    return len(compact) >= 2 and normalized_name not in _INSTRUCTION_ONLY and not compact.isdigit()
