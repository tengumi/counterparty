"""Creating, listing, opening and renaming a check against PostgreSQL.

The idempotency assertions are the point of running this against a real
database: the guarantee is the primary key of ``workspace.idempotency_keys``,
so a test that mocked the store would prove nothing about it.
"""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from conftest import ANALYST, SignIn
from counterparty_storage.workspace.enums import IdempotencyState
from counterparty_storage.workspace.models import IdempotencyKey
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from counterparty_ui_api.idempotency import fingerprint_of
from counterparty_ui_api.projects import CREATE_SCOPE


def _create(client: TestClient, **payload: object) -> dict[str, object]:
    """Create one project and return its body, failing loudly otherwise."""
    body = {"client_request_id": str(uuid4()), **payload}
    response = client.post("/api/v1/projects", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_creating_a_check_also_creates_its_first_chat(client: TestClient, sign_in: SignIn) -> None:
    """A project is usable immediately: it opens with one chat and no history."""
    sign_in()

    project = _create(client, title="Ромашка")

    assert project["title"] == "Ромашка"
    assert project["default_thread_id"] is not None
    assert project["threads_count"] == 1
    assert project["context_version"] == 0
    assert project["companies"] == []
    assert project["workflow_status"] == "in_progress"


def test_the_first_question_names_the_check_when_no_title_is_given(
    client: TestClient, sign_in: SignIn
) -> None:
    """The user's own words become the name; they are shortened, not reworded."""
    sign_in()

    project = _create(client, initial_question="Можно ли платить аванс 80% этой компании?")

    assert project["title"] == "Можно ли платить аванс 80% этой компании?"


def test_repeating_a_request_id_returns_the_first_project(
    client: TestClient, sign_in: SignIn
) -> None:
    """A retried create returns the first project instead of a second one."""
    sign_in()
    request_id = str(uuid4())
    body = {"title": "Проверка", "client_request_id": request_id}

    first = client.post("/api/v1/projects", json=body)
    second = client.post("/api/v1/projects", json=body)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["idempotent-replay"] == "true"
    assert second.json()["id"] == first.json()["id"]
    listed = client.get("/api/v1/projects").json()
    assert len(listed["items"]) == 1


def test_a_request_id_reused_for_another_payload_is_refused(
    client: TestClient, sign_in: SignIn
) -> None:
    """Replaying the first project would silently discard this request."""
    sign_in()
    request_id = str(uuid4())
    first = client.post(
        "/api/v1/projects", json={"title": "Первая", "client_request_id": request_id}
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/projects", json={"title": "Другая", "client_request_id": request_id}
    )

    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "conflict"
    assert body["details"]["reason"] == "request_id_reused"
    assert len(client.get("/api/v1/projects").json()["items"]) == 1


def test_a_request_arriving_while_the_first_one_runs_is_told_so(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """An in-flight reservation answers "still running", not "here is a copy"."""
    sign_in()
    request_id = uuid4()
    body = {"title": "Проверка", "client_request_id": str(request_id)}
    with Session(clean) as session:
        session.add(
            IdempotencyKey(
                tenant_id=UUID(str(ANALYST.tenant_id)),
                scope=CREATE_SCOPE,
                client_request_id=request_id,
                request_fingerprint=fingerprint_of(
                    {
                        "title": "Проверка",
                        "initial_question": None,
                        "owner": str(ANALYST.user_id),
                    }
                ),
                state=IdempotencyState.IN_FLIGHT,
                resource_kind="project",
            )
        )
        session.commit()

    response = client.post("/api/v1/projects", json=body)

    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "request_in_flight"
    assert response.json()["retryable"] is True
    assert client.get("/api/v1/projects").json()["items"] == []


def test_two_simultaneous_copies_create_exactly_one_project(
    client: TestClient, sign_in: SignIn
) -> None:
    """Two copies of one request race for one row; only one of them wins."""
    sign_in()
    body = {"title": "Одновременно", "client_request_id": str(uuid4())}

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [
            future.result()
            for future in [
                pool.submit(client.post, "/api/v1/projects", json=body) for _ in range(2)
            ]
        ]

    statuses = sorted(response.status_code for response in responses)
    assert statuses[0] == 201, [response.text for response in responses]
    assert statuses[1] in {200, 409}
    assert len(client.get("/api/v1/projects").json()["items"]) == 1


def test_the_list_is_ordered_by_activity_and_pages_by_cursor(
    client: TestClient, sign_in: SignIn
) -> None:
    """Paging visits every project exactly once, newest activity first."""
    sign_in()
    created = [_create(client, title=f"Проверка {index}")["id"] for index in range(3)]

    first = client.get("/api/v1/projects", params={"limit": 2}).json()
    assert [item["id"] for item in first["items"]] == list(reversed(created))[:2]
    assert first["page"]["has_more"] is True

    second = client.get(
        "/api/v1/projects", params={"limit": 2, "cursor": first["page"]["next_cursor"]}
    ).json()
    assert [item["id"] for item in second["items"]] == [created[0]]
    assert second["page"]["has_more"] is False


def test_a_cursor_the_server_did_not_issue_is_refused(client: TestClient, sign_in: SignIn) -> None:
    """A broken cursor is not quietly treated as "start from the beginning"."""
    sign_in()

    response = client.get("/api/v1/projects", params={"cursor": "not-a-cursor"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_renaming_keeps_the_deal_context_where_it_was(client: TestClient, sign_in: SignIn) -> None:
    """A rename is not a change of the deal, so no conclusion goes outdated."""
    sign_in()
    project = _create(client, title="Черновик")

    renamed = client.patch(f"/api/v1/projects/{project['id']}", json={"title": "Ромашка"})

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Ромашка"
    assert renamed.json()["context_version"] == project["context_version"]


def test_another_tenants_check_is_neither_listed_nor_openable(
    client: TestClient, sign_in: SignIn
) -> None:
    """A project of another tenant is indistinguishable from a missing one."""
    sign_in("demo-analyst")
    theirs = _create(client, title="Чужая проверка")["id"]
    client.delete("/api/v1/auth/session")
    sign_in("demo-partner")

    listed = client.get("/api/v1/projects").json()
    opened = client.get(f"/api/v1/projects/{theirs}")
    missing = client.get(f"/api/v1/projects/{uuid4()}")

    assert listed["items"] == []
    assert opened.status_code == 404
    assert opened.json()["message"] == missing.json()["message"]


def test_creating_a_check_requires_a_session(client: TestClient) -> None:
    """Ownership is never evaluated for an unauthenticated caller."""
    response = client.post(
        "/api/v1/projects", json={"title": "Проверка", "client_request_id": str(uuid4())}
    )

    assert response.status_code == 401
