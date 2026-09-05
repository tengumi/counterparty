"""Adding and removing the counterparties of one check, against PostgreSQL.

Three properties are only real if the database enforces them, so they are
exercised here rather than argued about: the pinned snapshot does not follow a
later import, the twenty-slot limit is a database rule, and removing a
counterparty keeps its row and its snapshot.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from conftest import SignIn, add_company, add_reported_company, add_snapshot
from counterparty_storage.workspace.models import ProjectCompany
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session


def _project(client: TestClient) -> dict[str, object]:
    """Create one check to add counterparties to."""
    response = client.post(
        "/api/v1/projects", json={"title": "Проверка", "client_request_id": str(uuid4())}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _add(client: TestClient, project_id: object, items: list[dict[str, str]], version: int = 0):  # type: ignore[no-untyped-def]
    """Send one add-companies batch."""
    return client.post(
        f"/api/v1/projects/{project_id}/companies",
        json={"items": items, "expected_context_version": version},
    )


def test_the_local_index_answers_by_inn_and_reports_its_latest_snapshot(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """Search reads what we already hold; it performs no external lookup."""
    sign_in()
    company_id, report_id = add_reported_company(clean, inn="7449088645", short_name="Ромашка")

    found = client.get("/api/v1/companies", params={"inn": "7449088645"}).json()
    missing = client.get("/api/v1/companies", params={"inn": "0000000000"}).json()

    assert [item["company_id"] for item in found["items"]] == [str(company_id)]
    assert found["items"][0]["latest_report_id"] == str(report_id)
    assert found["items"][0]["short_name"] == "Ромашка"
    assert missing["items"] == []


def test_a_company_without_a_reported_name_is_shown_by_its_inn(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A missing name is not invented, and it does not hide the company."""
    sign_in()
    add_reported_company(clean, inn="7702070139")

    found = client.get("/api/v1/companies", params={"inn": "7702070139"}).json()

    assert found["items"][0]["short_name"] == "7702070139"


