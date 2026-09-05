"""REST report pages and evidence against isolated real PostgreSQL."""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from conftest import SignIn, add_reported_company, add_snapshot
from counterparty_storage.reports.enums import IngestionStatus, SourceState
from counterparty_storage.reports.models import ReportSnapshot, SectionAvailability
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session


def _source(engine: Engine, report_id: UUID, raw: dict[str, Any]) -> None:
    with Session(engine) as session:
        report = session.get(ReportSnapshot, report_id)
        assert report is not None
        report.raw_jsonb = raw
        for key, value in raw.items():
            session.add(
                SectionAvailability(
                    report_id=report_id,
                    section=key,
                    source_state=SourceState.PRESENT_EMPTY
                    if value in (None, [], {})
                    else SourceState.PRESENT,
                    record_count=len(value) if isinstance(value, list) else 1,
                    source_path="/" + key,
                )
            )
        session.commit()


def _project(client: TestClient, inn: str) -> dict[str, Any]:
    response = client.post("/api/v1/projects", json={"client_request_id": str(uuid4())})
    assert response.status_code == 201, response.text
    project: dict[str, Any] = response.json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/companies",
        json={"items": [{"inn": inn}], "expected_context_version": 0},
    )
    assert response.status_code == 200, response.text
    return project


def _evidence(project: dict[str, Any], ref: str) -> str:
    return f"/api/v1/projects/{project['id']}/evidence/{quote(ref, safe='')}"


def test_section_pagination_and_resolvable_refs(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """Every numbered source row is reachable through an authorized reference."""
    sign_in()
    _, report_id = add_reported_company(clean, inn="7449088645", short_name="Компания")
    _source(
        clean,
        report_id,
        {
            "executionProceedings": [
                {"active": True, "amount": 0},
                {"active": False},
                {"active": True, "amount": None},
            ]
        },
    )
    project = _project(client, "7449088645")
    url = f"/api/v1/reports/{report_id}/sections/execution_proceedings"
    first = client.get(url, params={"limit": 1, "active": "true"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["total_records"] == 2 and body["page"]["has_more"]
    assert body["records"][0]["amount"]["value"] == "0"
    next_page = client.get(
        url, params={"limit": 2, "active": "true", "cursor": body["page"]["next_cursor"]}
    )
    assert next_page.status_code == 200, next_page.text
    record = next_page.json()["records"][0]
    assert record["amount"]["availability"] == "present_empty"
    ref = record["amount"]["evidence_refs"][0]
    resolved = client.get(_evidence(project, ref))
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["value"] is None
    assert resolved.json()["availability"] == "present_empty"
    wrong = client.get(url, params={"active": "false", "cursor": body["page"]["next_cursor"]})
    assert wrong.status_code == 422, wrong.text


def test_evidence_scope_history_and_pinned_snapshot(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """Tenant, user and project scope survive removal and a newer corpus import."""
    sign_in()
    company_id, report_id = add_reported_company(clean, inn="7449088645")
    _source(clean, report_id, {"licenses": [{"number": "old-license"}]})
    project = _project(client, "7449088645")
    other = client.post("/api/v1/projects", json={"client_request_id": str(uuid4())}).json()
    ref = f"report:{report_id}:/licenses/0"
    assert client.get(_evidence(other, ref)).status_code == 404
    newer = add_snapshot(clean, company_id=company_id, reported_at=datetime(2027, 1, 1, tzinfo=UTC))
    _source(clean, newer, {"licenses": [{"number": "new-license"}]})
    assert client.get(_evidence(project, f"report:{newer}:/licenses/0")).status_code == 404
    removed = client.request(
        "DELETE",
        f"/api/v1/projects/{project['id']}/companies/{company_id}",
        json={"expected_context_version": 1},
    )
    assert removed.status_code == 200, removed.text
    assert client.get(_evidence(project, ref)).json()["value"]["number"] == "old-license"
    for login in ("demo-partner", "demo-colleague"):
        sign_in(login)
        assert client.get(_evidence(project, ref)).status_code == 404


@pytest.mark.parametrize(
    "query",
    [{"limit": 101}, {"unknown": "x"}, {"active": True}, {"years": 2025}, {"cursor": "garbage"}],
)
def test_rejects_invalid_section_queries(
    client: TestClient, clean: Engine, sign_in: SignIn, query: dict[str, Any]
) -> None:
    """Unsupported filters are errors rather than ignored narrowing."""
    sign_in()
    _, report_id = add_reported_company(clean, inn="7449088645")
    _source(clean, report_id, {"licenses": [{"number": "x"}]})
    response = client.get(f"/api/v1/reports/{report_id}/sections/licenses", params=query)
    assert response.status_code == 422, response.text


def test_unavailable_source_and_unauthenticated_are_distinct(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """An invalid report remains explicit and no authentication means no data."""
    _, report_id = add_reported_company(clean, inn="7449088645")
    url = f"/api/v1/reports/{report_id}/sections/licenses"
    assert client.get(url).status_code == 401
    sign_in()
    assert client.get(url).json()["availability"] == "missing"
    _source(clean, report_id, {"licenses": []})
    assert client.get(url).json()["availability"] == "present_empty"
    with Session(clean) as session:
        report = session.get(ReportSnapshot, report_id)
        assert report is not None
        report.ingestion_status = IngestionStatus.INVALID
        session.commit()
    response = client.get(url)
    assert response.status_code == 200, response.text
    assert response.json()["availability"] == "invalid"
    assert response.json()["total_records"] is None


def test_forged_and_oversized_evidence_are_refused(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A project member cannot use an arbitrary pointer to dump the raw snapshot."""
    sign_in()
    _, report_id = add_reported_company(clean, inn="7449088645")
    _source(
        clean,
        report_id,
        {
            "licenses": [{"number": "x" * 70000, "unpublished": "private shape"}],
            "internal": {"key": "never projected"},
        },
    )
    project = _project(client, "7449088645")
    for path in ("/internal/key", "/licenses/0/unpublished", "/", "/licenses/00"):
        assert client.get(_evidence(project, f"report:{report_id}:{path}")).status_code == 404
    response = client.get(_evidence(project, f"report:{report_id}:/licenses/0"))
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "limit_exceeded"
