"""Demo sign-in issues a real session, and ownership is genuinely checked."""

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from counterparty_contracts import ProjectId, ThreadId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from counterparty_ui_api.app import create_app
from counterparty_ui_api.config import DemoUser, Settings
from counterparty_ui_api.dependencies import ScopedProject, ScopedThread
from counterparty_ui_api.sessions import InMemorySessionStore
from counterparty_ui_api.workspace import InMemoryProjectDirectory

ANALYST = DemoUser.model_validate(
    {
        "tenant_id": "00000000-0000-4000-8000-0000000000e1",
        "user_id": "00000000-0000-4000-8000-0000000000a1",
        "display_name": "Демо-аналитик",
    }
)
PARTNER = DemoUser.model_validate(
    {
        "tenant_id": "00000000-0000-4000-8000-0000000000e2",
        "user_id": "00000000-0000-4000-8000-0000000000a2",
        "display_name": "Демо-партнёр",
    }
)
ANALYST_PROJECT = ProjectId(UUID("00000000-0000-4000-8000-0000000000c1"))
PARTNER_PROJECT = ProjectId(UUID("00000000-0000-4000-8000-0000000000c2"))
ANALYST_THREAD = ThreadId(UUID("00000000-0000-4000-8000-0000000000d1"))
FOREIGN_THREAD = ThreadId(UUID("00000000-0000-4000-8000-0000000000d2"))

SETTINGS = Settings(
    demo_users={"demo-analyst": ANALYST, "demo-partner": PARTNER},
    session_cookie_secure=False,
)


def _directory() -> InMemoryProjectDirectory:
    """Register one project per demo tenant, with one thread each."""
    directory = InMemoryProjectDirectory()
    directory.add_project(
        project_id=ANALYST_PROJECT,
        tenant_id=ANALYST.tenant_id,
        owner_user_id=ANALYST.user_id,
    )
    directory.add_thread(project_id=ANALYST_PROJECT, thread_id=ANALYST_THREAD)
    directory.add_project(
        project_id=PARTNER_PROJECT,
        tenant_id=PARTNER.tenant_id,
        owner_user_id=PARTNER.user_id,
    )
    directory.add_thread(project_id=PARTNER_PROJECT, thread_id=FOREIGN_THREAD)
    return directory


def _probe_app(settings: Settings = SETTINGS) -> FastAPI:
    """Build the application with two probe routes over the real dependencies.

    The probes exist so the scope dependencies can be exercised before the
    business endpoints that will use them are written.
    """
    application = create_app(
        settings=settings,
        session_store=InMemorySessionStore(),
        project_directory=_directory(),
    )

    @application.get("/api/v1/projects/{project_id}/_probe")
    async def project_probe(scope: ScopedProject) -> dict[str, str]:
        return {"project_id": str(scope.project_id), "tenant_id": str(scope.tenant_id)}

    @application.get("/api/v1/projects/{project_id}/threads/{thread_id}/_probe")
    async def thread_probe(scope: ScopedThread) -> dict[str, str]:
        return {"thread_id": str(scope.thread_id)}

    return application


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Run the probe application with its real lifespan."""
    with TestClient(_probe_app()) as test_client:
        yield test_client


def _sign_in(client: TestClient, login: str) -> None:
    """Sign one demo identity in, keeping the cookie on the client."""
    response = client.post("/api/v1/auth/session", json={"login": login})
    assert response.status_code == 201


def test_sign_in_sets_an_http_only_cookie_and_never_returns_the_token(
    client: TestClient,
) -> None:
    """The token stays in the cookie; the body carries identity only."""
    response = client.post("/api/v1/auth/session", json={"login": "demo-analyst"})

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == str(ANALYST.tenant_id)
    assert body["demo"] is True
    assert "token" not in body
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header
    assert client.cookies["cp_session"] not in response.text


def test_unknown_login_is_refused_as_an_error_dto(client: TestClient) -> None:
    """A refusal carries a stable code and its request id, not a traceback."""
    response = client.post("/api/v1/auth/session", json={"login": "someone-else"})

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "unauthorized"
    assert body["request_id"] == response.headers["x-request-id"]


def test_demo_sign_in_can_be_switched_off() -> None:
    """A deployment without demo access refuses the demo login outright."""
    disabled = Settings(demo_auth_enabled=False, demo_users={"demo-analyst": ANALYST})
    with TestClient(_probe_app(disabled)) as client:
        response = client.post("/api/v1/auth/session", json={"login": "demo-analyst"})

    assert response.status_code == 403


def test_session_endpoint_requires_a_session(client: TestClient) -> None:
    """Without a cookie there is no caller to report."""
    response = client.get("/api/v1/auth/session")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_sign_out_revokes_the_session_server_side(client: TestClient) -> None:
    """The session stops working even if the token is presented again."""
    _sign_in(client, "demo-analyst")
    token = client.cookies["cp_session"]
    assert client.get("/api/v1/auth/session").status_code == 200

    assert client.delete("/api/v1/auth/session").status_code == 204

    client.cookies.set("cp_session", token)
    assert client.get("/api/v1/auth/session").status_code == 401


def test_forged_token_does_not_authorize(client: TestClient) -> None:
    """A cookie the server never issued opens nothing."""
    client.cookies.set("cp_session", "not-a-real-token")

    assert client.get("/api/v1/auth/session").status_code == 401


def test_owner_reaches_their_own_project(client: TestClient) -> None:
    """The verified scope carries the tenant the server resolved."""
    _sign_in(client, "demo-analyst")

    response = client.get(f"/api/v1/projects/{ANALYST_PROJECT}/_probe")

    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(ANALYST.tenant_id)


def test_project_of_another_tenant_is_reported_as_not_found(client: TestClient) -> None:
    """A foreign project is not distinguishable from a missing one."""
    _sign_in(client, "demo-analyst")

    foreign = client.get(f"/api/v1/projects/{PARTNER_PROJECT}/_probe")
    missing = client.get(f"/api/v1/projects/{uuid4()}/_probe")

    assert foreign.status_code == 404
    assert foreign.json()["code"] == "not_found"
    assert foreign.json()["message"] == missing.json()["message"]


def test_project_access_requires_a_session(client: TestClient) -> None:
    """Ownership is never evaluated for an unauthenticated caller."""
    response = client.get(f"/api/v1/projects/{ANALYST_PROJECT}/_probe")

    assert response.status_code == 401


def test_thread_of_another_project_is_not_reachable(client: TestClient) -> None:
    """A thread is usable only inside the project it belongs to."""
    _sign_in(client, "demo-analyst")

    own = client.get(f"/api/v1/projects/{ANALYST_PROJECT}/threads/{ANALYST_THREAD}/_probe")
    foreign = client.get(f"/api/v1/projects/{ANALYST_PROJECT}/threads/{FOREIGN_THREAD}/_probe")

    assert own.status_code == 200
    assert foreign.status_code == 404


def test_invalid_body_is_reported_without_echoing_it(client: TestClient) -> None:
    """A rejected body may hold a credential, so its values are not returned."""
    response = client.post("/api/v1/auth/session", json={"login": "x", "password": "hunter2"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert "hunter2" not in response.text