def test_adding_a_counterparty_pins_the_snapshot_it_is_judged_on(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A newer import does not change what the check is reasoning about."""
    sign_in()
    project = _project(client)
    company_id, pinned = add_reported_company(clean, inn="7449088645", short_name="Ромашка")

    added = _add(client, project["id"], [{"inn": "7449088645"}])
    assert added.status_code == 200, added.text
    assert added.json()["results"][0]["outcome"] == "added"
    assert added.json()["companies"][0]["report_id"] == str(pinned)

    newer = add_snapshot(
        clean,
        company_id=company_id,
        reported_at=datetime(2027, 1, 1, tzinfo=UTC),
        short_name="Ромашка",
    )
    reopened = client.get(f"/api/v1/projects/{project['id']}").json()

    assert reopened["companies"][0]["report_id"] == str(pinned)
    assert str(newer) != str(pinned)
    assert client.get("/api/v1/companies", params={"inn": "7449088645"}).json()["items"][0][
        "latest_report_id"
    ] == str(newer)


def test_adding_counterparties_advances_the_deal_context(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The composition is part of the deal context, so the version moves once."""
    sign_in()
    project = _project(client)
    add_reported_company(clean, inn="7449088645")
    add_reported_company(clean, inn="7702070139")

    added = _add(client, project["id"], [{"inn": "7449088645"}, {"inn": "7702070139"}])

    assert added.json()["context_version"] == 1
    assert len(added.json()["companies"]) == 2


def test_one_unusable_row_does_not_cancel_the_valid_ones(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """Each item is answered on its own, and nothing is invented for the rest."""
    sign_in()
    project = _project(client)
    add_reported_company(clean, inn="7449088645")
    without_report = add_company(clean, inn="7702070139")

    added = _add(
        client,
        project["id"],
        [
            {"inn": "7449088645"},
            {"inn": "0000000000"},
            {"company_id": str(without_report)},
            {"inn": "7449088645"},
        ],
    )

    outcomes = [result["outcome"] for result in added.json()["results"]]
    assert outcomes == ["added", "not_found", "invalid", "already_present"]
    errors = [result["error_code"] for result in added.json()["results"]]
    assert errors == [None, "not_found", "source_missing", None]
    assert len(added.json()["companies"]) == 1


def test_a_batch_that_would_exceed_twenty_is_refused_as_a_whole(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """An arbitrary first N would silently drop the rest of the request."""
    sign_in()
    project = _project(client)
    inns = [f"77000000{index:02d}" for index in range(21)]
    for inn in inns:
        add_reported_company(clean, inn=inn)

    filled = _add(client, project["id"], [{"inn": inn} for inn in inns[:20]])
    assert filled.status_code == 200, filled.text
    assert len(filled.json()["companies"]) == 20

    overflow = _add(client, project["id"], [{"inn": inns[20]}], version=1)

    assert overflow.status_code == 409
    assert overflow.json()["code"] == "limit_exceeded"
    assert overflow.json()["details"]["limit"] == 20
    assert len(client.get(f"/api/v1/projects/{project['id']}").json()["companies"]) == 20


def test_a_batch_larger_than_the_free_slots_adds_nothing(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The refusal happens before any row is written, not halfway through it."""
    sign_in()
    project = _project(client)
    inns = [f"770000{index:04d}" for index in range(22)]
    for inn in inns:
        add_reported_company(clean, inn=inn)
    filled = _add(client, project["id"], [{"inn": inn} for inn in inns[:12]])
    assert filled.status_code == 200, filled.text

    refused = _add(client, project["id"], [{"inn": inn} for inn in inns[12:]], version=1)

    assert refused.status_code == 409
    assert refused.json()["details"] == {"limit": 20, "in_project": 12, "requested_new": 10}
    assert len(client.get(f"/api/v1/projects/{project['id']}").json()["companies"]) == 12


def test_removing_a_counterparty_keeps_what_was_reviewed(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The row and its pinned snapshot survive; only the composition changes."""
    sign_in()
    project = _project(client)
    company_id, pinned = add_reported_company(clean, inn="7449088645")
    _add(client, project["id"], [{"inn": "7449088645"}])

    removed = client.request(
        "DELETE",
        f"/api/v1/projects/{project['id']}/companies/{company_id}",
        json={"expected_context_version": 1},
    )

    assert removed.status_code == 200, removed.text
    assert removed.json()["companies"] == []
    assert removed.json()["context_version"] == 2
    with Session(clean) as session:
        rows = list(
            session.execute(
                select(ProjectCompany).where(ProjectCompany.company_id == company_id)
            ).scalars()
        )
    assert len(rows) == 1
    assert rows[0].removed_at is not None
    assert rows[0].report_id == pinned


def test_a_removed_counterparty_can_return_without_erasing_its_history(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """Re-adding writes a new row; the earlier membership stays on record."""
    sign_in()
    project = _project(client)
    company_id, _ = add_reported_company(clean, inn="7449088645")
    _add(client, project["id"], [{"inn": "7449088645"}])
    client.request(
        "DELETE",
        f"/api/v1/projects/{project['id']}/companies/{company_id}",
        json={"expected_context_version": 1},
    )

    again = _add(client, project["id"], [{"inn": "7449088645"}], version=2)

    assert again.status_code == 200, again.text
    with Session(clean) as session:
        rows = list(
            session.execute(
                select(ProjectCompany).where(ProjectCompany.company_id == company_id)
            ).scalars()
        )
    assert len(rows) == 2
    assert sum(1 for row in rows if row.removed_at is None) == 1


def test_removing_a_counterparty_that_is_not_in_the_check_is_a_refusal(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """An absent counterparty is reported, not silently accepted as removed."""
    sign_in()
    project = _project(client)

    response = client.request(
        "DELETE",
        f"/api/v1/projects/{project['id']}/companies/{uuid4()}",
        json={"expected_context_version": 0},
    )

    assert response.status_code == 404


def test_a_stale_context_version_is_a_conflict_with_the_current_one(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The caller re-reads instead of overwriting someone else's change."""
    sign_in()
    project = _project(client)
    add_reported_company(clean, inn="7449088645")
    _add(client, project["id"], [{"inn": "7449088645"}])

    stale = _add(client, project["id"], [{"inn": "7449088645"}], version=0)

    assert stale.status_code == 409
    assert stale.json()["code"] == "conflict"
    assert stale.json()["details"] == {"expected_context_version": 0, "context_version": 1}


def test_counterparties_of_another_tenants_check_are_out_of_reach(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A foreign project is not addressable, in either direction."""
    sign_in("demo-analyst")
    project = _project(client)
    company_id, _ = add_reported_company(clean, inn="7449088645")
    client.delete("/api/v1/auth/session")
    sign_in("demo-partner")

    added = _add(client, project["id"], [{"inn": "7449088645"}])
    removed = client.request(
        "DELETE",
        f"/api/v1/projects/{project['id']}/companies/{company_id}",
        json={"expected_context_version": 0},
    )

    assert added.status_code == 404
    assert removed.status_code == 404


def test_the_composition_survives_a_reopen(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """What the project holds is read back the same way it was written."""
    sign_in()
    project = _project(client)
    company_id, report_id = add_reported_company(clean, inn="7449088645", short_name="Ромашка")
    _add(client, project["id"], [{"company_id": str(company_id)}])

    reopened = client.get(f"/api/v1/projects/{project['id']}").json()

    assert reopened["context_version"] == 1
    assert reopened["companies"] == [
        {
            "company_id": str(company_id),
            "report_id": str(report_id),
            "inn": "7449088645",
            "short_name": "Ромашка",
            "role": "unknown",
            "shortlisted": False,
            "added_at": reopened["companies"][0]["added_at"],
        }
    ]
    assert isinstance(UUID(reopened["companies"][0]["company_id"]), UUID)
