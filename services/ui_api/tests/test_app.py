"""Tests for the UI API composition root."""

from collections.abc import Iterator

import pytest
from counterparty_contracts import __version__ as contracts_version
from fastapi.testclient import TestClient

from counterparty_ui_api.app import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Run the application with its real lifespan."""
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health_reports_ready_service(client: TestClient) -> None:
    """Health reports the service and installed contract package version."""
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ui_api",
        "contracts_version": contracts_version,
    }


def test_health_is_declared_in_openapi(client: TestClient) -> None:
    """Health output remains visible as a typed OpenAPI response."""
    schema = client.get("/openapi.json").json()

    success_response = schema["paths"]["/healthz"]["get"]["responses"]["200"]
    assert success_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }
