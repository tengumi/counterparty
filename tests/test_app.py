"""Дымовые тесты API без обращений к DSLab."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from counterparty_agent.app import app
from counterparty_agent.config import Settings, get_settings


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Использовать детерминированные настройки без ключа независимо от окружения."""

    settings = Settings(llm_api_key=None, _env_file=None)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_index_and_health_do_not_call_the_model(client: TestClient) -> None:
    index_response = client.get("/")
    health_response = client.get("/api/health")

    assert index_response.status_code == 200
    assert "Проверка контрагента" in index_response.text
    assert health_response.json() == {
        "status": "ok",
        "llm_configured": False,
        "llm_provider": "dslab",
        "llm_model": "qwen3.7-plus",
    }


def test_chat_reports_missing_server_side_key(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "session_id": "TEST_SESSION",
            "question": "Какие риски?",
            "context": {"synthetic_demo_data": True},
        },
    )

    assert response.status_code == 503
    assert "COUNTERPARTY_LLM_API_KEY" in response.json()["detail"]
