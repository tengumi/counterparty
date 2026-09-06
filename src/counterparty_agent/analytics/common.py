"""Построение проверяемых findings и производных доказательств."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from counterparty_agent.models import (
    CounterpartySnapshot,
    Evidence,
    EvidenceCoverage,
    EvidenceKind,
    EvidenceQuality,
    Finding,
    FindingCategory,
    FindingDataStatus,
    FindingSeverity,
)

_RULES_VERSION = "analysis-rules-v1"


_NEGATIVE_SIGNAL_TOPICS = {
    "arbitrationDefendant": "арбитражные дела в роли ответчика",
    "massOkved": "количество видов деятельности",
    "executionProceedings": "исполнительные производства",
    "massAddress": "массовость адреса",
    "fnsBlocking": "ограничения ФНС",
    "profit": "прибыль",
    "invalidAddress": "достоверность адреса",
    "invalidRegistrationData": "достоверность регистрационных данных",
    "massAuthpersons": "массовость руководства",
    "currentAssets": "оборотные активы",
    "liquidationStatus": "ликвидационный статус",
    "invalidAuthpersonsData": "достоверность сведений о руководстве",
}


class AnalysisValidationError(ValueError):
    """Безопасный отказ при непроверяемом входе или изменённых результатах."""


class _AnalysisBuilder:
    """Локальный накопитель; не хранится в сессии и не логирует входные значения."""

    def __init__(self, snapshot: CounterpartySnapshot) -> None:
        self.snapshot = snapshot
        self.findings: list[Finding] = []
        self.derived: list[Evidence] = []
        self.by_path: defaultdict[str, list[Evidence]] = defaultdict(list)
        for evidence in snapshot.evidence:
            if (
                evidence.company_id != snapshot.company_id
                or evidence.snapshot_id != snapshot.snapshot_id
                or evidence.source_hash != snapshot.source_hash
                or evidence.record_hash != snapshot.record_hash
                or evidence.report_at != snapshot.report_at
                or evidence.source_name != snapshot.source_name
                or evidence.kind is EvidenceKind.DERIVED
            ):
                raise AnalysisValidationError("Исходный ledger не соответствует снимку")
            self.by_path[evidence.canonical_path].append(evidence)

    def inputs(self, path: str, values: Sequence[object]) -> tuple[Evidence, ...]:
        """Сверить значения канонической модели с evidence до любого расчёта."""

        evidence = tuple(sorted(self.by_path[path], key=lambda item: item.evidence_id))
        expected = sorted(_encode(value) for value in values)
        actual = sorted(_encode(item.typed_value) for item in evidence)
        if not evidence or actual != expected:
            raise AnalysisValidationError(f"Нет согласованных доказательств раздела {path}")
        return evidence

    def add(
        self,
        code: str,
        category: FindingCategory,
        statement: str,
        values: dict[str, object],
        parents: Sequence[Evidence],
        *,
        status: FindingDataStatus = FindingDataStatus.CONFIRMED,
        severity: FindingSeverity = FindingSeverity.INFO,
        period: int | str | None = None,
        unit: str | None = None,
        currency: str | None = None,
    ) -> None:
        if not parents:
            raise AnalysisValidationError("Расчёт не имеет исходных доказательств")
        if any(item.quality is EvidenceQuality.CONFLICTING for item in parents):
            status = FindingDataStatus.CONFLICTING
        elif status is FindingDataStatus.CONFIRMED and any(
            item.quality is EvidenceQuality.PARTIAL for item in parents
        ):
            status = FindingDataStatus.PARTIAL
        source_ids = tuple(sorted({item.evidence_id for item in parents}))
        payload = {
            "rules": _RULES_VERSION,
            "snapshot": self.snapshot.snapshot_id,
            "code": code,
            "period": period,
            "values": values,
            "parents": source_ids,
            "status": status.value,
        }
        evidence_id = f"evidence_{_digest(payload)}"
        quality = {
            FindingDataStatus.CONFLICTING: EvidenceQuality.CONFLICTING,
            FindingDataStatus.PARTIAL: EvidenceQuality.PARTIAL,
            FindingDataStatus.INSUFFICIENT: EvidenceQuality.PARTIAL,
        }.get(status, EvidenceQuality.CONFIRMED)
        coverage = {
            FindingDataStatus.INSUFFICIENT: EvidenceCoverage.MISSING,
            FindingDataStatus.INAPPLICABLE: EvidenceCoverage.NOT_APPLICABLE,
        }.get(status, EvidenceCoverage.PRESENT)
        self.derived.append(
            Evidence(
                evidence_id=evidence_id,
                company_id=self.snapshot.company_id,
                snapshot_id=self.snapshot.snapshot_id,
                canonical_path=f"analysis.{code}",
                stable_key=f"{_RULES_VERSION}:{code}:{period}",
                source_paths=tuple(
                    sorted({path for item in parents for path in item.source_paths})
                ),
                kind=EvidenceKind.DERIVED,
                typed_value=values,
                report_at=self.snapshot.report_at,
                source_name=self.snapshot.source_name,
                source_hash=self.snapshot.source_hash,
                record_hash=self.snapshot.record_hash,
                period=period,
                unit=unit,
                currency=currency,
                quality=quality,
                coverage=coverage,
                derived_from=source_ids,
            )
        )
        self.findings.append(
            Finding(
                finding_id=f"finding_{_digest((evidence_id, statement, severity.value))}",
                company_id=self.snapshot.company_id,
                snapshot_id=self.snapshot.snapshot_id,
                code=code,
                category=category,
                severity=severity,
                data_status=status,
                statement=statement,
                period=period,
                evidence_ids=(evidence_id,),
            )
        )


def _number(value: object) -> str:
    return "нет данных" if value is None else str(value)


def _money(value: Decimal | None) -> str:
    """Показать рубли с разрядами без округления и изменения масштаба."""

    if value is None:
        return "нет данных"
    return format(value, ",f").replace(",", "\u202f")


def _contains_none(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_none(item) for item in value.values())
    return value is None


def _encode(value: object) -> str:
    """Канонизация без потери Decimal и без нечисловых NaN/Infinity."""

    def default(item: object) -> str:
        if isinstance(item, Decimal):
            if not item.is_finite():
                raise AnalysisValidationError("Нечисловое денежное значение в исходных данных")
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat()
        raise AnalysisValidationError("Неподдерживаемый тип доказательства")

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=default, allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_encode(value).encode("utf-8")).hexdigest()[:24]
