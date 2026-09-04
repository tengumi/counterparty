"""Контрольные суммы реквизитов и нормализация названий."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein

from counterparty_agent.models import (
    BankTrafficLight,
    CounterpartySnapshot,
)

_INN_10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)


_INN_12_FIRST_WEIGHTS = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


_INN_12_SECOND_WEIGHTS = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


_LEGAL_FORM_PREFIXES = (
    "общество с ограниченной ответственностью",
    "публичное акционерное общество",
    "непубличное акционерное общество",
    "акционерное общество",
    "индивидуальный предприниматель",
    "автономная некоммерческая организация",
    "гаражно строительный кооператив",
    "закрытое акционерное общество",
    "открытое акционерное общество",
    "ассоциация",
    "ооо",
    "пао",
    "нао",
    "ао",
    "ип",
    "зао",
    "оао",
    "ано",
    "гск",
)


_LEGAL_FORM_CODES = {
    "общество с ограниченной ответственностью": "OOO",
    "публичное акционерное общество": "PAO",
    "непубличное акционерное общество": "NAO",
    "акционерное общество": "AO",
    "индивидуальный предприниматель": "IP",
    "автономная некоммерческая организация": "ANO",
    "гаражно строительный кооператив": "GSK",
    "закрытое акционерное общество": "ZAO",
    "открытое акционерное общество": "OAO",
    "ассоциация": "ASSOCIATION",
    "ооо": "OOO",
    "пао": "PAO",
    "нао": "NAO",
    "ао": "AO",
    "ип": "IP",
    "зао": "ZAO",
    "оао": "OAO",
    "ано": "ANO",
    "гск": "GSK",
}


def normalize_identifier(value: str) -> str:
    """Оставить в идентификаторе только десятичные ASCII-цифры."""

    return "".join(character for character in value if character in "0123456789")


def is_valid_inn(value: str) -> bool:
    """Проверить длину и контрольные цифры ИНН организации или физлица."""

    normalized = normalize_identifier(value)
    if normalized != value.strip() or len(normalized) not in {10, 12}:
        return False

    digits = tuple(int(character) for character in normalized)
    if len(digits) == 10:
        checksum = sum(
            digit * weight for digit, weight in zip(digits, _INN_10_WEIGHTS, strict=False)
        )
        return checksum % 11 % 10 == digits[9]

    first_checksum = sum(
        digit * weight for digit, weight in zip(digits, _INN_12_FIRST_WEIGHTS, strict=False)
    )
    second_checksum = sum(
        digit * weight for digit, weight in zip(digits, _INN_12_SECOND_WEIGHTS, strict=False)
    )
    return first_checksum % 11 % 10 == digits[10] and second_checksum % 11 % 10 == digits[11]


def is_valid_ogrn(value: str) -> bool:
    """Проверить длину и контрольную цифру ОГРН или ОГРНИП."""

    normalized = normalize_identifier(value)
    if normalized != value.strip():
        return False
    if len(normalized) == 13:
        return int(normalized[:12]) % 11 % 10 == int(normalized[-1])
    if len(normalized) == 15:
        return int(normalized[:14]) % 13 % 10 == int(normalized[-1])
    return False


def parse_bank_traffic_light(raw_level: str | None) -> BankTrafficLight | None:
    """Распознать известный цвет, сохранив неизвестное raw-значение отдельно."""

    if raw_level is None:
        return None
    try:
        return BankTrafficLight(raw_level)
    except ValueError:
        return None


def normalize_company_name(value: str) -> str:
    """Нормализовать регистр, `ё`, кавычки, дефисы и пробелы названия."""

    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    normalized = re.sub(r"[^0-9a-zа-я]+", " ", normalized)
    return " ".join(normalized.split())


def company_name_keys(value: str) -> tuple[str, ...]:
    """Построить точные ключи названия с ОПФ и без неё."""

    normalized = normalize_company_name(value)
    if not normalized:
        return ()

    keys = [normalized, normalized.replace(" ", "")]
    for prefix in _LEGAL_FORM_PREFIXES:
        if normalized == prefix:
            break
        marker = f"{prefix} "
        if normalized.startswith(marker):
            core_name = normalized.removeprefix(marker)
            keys.extend((core_name, core_name.replace(" ", "")))
            break
    return tuple(dict.fromkeys(key for key in keys if key))


def company_legal_form(value: str) -> str | None:
    """Вернуть канонический код явно указанной организационно-правовой формы."""

    normalized = normalize_company_name(value)
    for prefix in _LEGAL_FORM_PREFIXES:
        if normalized == prefix or normalized.startswith(f"{prefix} "):
            return _LEGAL_FORM_CODES[prefix]
    return None


def company_core_name(value: str) -> str:
    """Вернуть нормализованное название без ведущей правовой формы."""

    normalized = normalize_company_name(value)
    for prefix in _LEGAL_FORM_PREFIXES:
        if normalized == prefix:
            return ""
        marker = f"{prefix} "
        if normalized.startswith(marker):
            return normalized.removeprefix(marker)
    return normalized


def _legal_form_matches(value: str, snapshot: CounterpartySnapshot) -> bool:
    requested_form = company_legal_form(value)
    if requested_form is None:
        return True
    snapshot_forms = {
        legal_form
        for name in (snapshot.identity.full_name, snapshot.identity.short_name)
        if (legal_form := company_legal_form(name)) is not None
    }
    return requested_form in snapshot_forms


def _name_similarity(query_core: str, candidate: str) -> tuple[float, int]:
    candidate_core = company_core_name(candidate)
    score = max(
        float(fuzz.ratio(query_core, candidate_core)),
        float(fuzz.ratio(query_core.replace(" ", ""), candidate_core.replace(" ", ""))),
        float(fuzz.token_sort_ratio(query_core, candidate_core)),
    )
    distance = int(
        DamerauLevenshtein.distance(
            query_core.replace(" ", ""),
            candidate_core.replace(" ", ""),
        )
    )
    return score, distance
