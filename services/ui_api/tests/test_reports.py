"""Overview and comparison behavior against pinned PostgreSQL snapshots."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from conftest import SignIn, add_reported_company, add_snapshot
from counterparty_storage.reports.enums import IngestionStatus
from counterparty_storage.reports.models import (
    CompanyProfile,
    CompanyStatus,
    FinancialStatement,
    ReportSnapshot,
    ZskAssessment,
)
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from counterparty_ui_api.reports import resolve_report_evidence_id


def _project(client: TestClient) -> dict[str, object]:
    """Create one project for a comparison fixture."""
    response = client.post(
        "/api/v1/projects", json={"title": "Сравнение", "client_request_id": str(uuid4())}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _pin(client: TestClient, project_id: object, inns: list[str]) -> list[str]:
    """Add existing companies and return their pinned reports in slot order."""
    response = client.post(
        f"/api/v1/projects/{project_id}/companies",
        json={"items": [{"inn": inn} for inn in inns], "expected_context_version": 0},
    )
    assert response.status_code == 200, response.text
    return [item["report_id"] for item in response.json()["companies"]]


def _fill_report(
    engine: Engine,
    report_id: UUID,
    *,
    year: int,
    proceeds: Decimal,
    profit_present: bool = True,
) -> None:
    """Give a basic fixture normalized status, risk, ZSK and financial rows."""
    raw_financial: dict[str, object] = {
        "common": {"year": year, "proceeds": str(proceeds)},
        "assets": {},
        "liabilities": {},
    }
    if profit_present:
        raw_financial["common"] = {
            "year": year,
            "proceeds": str(proceeds),
            "profit": "10",
        }
    with Session(engine) as session:
        snapshot = session.scalar(select(ReportSnapshot).where(ReportSnapshot.id == report_id))
        assert snapshot is not None
        snapshot.raw_jsonb = {
            "baseInfo": {"riskLevel": "LOW"},
            "status": {"status": "ACTIVE"},
            "zskRiskLevel": "GREEN",
            "finReports": [raw_financial],
        }
        profile = session.get(CompanyProfile, report_id)
        assert profile is not None
        profile.bank_risk_raw = "LOW"
        session.add(CompanyStatus(report_id=report_id, status_raw="ACTIVE", extra_jsonb={}))
        session.add(
            ZskAssessment(
                report_id=report_id,
                raw_value="GREEN",
                display_policy_version="zsk-display/1",
                source_path="/zskRiskLevel",
            )
        )
        session.add(
            FinancialStatement(
                id=uuid4(),
                report_id=report_id,
                year=year,
                ordinal=0,
                proceeds=proceeds,
                profit=Decimal("10") if profit_present else None,
                source_path="/finReports/0",
                extra_jsonb={},
            )
        )
        session.commit()


def test_overview_uses_exact_snapshot_and_resolvable_evidence(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A newer import cannot move an overview requested by pinned report id."""
    sign_in()
    company_id, pinned = add_reported_company(clean, inn="7449088645", short_name="Ромашка")
    _fill_report(clean, pinned, year=2025, proceeds=Decimal("0"), profit_present=False)
    newer = add_snapshot(
        clean,
        company_id=company_id,
        reported_at=datetime(2027, 1, 1, tzinfo=UTC),
        short_name="Новая Ромашка",
    )

    response = client.get(f"/api/v1/reports/{pinned}/overview")

    assert response.status_code == 200, response.text
    overview = response.json()
    assert overview["report"]["id"] == str(pinned)
    assert overview["report"]["id"] != str(newer)
    proceeds = next(fact for fact in overview["facts"] if fact["key"].endswith(".proceeds"))
    profit = next(fact for fact in overview["facts"] if fact["key"].endswith(".profit"))
    assert (proceeds["value"], proceeds["availability"]) == ("0.00", "available")
    assert (profit["value"], profit["availability"]) == (None, "missing")
    assert resolve_report_evidence_id(proceeds["evidence_refs"][0]) == (
        pinned,
        "/finReports/0/common/proceeds",
    )


def test_comparison_preserves_requested_order_periods_and_partial_rows(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """Two pinned reports keep request order and expose differing latest years."""
    sign_in()
    _, first = add_reported_company(clean, inn="7449088645", short_name="Первая")
    _, second = add_reported_company(clean, inn="7702070139", short_name="Вторая")
    _fill_report(clean, first, year=2024, proceeds=Decimal("100"))
    _fill_report(clean, second, year=2025, proceeds=Decimal("200"), profit_present=False)
    project = _project(client)
    _pin(client, project["id"], ["7449088645", "7702070139"])

    response = client.post(
        f"/api/v1/projects/{project['id']}/comparisons",
        json={
            "report_ids": [str(second), str(first)],
            "criteria": ["status", "financials"],
            "year_policy": "latest_available",
        },
    )

    assert response.status_code == 200, response.text
    comparison = response.json()
    assert [row["report"]["id"] for row in comparison["rows"]] == [str(second), str(first)]
    assert [row["status"] for row in comparison["rows"]] == ["partial", "partial"]
    assert comparison["warnings"][0]["code"] == "period_mismatch"
    assert not ({"score", "winner_id", "rank"} & comparison.keys())

    with Session(clean) as session:
        invalid = session.get(ReportSnapshot, second)
        assert invalid is not None
        invalid.ingestion_status = IngestionStatus.INVALID
        session.commit()
    degraded = client.post(
        f"/api/v1/projects/{project['id']}/comparisons",
        json={
            "report_ids": [str(first), str(second)],
            "criteria": ["status"],
            "year_policy": "latest_available",
        },
    )
    assert degraded.status_code == 200, degraded.text
    assert [row["report"]["id"] for row in degraded.json()["rows"]] == [
        str(first),
        str(second),
    ]
    assert degraded.json()["rows"][1]["status"] == "unavailable"


def test_comparison_accepts_twenty_and_rejects_foreign_report(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The upper bound is complete and project membership is enforced."""
    sign_in()
    inns = [f"77000000{index:02d}" for index in range(20)]
    reports: list[UUID] = []
    for index, inn in enumerate(inns):
        _, report_id = add_reported_company(clean, inn=inn, short_name=f"Компания {index}")
        _fill_report(clean, report_id, year=2025, proceeds=Decimal(index))
        reports.append(report_id)
    project = _project(client)
    _pin(client, project["id"], inns)

    response = client.post(
        f"/api/v1/projects/{project['id']}/comparisons",
        json={
            "report_ids": [str(report_id) for report_id in reversed(reports)],
            "criteria": ["status"],
            "year_policy": "latest_available",
        },
    )

    assert response.status_code == 200, response.text
    assert [row["report"]["id"] for row in response.json()["rows"]] == [
        str(report_id) for report_id in reversed(reports)
    ]

    _, foreign = add_reported_company(clean, inn="7801265392", short_name="Вне проекта")
    refused = client.post(
        f"/api/v1/projects/{project['id']}/comparisons",
        json={
            "report_ids": [str(reports[0]), str(foreign)],
            "criteria": ["status"],
            "year_policy": "latest_available",
        },
    )
    assert refused.status_code == 404
