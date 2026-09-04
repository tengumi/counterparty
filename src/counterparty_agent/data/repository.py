"""Загрузка snapshots, индексы и поиск кандидатов."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

from pydantic import ValidationError

from counterparty_agent.data.errors import SnapshotSourceError
from counterparty_agent.data.identifiers import (
    _LEGAL_FORM_PREFIXES,
    _legal_form_matches,
    _name_similarity,
    company_core_name,
    company_legal_form,
    company_name_keys,
    is_valid_inn,
    is_valid_ogrn,
    normalize_company_name,
)
from counterparty_agent.data.mapping import _map_record
from counterparty_agent.models import (
    CounterpartyCandidate,
    CounterpartySnapshot,
    MatchMethod,
    ResolutionResult,
    ResolutionStatus,
    SourceOutcome,
)


class CounterpartySource(Protocol):
    """Минимальная граница источника только для чтения."""

    @property
    def outcome(self) -> SourceOutcome:
        """Вернуть состояние загруженного источника."""

    @property
    def snapshots(self) -> tuple[CounterpartySnapshot, ...]:
        """Вернуть неизменяемую коллекцию канонических снимков."""

    @property
    def source_hash(self) -> str:
        """Вернуть SHA-256 исходного артефакта."""

    def get_snapshot(self, snapshot_id: str) -> CounterpartySnapshot | None:
        """Вернуть снимок по внутреннему идентификатору."""

    def find_by_inn(self, value: str) -> ResolutionResult:
        """Найти контрагента по точному ИНН."""

    def find_by_ogrn(self, value: str) -> ResolutionResult:
        """Найти контрагента по точному ОГРН или ОГРНИП."""

    def find_by_name_exact(self, value: str) -> ResolutionResult:
        """Найти кандидатов по точному нормализованному названию."""

    def find_by_name_fuzzy(
        self,
        value: str,
        *,
        limit: int = 3,
        score_cutoff: float = 75.0,
    ) -> ResolutionResult:
        """Вернуть fuzzy-кандидатов, не выбирая компанию автоматически."""


class JsonCounterpartySource:
    """Загруженный в память JSON-источник с точными индексами."""

    def __init__(
        self,
        snapshots: Sequence[CounterpartySnapshot],
        *,
        source_hash: str,
        outcome: SourceOutcome = SourceOutcome.SUCCESS,
    ) -> None:
        self._snapshots = tuple(snapshots)
        self._source_hash = source_hash
        self._outcome = outcome
        self._by_snapshot_id = {snapshot.snapshot_id: snapshot for snapshot in self._snapshots}
        self._by_inn = self._build_unique_index("inn")
        self._by_ogrn = self._build_unique_index("ogrn")
        self._by_name = self._build_name_index()

    @classmethod
    def from_path(cls, path: Path) -> JsonCounterpartySource:
        """Прочитать реальный snapshot и атомарно построить канонические записи."""

        try:
            raw_content = path.read_bytes()
        except FileNotFoundError as error:
            raise SnapshotSourceError(
                SourceOutcome.UNAVAILABLE,
                "snapshot_not_found",
                "Файл JSON-источника не найден",
            ) from error
        except PermissionError as error:
            raise SnapshotSourceError(
                SourceOutcome.DENIED,
                "snapshot_access_denied",
                "Недостаточно прав для чтения JSON-источника",
            ) from error
        except OSError as error:
            raise SnapshotSourceError(
                SourceOutcome.UNAVAILABLE,
                "snapshot_unavailable",
                "JSON-источник временно недоступен",
            ) from error

        source_hash = hashlib.sha256(raw_content).hexdigest()
        try:
            parsed = json.loads(raw_content, parse_float=Decimal)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SnapshotSourceError(
                SourceOutcome.INVALID,
                "invalid_json",
                "JSON-источник содержит некорректный документ",
            ) from error

        if not isinstance(parsed, list):
            raise SnapshotSourceError(
                SourceOutcome.INVALID,
                "invalid_root",
                "Корнем JSON-источника должен быть массив",
            )

        snapshots_list: list[CounterpartySnapshot] = []
        for index, record in enumerate(parsed, start=1):
            try:
                snapshot = _map_record(
                    record,
                    record_number=index,
                    source_name=path.name,
                    source_hash=source_hash,
                )
            except SnapshotSourceError:
                raise
            except ValidationError:
                raise SnapshotSourceError(
                    SourceOutcome.INVALID,
                    "invalid_record",
                    f"Запись {index} не соответствует канонической модели",
                ) from None
            snapshots_list.append(snapshot)

        snapshots = tuple(snapshots_list)
        has_unknown_bank_level = any(
            snapshot.bank_risk.raw_level is not None and snapshot.bank_risk.recognized_level is None
            for snapshot in snapshots
        )
        if not snapshots:
            outcome = SourceOutcome.EMPTY
        elif has_unknown_bank_level:
            outcome = SourceOutcome.PARTIAL
        else:
            outcome = SourceOutcome.SUCCESS
        return cls(snapshots, source_hash=source_hash, outcome=outcome)

    @property
    def outcome(self) -> SourceOutcome:
        """Вернуть состояние загруженного источника."""

        return self._outcome

    @property
    def source_hash(self) -> str:
        """Вернуть SHA-256 исходного файла без раскрытия его содержимого."""

        return self._source_hash

    @property
    def snapshots(self) -> tuple[CounterpartySnapshot, ...]:
        """Вернуть неизменяемую коллекцию канонических снимков."""

        return self._snapshots

    def get_snapshot(self, snapshot_id: str) -> CounterpartySnapshot | None:
        """Вернуть снимок по внутреннему непрозрачному идентификатору."""

        return self._by_snapshot_id.get(snapshot_id)

    def find_by_inn(self, value: str) -> ResolutionResult:
        """Найти контрагента по точному валидному ИНН."""

        normalized = value.strip()
        if not is_valid_inn(normalized):
            return ResolutionResult(
                status=ResolutionStatus.INVALID_IDENTIFIER,
                query=normalized,
            )
        return self._resolution_from_ids(normalized, self._by_inn, MatchMethod.INN_EXACT)

    def find_by_ogrn(self, value: str) -> ResolutionResult:
        """Найти контрагента по точному валидному ОГРН или ОГРНИП."""

        normalized = value.strip()
        if not is_valid_ogrn(normalized):
            return ResolutionResult(
                status=ResolutionStatus.INVALID_IDENTIFIER,
                query=normalized,
            )
        return self._resolution_from_ids(normalized, self._by_ogrn, MatchMethod.OGRN_EXACT)

    def find_by_name_exact(self, value: str) -> ResolutionResult:
        """Найти контрагентов по точному нормализованному названию."""

        normalized = normalize_company_name(value)
        snapshot_ids: set[str] = set()
        for key in company_name_keys(value):
            snapshot_ids.update(self._by_name.get(key, ()))
        all_ordered_ids = tuple(
            snapshot.snapshot_id
            for snapshot in self._snapshots
            if snapshot.snapshot_id in snapshot_ids
        )
        compatible_ids = tuple(
            snapshot_id
            for snapshot_id in all_ordered_ids
            if _legal_form_matches(value, self._by_snapshot_id[snapshot_id])
        )
        if compatible_ids or company_legal_form(value) is None or not all_ordered_ids:
            return self._resolution(normalized, compatible_ids, MatchMethod.NAME_EXACT)

        candidates = tuple(
            _candidate(self._by_snapshot_id[snapshot_id], legal_form_conflict=True)
            for snapshot_id in all_ordered_ids
        )
        return ResolutionResult(
            status=ResolutionStatus.NEEDS_CONFIRMATION,
            query=normalized,
            method=MatchMethod.NAME_EXACT,
            candidates=candidates,
        )

    def find_by_name_fuzzy(
        self,
        value: str,
        *,
        limit: int = 3,
        score_cutoff: float = 75.0,
    ) -> ResolutionResult:
        """Найти до трёх похожих названий только для явного подтверждения."""

        if limit < 1 or limit > 10:
            raise ValueError("limit должен быть в диапазоне от 1 до 10")
        if score_cutoff < 0 or score_cutoff > 100:
            raise ValueError("score_cutoff должен быть в диапазоне от 0 до 100")

        normalized = normalize_company_name(value)
        query_core = company_core_name(value)
        query_compact = query_core.replace(" ", "")
        if (
            len(query_compact) < 4
            or not any(character.isalpha() for character in query_compact)
            or normalized in _LEGAL_FORM_PREFIXES
        ):
            return ResolutionResult(status=ResolutionStatus.NOT_FOUND, query=normalized)

        scored: list[tuple[float, int, str, CounterpartySnapshot, bool]] = []
        for snapshot in self._snapshots:
            metrics = tuple(
                _name_similarity(query_core, candidate_name)
                for candidate_name in (snapshot.identity.full_name, snapshot.identity.short_name)
            )
            score, distance = min(metrics, key=lambda item: (-item[0], item[1]))
            if score >= score_cutoff:
                scored.append(
                    (
                        score,
                        distance,
                        snapshot.company_id,
                        snapshot,
                        not _legal_form_matches(value, snapshot),
                    )
                )

        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        candidates = tuple(
            _candidate(
                snapshot,
                match_score=round(score, 2),
                rank=rank,
                legal_form_conflict=legal_form_conflict,
            )
            for rank, (score, _, _, snapshot, legal_form_conflict) in enumerate(
                scored[:limit], start=1
            )
        )
        if not candidates:
            return ResolutionResult(status=ResolutionStatus.NOT_FOUND, query=normalized)
        return ResolutionResult(
            status=ResolutionStatus.NEEDS_CONFIRMATION,
            query=normalized,
            method=MatchMethod.NAME_FUZZY,
            candidates=candidates,
        )

    def _build_unique_index(self, field: str) -> dict[str, tuple[str, ...]]:
        index: defaultdict[str, list[str]] = defaultdict(list)
        for snapshot in self._snapshots:
            key = cast(str, getattr(snapshot.identity, field))
            index[key].append(snapshot.snapshot_id)
        duplicate_count = sum(len(snapshot_ids) > 1 for snapshot_ids in index.values())
        if duplicate_count:
            raise SnapshotSourceError(
                SourceOutcome.INVALID,
                "duplicate_identifier",
                "JSON-источник содержит повторяющиеся уникальные идентификаторы",
            )
        return {key: tuple(snapshot_ids) for key, snapshot_ids in index.items()}

    def _build_name_index(self) -> dict[str, tuple[str, ...]]:
        index: defaultdict[str, list[str]] = defaultdict(list)
        for snapshot in self._snapshots:
            for name in (snapshot.identity.full_name, snapshot.identity.short_name):
                for key in company_name_keys(name):
                    if snapshot.snapshot_id not in index[key]:
                        index[key].append(snapshot.snapshot_id)
        return {key: tuple(snapshot_ids) for key, snapshot_ids in index.items()}

    def _resolution_from_ids(
        self,
        query: str,
        index: Mapping[str, tuple[str, ...]],
        method: MatchMethod,
    ) -> ResolutionResult:
        return self._resolution(query, index.get(query, ()), method)

    def _resolution(
        self,
        query: str,
        snapshot_ids: Sequence[str],
        method: MatchMethod,
    ) -> ResolutionResult:
        candidates = tuple(
            _candidate(self._by_snapshot_id[snapshot_id]) for snapshot_id in snapshot_ids
        )
        if not candidates:
            return ResolutionResult(status=ResolutionStatus.NOT_FOUND, query=query)
        status = ResolutionStatus.RESOLVED if len(candidates) == 1 else ResolutionStatus.AMBIGUOUS
        return ResolutionResult(
            status=status,
            query=query,
            method=method,
            candidates=candidates,
        )


def _candidate(
    snapshot: CounterpartySnapshot,
    *,
    match_score: float | None = None,
    rank: int | None = None,
    legal_form_conflict: bool = False,
) -> CounterpartyCandidate:
    return CounterpartyCandidate(
        company_id=snapshot.company_id,
        snapshot_id=snapshot.snapshot_id,
        inn=snapshot.identity.inn,
        ogrn=snapshot.identity.ogrn,
        full_name=snapshot.identity.full_name,
        short_name=snapshot.identity.short_name,
        party_type=snapshot.identity.party_type,
        raw_status=snapshot.status.raw_status,
        match_score=match_score,
        rank=rank,
        legal_form_conflict=legal_form_conflict,
    )
