"""Интеграционные проверки разбора запроса и поиска на реальном snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from counterparty_agent.config import Settings
from counterparty_agent.data.identifiers import company_core_name, company_legal_form
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import (
    CounterpartySnapshot,
    EntityKind,
    MatchMethod,
    PartyType,
    QueryIntent,
    QueryResolution,
    ResolutionStatus,
)
from counterparty_agent.query import QueryParseError, parse_and_resolve_query, parse_query


@pytest.fixture(scope="module")
def source() -> JsonCounterpartySource:
    """Использовать только выданный snapshot, не создавая фиктивные компании."""

    snapshot_path = Path(Settings().snapshot_json_path)
    if not snapshot_path.is_file():
        pytest.skip("Реальный snapshot не настроен в COUNTERPARTY_SNAPSHOT_JSON_PATH")
    return JsonCounterpartySource.from_path(snapshot_path)


def test_real_identifiers_are_extracted_and_resolved_exactly(
    source: JsonCounterpartySource,
) -> None:
    legal_entity = next(
        item for item in source.snapshots if item.identity.party_type is PartyType.LEGAL_ENTITY
    )
    entrepreneur = next(
        item
        for item in source.snapshots
        if item.identity.party_type is PartyType.INDIVIDUAL_ENTREPRENEUR
    )
    cases = (
        (f"Проверь ИНН {legal_entity.identity.inn}", EntityKind.INN, MatchMethod.INN_EXACT),
        (f"ИНН {entrepreneur.identity.inn}", EntityKind.INN, MatchMethod.INN_EXACT),
        (f"ОГРН {legal_entity.identity.ogrn}", EntityKind.OGRN, MatchMethod.OGRN_EXACT),
        (f"ОГРНИП {entrepreneur.identity.ogrn}", EntityKind.OGRN, MatchMethod.OGRN_EXACT),
    )

    for index, (query, kind, method) in enumerate(cases, start=1):
        resolution = parse_and_resolve_query(query, source)
        if len(resolution.plan.mentions) != 1:
            pytest.fail(f"Неверное число упоминаний в сценарии {index}", pytrace=False)
        mention = resolution.plan.mentions[0]
        result = resolution.results[0]
        if mention.kind is not kind or mention.checksum_valid is not True:
            pytest.fail(f"Неверный тип идентификатора в сценарии {index}", pytrace=False)
        if result.status is not ResolutionStatus.RESOLVED or result.method is not method:
            pytest.fail(
                f"Идентификатор не разрешён exact-поиском в сценарии {index}",
                pytrace=False,
            )
        if resolution.requires_clarification:
            pytest.fail(f"Лишнее уточнение в сценарии {index}", pytrace=False)


def test_labeled_identifier_may_be_formatted_before_validation(
    source: JsonCounterpartySource,
) -> None:
    identifier = source.snapshots[0].identity.inn
    formatted = "-".join((identifier[:3], identifier[3:6], identifier[6:]))
    resolution = parse_and_resolve_query(f"ИНН: {formatted}", source)

    assert len(resolution.plan.mentions) == 1
    assert resolution.plan.mentions[0].normalized_value == identifier
    assert resolution.results[0].status is ResolutionStatus.RESOLVED


def test_group_mode_preserves_duplicate_positions_without_changing_default_parser(
    source: JsonCounterpartySource,
) -> None:
    first, second = source.snapshots[:2]
    query = f"Сравни {first.identity.inn}, {first.identity.inn}, {second.identity.inn}"
    assert len(parse_query(query).mentions) == 2
    group = parse_query(query, preserve_duplicates=True)
    assert len(group.mentions) == 3
    assert group.mentions[0].normalized_value == group.mentions[1].normalized_value
    assert group.mentions[0].span_start < group.mentions[1].span_start
    assert len({item.mention_id for item in group.mentions}) == 3


def test_invalid_checksum_is_terminal_and_never_becomes_a_name(
    source: JsonCounterpartySource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = source.snapshots[0]
    invalid_identifiers = (
        ("ИНН", _change_checksum(snapshot.identity.inn)),
        ("ОГРН", _change_checksum(snapshot.identity.ogrn)),
    )

    def unexpected_fuzzy(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        pytest.fail("Fuzzy-поиск не должен вызываться для идентификатора", pytrace=False)

    monkeypatch.setattr(source, "find_by_name_fuzzy", unexpected_fuzzy)
    for index, (label, identifier) in enumerate(invalid_identifiers, start=1):
        resolution = parse_and_resolve_query(f"{label} {identifier}", source)
        result = resolution.results[0]
        if result.status is not ResolutionStatus.INVALID_IDENTIFIER:
            pytest.fail(f"Невалидный идентификатор принят в сценарии {index}", pytrace=False)
        if result.candidates:
            pytest.fail(
                f"Невалидный идентификатор дал кандидатов в сценарии {index}",
                pytrace=False,
            )


def test_normalized_exact_name_has_priority_over_fuzzy(
    source: JsonCounterpartySource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_index, snapshot = _unique_named_snapshot(source)

    def unexpected_fuzzy(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        pytest.fail("Fuzzy-поиск вызван после exact-совпадения", pytrace=False)

    monkeypatch.setattr(source, "find_by_name_fuzzy", unexpected_fuzzy)
    query = f"Проверь компанию «  {snapshot.identity.full_name.swapcase()}  »"
    resolution = parse_and_resolve_query(query, source)
    result = resolution.results[0]

    if result.status is not ResolutionStatus.RESOLVED:
        pytest.fail(f"Exact-название не разрешено для записи {record_index}", pytrace=False)
    if result.method is not MatchMethod.NAME_EXACT:
        pytest.fail(f"Exact-название ушло в другой метод у записи {record_index}", pytrace=False)
    if result.candidates[0].company_id != snapshot.company_id:
        pytest.fail(f"Exact-название нашло другую запись {record_index}", pytrace=False)


def test_natural_command_forms_do_not_pollute_company_name(
    source: JsonCounterpartySource,
) -> None:
    record_index, snapshot, core_name = _unique_core_named_snapshot(source)
    queries = (
        f"Проверить {core_name}",
        f"Найти {core_name}",
        f"Показать отчет по {core_name}",
        f"Проанализировать {core_name}",
        f"Что известно об {core_name}",
        f"Расскажи об {core_name}",
    )

    for scenario, query in enumerate(queries, start=1):
        resolution = parse_and_resolve_query(query, source)
        if len(resolution.results) != 1:
            pytest.fail(
                f"Неверное число сущностей: запись {record_index}, сценарий {scenario}",
                pytrace=False,
            )
        result = resolution.results[0]
        if (
            result.status is not ResolutionStatus.RESOLVED
            or result.method is not MatchMethod.NAME_EXACT
            or result.candidates[0].company_id != snapshot.company_id
        ):
            pytest.fail(
                f"Команда загрязнила название: запись {record_index}, сценарий {scenario}",
                pytrace=False,
            )


def test_quoted_report_section_is_not_treated_as_company(
    source: JsonCounterpartySource,
) -> None:
    identifier = source.snapshots[0].identity.inn

    for index, section in enumerate(("Суды", "прибыль", "выручка"), start=1):
        plan = parse_query(f"Проверь ИНН {identifier} и покажи раздел «{section}»")
        if len(plan.mentions) != 1 or plan.mentions[0].kind is not EntityKind.INN:
            pytest.fail(f"Раздел принят за компанию в сценарии {index}", pytrace=False)

    comparison_plan = parse_query(f"Сравни ИНН {identifier} и «выручку»")
    assert len(comparison_plan.mentions) == 1
    assert comparison_plan.mentions[0].kind is EntityKind.INN


def test_follow_up_clause_is_not_treated_as_second_company(
    source: JsonCounterpartySource,
) -> None:
    record_index, snapshot, core_name = _unique_core_named_snapshot(source)
    queries = (
        f"Проверь {core_name}; покажи суды",
        f"Проверь {core_name}\nпокажи финансы",
    )

    for scenario, query in enumerate(queries, start=1):
        resolution = parse_and_resolve_query(query, source)
        if len(resolution.results) != 1:
            pytest.fail(
                f"Лишняя сущность: запись {record_index}, сценарий {scenario}",
                pytrace=False,
            )
        result = resolution.results[0]
        if (
            result.status is not ResolutionStatus.RESOLVED
            or result.candidates[0].company_id != snapshot.company_id
        ):
            pytest.fail(
                f"Потеряна основная компания: запись {record_index}, сценарий {scenario}",
                pytrace=False,
            )


def test_exact_name_collision_remains_ambiguous(source: JsonCounterpartySource) -> None:
    record_index, name = _ambiguous_name(source)
    resolution = parse_and_resolve_query(name, source)
    result = resolution.results[0]

    if result.status is not ResolutionStatus.AMBIGUOUS:
        pytest.fail(f"Коллизия названий скрыта у записи {record_index}", pytrace=False)
    assert result.method is MatchMethod.NAME_EXACT
    assert len(result.candidates) >= 2
    assert resolution.requires_clarification
    assert not resolution.resolved_company_ids


def test_typo_returns_deterministic_top_three_without_auto_selection(
    source: JsonCounterpartySource,
) -> None:
    record_index, snapshot, typo = _snapshot_with_fuzzy_typo(source)
    first = parse_and_resolve_query(typo, source)
    second = parse_and_resolve_query(typo, source)
    reversed_source = JsonCounterpartySource(
        tuple(reversed(source.snapshots)),
        source_hash=source.source_hash,
        outcome=source.outcome,
    )
    reversed_result = parse_and_resolve_query(typo, reversed_source)

    result = first.results[0]
    if result.status is not ResolutionStatus.NEEDS_CONFIRMATION:
        pytest.fail(f"Fuzzy скрыто разрешён для записи {record_index}", pytrace=False)
    if result.method is not MatchMethod.NAME_FUZZY:
        pytest.fail(f"Опечатка не использовала fuzzy у записи {record_index}", pytrace=False)
    if snapshot.company_id not in {candidate.company_id for candidate in result.candidates}:
        pytest.fail(f"Исходная компания не вошла в top-3 у записи {record_index}", pytrace=False)

    first_signature = _candidate_signature(first)
    assert 1 <= len(first_signature) <= 3
    assert first_signature == _candidate_signature(second)
    assert first_signature == _candidate_signature(reversed_result)
    assert [candidate.rank for candidate in result.candidates] == list(
        range(1, len(result.candidates) + 1)
    )
    assert all(
        left.match_score >= right.match_score
        for left, right in zip(result.candidates, result.candidates[1:], strict=False)
        if left.match_score is not None and right.match_score is not None
    )
    assert not first.resolved_company_ids
    assert first.requires_clarification


def test_conflicting_legal_form_requires_confirmation(
    source: JsonCounterpartySource,
) -> None:
    record_index, query = _legal_form_conflict_query(source)
    resolution = parse_and_resolve_query(query, source)
    result = resolution.results[0]

    if result.status is not ResolutionStatus.NEEDS_CONFIRMATION:
        pytest.fail(f"Конфликт ОПФ скрыт для записи {record_index}", pytrace=False)
    assert result.method is MatchMethod.NAME_EXACT
    assert result.candidates
    assert all(candidate.legal_form_conflict for candidate in result.candidates)
    assert resolution.requires_clarification


def test_multiple_real_identifiers_create_comparison_plan(
    source: JsonCounterpartySource,
) -> None:
    first, second = source.snapshots[:2]
    resolution = parse_and_resolve_query(
        f"Сравни ИНН {first.identity.inn} и ИНН {second.identity.inn}",
        source,
    )

    assert resolution.plan.intent is QueryIntent.COMPARE_EXPLICIT
    assert len(resolution.plan.mentions) == 2
    assert all(result.status is ResolutionStatus.RESOLVED for result in resolution.results)
    assert resolution.resolved_company_ids == (first.company_id, second.company_id)
    assert not resolution.requires_clarification

    same_company = parse_and_resolve_query(
        f"Сравни ИНН {first.identity.inn} и ОГРН {first.identity.ogrn}",
        source,
    )
    assert len(same_company.resolved_company_ids) == 1
    assert same_company.requires_clarification


def test_two_unquoted_names_with_explicit_separator_create_comparison(
    source: JsonCounterpartySource,
) -> None:
    first, second = _two_unique_named_snapshots(source)
    queries = (
        f"Сравни {first.identity.short_name}; {second.identity.short_name}",
        f"{first.identity.short_name}; {second.identity.short_name}",
    )

    for index, query in enumerate(queries, start=1):
        resolution = parse_and_resolve_query(query, source)
        if resolution.plan.intent is not QueryIntent.COMPARE_EXPLICIT:
            pytest.fail(f"Не распознан список названий в сценарии {index}", pytrace=False)
        if len(resolution.plan.mentions) != 2:
            pytest.fail(f"Потеряно название из списка в сценарии {index}", pytrace=False)
        if not all(result.status is ResolutionStatus.RESOLVED for result in resolution.results):
            pytest.fail(f"Не разрешён список названий в сценарии {index}", pytrace=False)
        assert resolution.resolved_company_ids == (first.company_id, second.company_id)
        assert not resolution.requires_clarification


def test_mixed_name_and_identifier_are_both_kept(
    source: JsonCounterpartySource,
) -> None:
    named, identified = _two_unique_named_snapshots(source)
    queries = (
        f"Сравни {named.identity.short_name} и ИНН {identified.identity.inn}",
        f"Сравни ИНН {identified.identity.inn} и {named.identity.short_name}",
    )

    for index, query in enumerate(queries, start=1):
        resolution = parse_and_resolve_query(query, source)
        if len(resolution.plan.mentions) != 2:
            pytest.fail(f"Потеряна смешанная сущность в сценарии {index}", pytrace=False)
        if set(resolution.resolved_company_ids) != {named.company_id, identified.company_id}:
            pytest.fail(f"Неверно разрешены смешанные сущности в сценарии {index}", pytrace=False)
        if resolution.requires_clarification:
            pytest.fail(f"Лишнее уточнение смешанных сущностей в сценарии {index}", pytrace=False)


def test_real_additional_legal_forms_keep_core_aliases(
    source: JsonCounterpartySource,
) -> None:
    expected_forms = {"ANO", "ASSOCIATION", "GSK"}
    seen_forms: set[str] = set()

    for index, snapshot in enumerate(source.snapshots, start=1):
        legal_form = company_legal_form(snapshot.identity.short_name)
        if legal_form not in expected_forms:
            continue
        seen_forms.add(legal_form)
        result = source.find_by_name_exact(company_core_name(snapshot.identity.short_name))
        if result.status is ResolutionStatus.NOT_FOUND:
            pytest.fail(f"ОПФ потеряла core alias у записи {index}", pytrace=False)

    assert seen_forms == expected_forms


def test_duplicate_identifier_is_not_a_comparison(source: JsonCounterpartySource) -> None:
    identifier = source.snapshots[0].identity.inn
    plan = parse_query(f"{identifier}, {identifier}")

    assert plan.intent is QueryIntent.LOOKUP
    assert len(plan.mentions) == 1


def test_short_or_instruction_only_query_has_no_candidates(
    source: JsonCounterpartySource,
) -> None:
    with pytest.raises(QueryParseError):
        parse_query("   ")

    for index, query in enumerate(
        ("а", "ООО", "@@@ ###", "12345", "ъъъъъъъъ", "проверь компанию"),
        start=1,
    ):
        resolution = parse_and_resolve_query(query, source)
        if any(result.candidates for result in resolution.results):
            pytest.fail(f"Мусорный запрос дал кандидатов в сценарии {index}", pytrace=False)
        if not resolution.requires_clarification:
            pytest.fail(f"Мусорный запрос не запросил уточнение в сценарии {index}", pytrace=False)


def test_resolution_does_not_write_sensitive_values(
    source: JsonCounterpartySource,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = source.snapshots[0]
    parse_and_resolve_query(f"ИНН {snapshot.identity.inn}", source)
    _, _, typo = _snapshot_with_fuzzy_typo(source)
    parse_and_resolve_query(typo, source)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert not caplog.records


def _unique_named_snapshot(
    source: JsonCounterpartySource,
) -> tuple[int, CounterpartySnapshot]:
    for index, snapshot in enumerate(source.snapshots, start=1):
        result = source.find_by_name_exact(snapshot.identity.full_name)
        if (
            result.status is ResolutionStatus.RESOLVED
            and result.candidates[0].company_id == snapshot.company_id
        ):
            return index, snapshot
    raise AssertionError("В реальном snapshot нет уникального названия")


def _unique_core_named_snapshot(
    source: JsonCounterpartySource,
) -> tuple[int, CounterpartySnapshot, str]:
    for index, snapshot in enumerate(source.snapshots, start=1):
        core_name = company_core_name(snapshot.identity.short_name)
        result = source.find_by_name_exact(core_name)
        if (
            result.status is ResolutionStatus.RESOLVED
            and result.candidates[0].company_id == snapshot.company_id
        ):
            return index, snapshot, core_name
    raise AssertionError("В реальном snapshot нет уникального core-названия")


def _ambiguous_name(source: JsonCounterpartySource) -> tuple[int, str]:
    for index, snapshot in enumerate(source.snapshots, start=1):
        for name in (snapshot.identity.full_name, snapshot.identity.short_name):
            if source.find_by_name_exact(name).status is ResolutionStatus.AMBIGUOUS:
                return index, name
    raise AssertionError("В реальном snapshot нет коллизии названий")


def _two_unique_named_snapshots(
    source: JsonCounterpartySource,
) -> tuple[CounterpartySnapshot, CounterpartySnapshot]:
    unique: list[CounterpartySnapshot] = []
    for snapshot in source.snapshots:
        result = source.find_by_name_exact(snapshot.identity.short_name)
        if (
            result.status is ResolutionStatus.RESOLVED
            and result.candidates[0].company_id == snapshot.company_id
        ):
            unique.append(snapshot)
        if len(unique) == 2:
            return unique[0], unique[1]
    raise AssertionError("В реальном snapshot нет двух уникальных названий")


def _snapshot_with_fuzzy_typo(
    source: JsonCounterpartySource,
) -> tuple[int, CounterpartySnapshot, str]:
    for index, snapshot in enumerate(source.snapshots, start=1):
        typo = _delete_middle_character(snapshot.identity.short_name)
        if typo is None:
            continue
        if source.find_by_name_exact(typo).status is not ResolutionStatus.NOT_FOUND:
            continue
        result = source.find_by_name_fuzzy(typo)
        if (
            result.status is ResolutionStatus.NEEDS_CONFIRMATION
            and result.candidates
            and result.candidates[0].company_id == snapshot.company_id
        ):
            return index, snapshot, typo
    raise AssertionError("В реальном snapshot нет подходящего fuzzy-сценария")


def _legal_form_conflict_query(source: JsonCounterpartySource) -> tuple[int, str]:
    for index, snapshot in enumerate(source.snapshots, start=1):
        core_name = company_core_name(snapshot.identity.short_name)
        opposite_form = (
            "ООО" if snapshot.identity.party_type is PartyType.INDIVIDUAL_ENTREPRENEUR else "ИП"
        )
        query = f"{opposite_form} {core_name}"
        if source.find_by_name_exact(query).status is ResolutionStatus.NEEDS_CONFIRMATION:
            return index, query
    raise AssertionError("В реальном snapshot нет сценария конфликта ОПФ")


def _delete_middle_character(name: str) -> str | None:
    words = name.split()
    candidates = (
        (index, word)
        for index, word in enumerate(words)
        if len(company_core_name(word).replace(" ", "")) >= 5
    )
    try:
        index, word = max(candidates, key=lambda item: len(item[1]))
    except ValueError:
        return None
    position = len(word) // 2
    words[index] = f"{word[:position]}{word[position + 1 :]}"
    return " ".join(words)


def _candidate_signature(
    resolution: QueryResolution,
) -> tuple[tuple[str, float | None, int | None], ...]:
    return tuple(
        (candidate.company_id, candidate.match_score, candidate.rank)
        for candidate in resolution.results[0].candidates
    )


def _change_checksum(identifier: str) -> str:
    replacement = str((int(identifier[-1]) + 1) % 10)
    return f"{identifier[:-1]}{replacement}"
