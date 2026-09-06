"""The session-less internal endpoint the agent calls to pin a company by INN.

The agent has no browser session, so this endpoint trades the ownership
dependencies for one shared token and reads the tenant from the project row.
Everything below runs against PostgreSQL because the rules under test —
snapshot pinning and the context-version bump — are database behaviour.
"""

from uuid import uuid4

from conftest import SignIn, add_company, add_reported_company
from fastapi.testclient import TestClient
from sqlalchemy import Engine

TOKEN = "test-internal-token"


def _project(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects", json={"title": "Проверка", "client_request_id": str(uuid4())}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _add(client: TestClient, project_id: str, inn: str, *, token: str | None = TOKEN):  # type: ignore[no-untyped-def]
    headers = {} if token is None else {"X-Internal-Token": token}
    return client.post(
        f"/api/v1/internal/projects/{project_id}/companies",
        json={"inn": inn},
        headers=headers,
    )


def _composition(client: TestClient, project_id: str) -> dict[str, object]:
    """Read the project's current counterparties and context version."""
    response = client.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_a_known_inn_is_pinned_and_advances_the_deal_context(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The company is added, pinned to its latest snapshot, and the version moves."""
    sign_in()
    project_id = _project(client)
    add_reported_company(clean, inn="7449088645", short_name="Ромашка")

    response = _add(client, project_id, "7449088645")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "added"
    assert body["name"] == "Ромашка"

    composition = _composition(client, project_id)
    assert [row["inn"] for row in composition["companies"]] == ["7449088645"]
    assert composition["context_version"] == 1


def test_pinning_the_same_company_twice_is_not_an_error(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A repeat call reports ``already_present`` and does not bump the version again."""
    sign_in()
    project_id = _project(client)
    add_reported_company(clean, inn="7449088645", short_name="Ромашка")

    first = _add(client, project_id, "7449088645")
    second = _add(client, project_id, "7449088645")

    assert first.json()["outcome"] == "added"
    assert second.status_code == 200
    assert second.json()["outcome"] == "already_present"
    assert _composition(client, project_id)["context_version"] == 1


def test_an_unknown_inn_is_reported_not_found_without_writing(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A company outside the local index is a 200 outcome, not a write or a 500."""
    sign_in()
    project_id = _project(client)

    response = _add(client, project_id, "0000000000")

    assert response.status_code == 200
    assert response.json()["outcome"] == "not_found"


def test_a_company_without_a_snapshot_is_reported_no_report(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """An indexed company with no held report cannot be pinned."""
    sign_in()
    project_id = _project(client)
    add_company(clean, inn="7702070139")

    response = _add(client, project_id, "7702070139")

    assert response.status_code == 200
    assert response.json()["outcome"] == "no_report"


def test_a_wrong_or_missing_token_is_refused(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """Without the shared secret the endpoint answers 401 and touches nothing."""
    sign_in()
    project_id = _project(client)
    add_reported_company(clean, inn="7449088645")

    assert _add(client, project_id, "7449088645", token="wrong").status_code == 401
    assert _add(client, project_id, "7449088645", token=None).status_code == 401
    assert _composition(client, project_id)["companies"] == []


def test_an_unknown_project_is_not_found(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A project id that does not exist is a 404, even with a valid token."""
    sign_in()

    response = _add(client, str(uuid4()), "7449088645")

    assert response.status_code == 404
