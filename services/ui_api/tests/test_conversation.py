"""Reading the stored conversation projection of one thread, against PostgreSQL.

This service does not hold the message projection, so the endpoint's job is
narrow: prove the thread belongs to the project, return an empty-but-valid
projection, and surface the run the UI can reconnect to.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from conftest import ANALYST, SignIn
from counterparty_storage.workspace.enums import AgentRunStatus
from counterparty_storage.workspace.models import AgentRun
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session


def _project(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/projects", json={"client_request_id": str(uuid4()), "title": "Проверка"}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _add_run(
    engine: Engine,
    *,
    project_id: str,
    thread_id: str,
    status: AgentRunStatus,
    started_at: datetime,
    revision: int = 0,
) -> str:
    run_id = uuid4()
    finished = (
        None
        if status
        in {
            AgentRunStatus.ACCEPTED,
            AgentRunStatus.RUNNING,
            AgentRunStatus.CANCELLING,
        }
        else started_at + timedelta(minutes=1)
    )
    with Session(engine) as session:
        session.add(
            AgentRun(
                id=run_id,
                tenant_id=ANALYST.tenant_id,
                project_id=project_id,
                thread_id=thread_id,
                owner_id=uuid4(),
                client_request_id=uuid4(),
                status=status,
                started_at=started_at,
                finished_at=finished,
                based_on_context_version=0,
                last_public_revision=revision,
            )
        )
        session.commit()
    return str(run_id)


def test_a_fresh_thread_has_an_empty_but_valid_projection(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """No run and no history: the chat is empty, not failed to load."""
    sign_in()
    project = _project(client)

    response = client.get(
        f"/api/v1/projects/{project['id']}/threads/{project['default_thread_id']}/conversation"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["messages"] == []
    assert body["activities"] == []
    assert body["run"] is None
    assert body["active_run_id"] is None
    assert body["project_id"] == project["id"]
    assert body["thread_id"] == project["default_thread_id"]
    assert body["context_version"] == 0


def test_a_thread_of_another_project_is_not_found(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The thread has to belong to the project named in the path."""
    sign_in()
    first = _project(client)
    second = _project(client)

    crossed = client.get(
        f"/api/v1/projects/{first['id']}/threads/{second['default_thread_id']}/conversation"
    )
    assert crossed.status_code == 404


def test_an_active_run_is_offered_as_a_reconnect_target(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The newest run is reported, and a running one is an active target."""
    sign_in()
    project = _project(client)
    thread_id = str(project["default_thread_id"])
    now = datetime.now(UTC)
    _add_run(
        clean,
        project_id=str(project["id"]),
        thread_id=thread_id,
        status=AgentRunStatus.COMPLETED,
        started_at=now - timedelta(minutes=10),
    )
    running = _add_run(
        clean,
        project_id=str(project["id"]),
        thread_id=thread_id,
        status=AgentRunStatus.RUNNING,
        started_at=now,
        revision=3,
    )

    body = client.get(f"/api/v1/projects/{project['id']}/threads/{thread_id}/conversation").json()

    assert body["active_run_id"] == running
    assert body["run"]["id"] == running
    assert body["run"]["status"] == "running"
    assert body["revision"] == 3


def test_a_terminal_run_is_reported_but_is_not_an_active_target(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A finished run still shows in ``run``; ``active_run_id`` stays null."""
    sign_in()
    project = _project(client)
    thread_id = str(project["default_thread_id"])
    finished = _add_run(
        clean,
        project_id=str(project["id"]),
        thread_id=thread_id,
        status=AgentRunStatus.COMPLETED,
        started_at=datetime.now(UTC),
    )

    body = client.get(f"/api/v1/projects/{project['id']}/threads/{thread_id}/conversation").json()

    assert body["run"]["id"] == finished
    assert body["run"]["status"] == "completed"
    assert body["active_run_id"] is None
