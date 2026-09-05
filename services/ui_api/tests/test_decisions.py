"""Recording the user's decision and reading AI artifacts, against PostgreSQL.

The point of the database here is ownership and the independence of a decision
from any artifact: a decision is the person's, it is stored under the
authenticated author, and it can be recorded with no artifact at all.
"""

from uuid import uuid4

from conftest import ANALYST, SignIn
from counterparty_storage.workspace.enums import ArtifactFreshness
from counterparty_storage.workspace.models import AnalysisArtifact
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session


def _project(client: TestClient, **payload: object) -> dict[str, object]:
    body = {"client_request_id": str(uuid4()), "title": "Проверка", **payload}
    response = client.post("/api/v1/projects", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _decision(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "outcome": "not_ready",
        "rationale": "Слишком много открытых производств",
        "conditions": [],
        "company_ids": [],
        "context_version": 0,
        "evidence_refs": [],
    }
    body.update(overrides)
    return body


def _add_artifact(
    engine: Engine,
    *,
    project_id: str,
    artifact_id: str,
    version: int,
    summary: str = "Черновой вывод",
) -> None:
    with Session(engine) as session:
        session.add(
            AnalysisArtifact(
                id=artifact_id,
                version=version,
                tenant_id=ANALYST.tenant_id,
                project_id=project_id,
                based_on_context_version=0,
                report_ids=[],
                question="Можно ли платить аванс 80%?",
                summary=summary,
                grounds=[{"text": "Есть залог", "refs": ["report/x#/pledge"]}],
                unknowns=[],
                next_actions=[],
                evidence_refs=[],
                freshness=ArtifactFreshness.CURRENT,
            )
        )
        session.commit()


def test_a_decision_is_stored_under_the_authenticated_author(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The author comes from the session, not from the request body."""
    sign_in()
    project = _project(client)

    created = client.post(f"/api/v1/projects/{project['id']}/decisions", json=_decision())

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["project_id"] == project["id"]
    assert body["outcome"] == "not_ready"
    assert body["author_user_id"] == str(ANALYST.user_id)
    assert body["based_on_artifact_id"] is None
    assert body["created_at"]


def test_decisions_come_back_newest_first(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """The list is ordered so the current decision is the first row."""
    sign_in()
    project = _project(client)

    first = client.post(f"/api/v1/projects/{project['id']}/decisions", json=_decision()).json()
    second = client.post(
        f"/api/v1/projects/{project['id']}/decisions",
        json=_decision(
            outcome="ready_with_conditions",
            rationale="Приемлемо при банковской гарантии на аванс",
            conditions=["Банковская гарантия на аванс"],
            supersedes_id=first["id"],
        ),
    ).json()

    listed = client.get(f"/api/v1/projects/{project['id']}/decisions")
    assert listed.status_code == 200
    ids = [row["id"] for row in listed.json()]
    assert ids == [second["id"], first["id"]]
    assert listed.json()[0]["supersedes_id"] == first["id"]


def test_a_conditional_outcome_without_a_condition_is_refused(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """``ready_with_conditions`` must name a concrete condition."""
    sign_in()
    project = _project(client)

    response = client.post(
        f"/api/v1/projects/{project['id']}/decisions",
        json=_decision(outcome="ready_with_conditions", conditions=[]),
    )

    assert response.status_code == 422


def test_citing_an_artifact_requires_the_version_and_that_it_exists(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """An artifact reference pins the version it read, and it must be real."""
    sign_in()
    project = _project(client)
    artifact_id = str(uuid4())

    unpinned = client.post(
        f"/api/v1/projects/{project['id']}/decisions",
        json=_decision(based_on_artifact_id=artifact_id),
    )
    assert unpinned.status_code == 422

    missing = client.post(
        f"/api/v1/projects/{project['id']}/decisions",
        json=_decision(based_on_artifact_id=artifact_id, based_on_artifact_version=1),
    )
    assert missing.status_code == 404

    _add_artifact(clean, project_id=str(project["id"]), artifact_id=artifact_id, version=1)
    cited = client.post(
        f"/api/v1/projects/{project['id']}/decisions",
        json=_decision(based_on_artifact_id=artifact_id, based_on_artifact_version=1),
    )
    assert cited.status_code == 201, cited.text
    assert cited.json()["based_on_artifact_id"] == artifact_id
    assert cited.json()["based_on_artifact_version"] == 1


def test_a_decision_of_another_owner_is_not_reachable(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """A colleague of the same tenant who does not own the project sees 404."""
    sign_in()
    project = _project(client)
    client.post(f"/api/v1/projects/{project['id']}/decisions", json=_decision())

    sign_in("demo-colleague")
    denied = client.get(f"/api/v1/projects/{project['id']}/decisions")
    assert denied.status_code == 404


def test_artifacts_are_an_honest_empty_list_until_the_agent_writes_one(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """Nothing produces artifacts yet, so the endpoint returns ``[]``."""
    sign_in()
    project = _project(client)

    response = client.get(f"/api/v1/projects/{project['id']}/artifacts")

    assert response.status_code == 200
    assert response.json() == []


def test_latest_collapses_to_the_newest_version_of_each_artifact(
    client: TestClient, clean: Engine, sign_in: SignIn
) -> None:
    """``latest=true`` returns one row per artifact id, the highest version."""
    sign_in()
    project = _project(client)
    artifact_id = str(uuid4())
    _add_artifact(clean, project_id=str(project["id"]), artifact_id=artifact_id, version=1)
    _add_artifact(
        clean,
        project_id=str(project["id"]),
        artifact_id=artifact_id,
        version=2,
        summary="Уточнённый вывод",
    )

    latest = client.get(
        f"/api/v1/projects/{project['id']}/artifacts", params={"latest": "true"}
    ).json()
    everything = client.get(f"/api/v1/projects/{project['id']}/artifacts").json()

    assert [(row["id"], row["version"]) for row in latest] == [(artifact_id, 2)]
    assert latest[0]["summary"] == "Уточнённый вывод"
    assert latest[0]["grounds"] == [{"text": "Есть залог", "refs": ["report/x#/pledge"]}]
    assert len(everything) == 2
