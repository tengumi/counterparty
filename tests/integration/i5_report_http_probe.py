"""Independent REST scope/history/evidence probe over a real local HTTP listener.

Requires the approved corpus imported into a dedicated database and a login
in counterparty_ui_api. The probe creates and removes only its own projects.
"""

import asyncio
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from psycopg import AsyncConnection

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    """Allocate a local ephemeral port for the short-lived verification worker."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def main() -> None:
    """Exercise the production application in a child process with real cookies."""
    tenant = str(uuid4())
    users = {
        "i5-owner": {
            "tenant_id": tenant,
            "user_id": str(uuid4()),
            "display_name": "I5 owner",
        },
        "i5-colleague": {
            "tenant_id": tenant,
            "user_id": str(uuid4()),
            "display_name": "I5 peer",
        },
        "i5-foreign": {
            "tenant_id": str(uuid4()),
            "user_id": str(uuid4()),
            "display_name": "I5 other",
        },
    }
    run_key = uuid4().hex
    users = {f"{login}-{run_key}": claims for login, claims in users.items()}
    port = free_port()
    child = await asyncio.create_subprocess_exec(
        str(ROOT / "services/ui_api/.venv/bin/python"),
        "-m",
        "uvicorn",
        "counterparty_ui_api.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-access-log",
        "--log-level",
        "error",
        env={
            **os.environ,
            "UI_API_DATABASE_URL": os.environ["I5_API_DATABASE_URL"],
            "UI_API_SESSION_COOKIE_SECURE": "false",
            "UI_API_DEMO_USERS": json.dumps(users),
        },
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    checks = 0
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=20
        ) as api:
            async with asyncio.timeout(10):
                while True:
                    try:
                        if (await api.get("/healthz")).status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    await asyncio.sleep(0.05)
            response = await api.get("/api/v1/companies", params={"inn": "7449088645"})
            assert response.status_code == 401
            checks += 1
            assert (
                await api.post(
                    "/api/v1/auth/session", json={"login": f"i5-owner-{run_key}"}
                )
            ).status_code == 201
            company = (
                await api.get("/api/v1/companies", params={"inn": "7449088645"})
            ).json()["items"][0]
            report_id = company["latest_report_id"]
            section_url = f"/api/v1/reports/{report_id}/sections/profile"
            overview = (await api.get(f"/api/v1/reports/{report_id}/overview")).json()
            profile = (await api.get(section_url)).json()["records"][0]
            ref = profile["evidence_refs"][0]
            created = await api.post(
                "/api/v1/projects", json={"client_request_id": str(uuid4())}
            )
            assert created.status_code == 201
            project = created.json()
            added = await api.post(
                f"/api/v1/projects/{project['id']}/companies",
                json={
                    "items": [{"inn": "7449088645"}],
                    "expected_context_version": 0,
                },
            )
            assert added.status_code == 200
            pinned = (await api.get(f"/api/v1/projects/{project['id']}")).json()
            assert pinned["companies"][0]["report_id"] == report_id
            checks += 1

            def evidence_path(project_id: str, evidence: str) -> str:
                return (
                    f"/api/v1/projects/{project_id}/evidence/{quote(evidence, safe='')}"
                )

            evidence_url = evidence_path(project["id"], ref)
            response = await api.get(evidence_url)
            assert response.status_code == 200
            original: dict[str, Any] = response.json()
            assert original["report"] == overview["report"]
            assert original["evidence"]["report_id"] == report_id
            raw_date = original["value"]["registrationInfo"]["registrationDate"]
            if isinstance(raw_date, dict):
                raw_date = raw_date["$date"]
            assert datetime.fromisoformat(
                profile["registration_date"].replace("Z", "+00:00")
            ) == datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(UTC)
            checks += 3
            for forged in [
                f"report:{report_id}:/",
                f"report:{report_id}:/baseInfo/notIssued",
                f"report:{report_id}:/baseInfo/registrationInfo/registrationDate",
                f"report:{uuid4()}:/baseInfo",
                ref + "/../status",
            ]:
                assert (
                    await api.get(evidence_path(project["id"], forged))
                ).status_code == 404
                checks += 1
            empty = (
                await api.post(
                    "/api/v1/projects", json={"client_request_id": str(uuid4())}
                )
            ).json()
            assert (await api.get(evidence_path(empty["id"], ref))).status_code == 404
            checks += 1
            for login in ("i5-colleague", "i5-foreign"):
                assert (
                    await api.post(
                        "/api/v1/auth/session", json={"login": f"{login}-{run_key}"}
                    )
                ).status_code == 201
                assert (await api.get(evidence_url)).status_code == 404
                checks += 1
            await api.post(
                "/api/v1/auth/session", json={"login": f"i5-owner-{run_key}"}
            )
            removed = await api.request(
                "DELETE",
                f"/api/v1/projects/{project['id']}/companies/{company['company_id']}",
                json={"expected_context_version": 1},
            )
            assert removed.status_code == 200
            assert (await api.get(evidence_url)).json() == original
            checks += 1
            assert (
                await api.get(section_url, params={"active": "true"})
            ).status_code == 422
            assert (
                await api.get(section_url, params={"cursor": "forged-cursor"})
            ).status_code == 422
            checks += 2
            # Project DELETE belongs to a later delivery; model a deleted fixture
            # directly, so the current evidence authorization can still be checked.
            assert (
                await api.delete(f"/api/v1/projects/{project['id']}")
            ).status_code == 405
            async with await AsyncConnection.connect(
                os.environ["I5_API_ADMIN_DSN"]
            ) as db:
                await db.execute(
                    "UPDATE workspace.projects SET deleted_at = now() WHERE id IN (%s, %s)",
                    (project["id"], empty["id"]),
                )
            assert (await api.get(evidence_url)).status_code == 404
            checks += 1
    finally:
        if child.returncode is None:
            child.terminate()
        _, errors = await asyncio.wait_for(child.communicate(), timeout=10)
        assert child.returncode in (0, -15), errors.decode()
    print(
        json.dumps(
            {
                "rest_http_checks": checks,
                "listener_cleaned_up": True,
                "project_delete_endpoint": "pending_405",
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
