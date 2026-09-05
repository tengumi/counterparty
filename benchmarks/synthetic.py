"""Независимый генератор: не импортирует поиск, mapper или правила приложения."""

from dataclasses import dataclass
from random import Random
from typing import Any

DATE = "2026-09-04T00:00:00Z"


@dataclass(frozen=True)
class Truth:
    inn: str
    ogrn: str
    name: str
    profit: int | None
    proceeds: int | None
    year: int | None
    bank: str | None


@dataclass(frozen=True)
class SyntheticDataset:
    reports: list[dict[str, Any]]
    truth: tuple[Truth, ...]


def synthetic_factory(seed: int = 409, n: int = 100) -> SyntheticDataset:
    """Суммы и ожидания создаются до сериализации; первые записи стабильны при росте N."""

    rng = Random(seed)
    reports: list[dict[str, Any]] = []
    truth: list[Truth] = []
    for index in range(n):
        base = f"990{index:06d}"
        check = sum(int(d) * w for d, w in zip(base, (2, 4, 10, 3, 5, 9, 4, 6, 8), strict=True))
        inn = base + str(check % 11 % 10)
        base_ogrn = f"12699{index:07d}"
        ogrn = base_ogrn + str(int(base_ogrn) % 11 % 10)
        name = f'ООО "СИНТЕТИЧЕСКИЙ ПОСТАВЩИК {index:04d}"'
        profit = [rng.randrange(1, 1_000_000), -rng.randrange(1, 1_000_000), 0, None][index % 4]
        proceeds = 2**54 + index if index % 20 == 14 else rng.randrange(1000, 9_000_000)
        bank = ["GREEN", "YELLOW", "RED", "GREY", None][index % 5]
        year = None if index % 20 == 5 else 2023 if index % 20 == 6 else 2025
        truth.append(
            Truth(inn, ogrn, name, profit if year else None, proceeds if year else None, year, bank)
        )
        common: dict[str, Any] = {"year": year, "proceeds": {"$numberLong": str(proceeds)}}
        if profit is not None:
            common["profit"] = {"$numberLong": str(profit)}
        report: dict[str, Any] = {
            "reportDate": {"$date": DATE},
            "baseInfo": {
                "inn": inn,
                "ogrn": ogrn,
                "fullName": name,
                "shortName": name,
                "registrationInfo": {"registrationDate": {"$date": "2018-01-01T00:00:00Z"}},
            },
            "status": {"status": "CURRENT", "date": {"$date": DATE}},
            "arbitrationByStatus": {
                "plaintiffArbitration": {
                    f"plaintiffArbitration{s}": {} for s in ("Finished", "Pending", "Appealed")
                },
                "defandantArbitration": {
                    f"defandantArbitration{s}": {} for s in ("Finished", "Pending", "Appealed")
                },
            },
            "executionProceedings": [],
            "kindsOfActivityInfo": {
                "mainKindOfActivity": {"code": "62.01", "description": "Синтетическая деятельность"}
            },
            "reputationalRisks": {"positive": [], "negative": []},
        }
        if year:
            report["finReports"] = [
                {
                    "common": common,
                    "assets": {"totalAssets": 1000, "currentAssets": {}},
                    "liabilities": {
                        "totalLiabilities": 1000,
                        "capitals": -10 if index % 20 == 4 else 100,
                    },
                }
            ]
        if bank is not None:
            report["zskRiskLevel"] = bank
        reports.append({"_id": {"ogrn": ogrn, "date": {"$date": DATE}}, "report": report})
    return SyntheticDataset(reports, tuple(truth))
