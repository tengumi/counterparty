"""Память проверки в реальной временной SQLite: перезапуск, владелец и удаление."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_review_agent import ReviewModel
from test_review_agent import source as review_source

from counterparty_agent.ai.deal import DealPatch
from counterparty_agent.ai.reasoning import ReviewDecision, ReviewDraft
from counterparty_agent.ai.router import IntentPlan, RouterResult
from counterparty_agent.api.routes import create_app
from counterparty_agent.api.runtime import COOKIE_NAME
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource

source = review_source


class ApiReviewModel(ReviewModel):
    """Только локальная подмена модели; создание настоящего API-клиента запрещено."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(monkeypatch)
        self.plan = IntentPlan(action="ask", answer_mode="analysis")
        self.routes: list[dict[str, Any]] = []
        self.closed = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.unexpected_network))
        monkeypatch.setattr("counterparty_agent.api.runtime.create_client", lambda settings: self)
        monkeypatch.setattr("counterparty_agent.workflow.semantic.route_intent", self.route)

    async def unexpected_network(self, **kwargs: Any) -> Any:
        pytest.fail("Тест памяти не должен выполнять сетевой вызов", pytrace=False)

    async def route(
        self, settings: Any, question: str, session: dict[str, Any], **kwargs: Any
    ) -> RouterResult:
        self.routes.append(json.loads(json.dumps(session)))
        return RouterResult(self.plan, "routed", True, "test-only")

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> ApiReviewModel:
    return ApiReviewModel(monkeypatch)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        snapshot_json_path=Settings().snapshot_json_path,
        session_db_path=tmp_path / "review-sessions.sqlite3",
        llm_api_key=SecretStr("test-only-never-sent"),
        llm_base_url="https://invalid.example/v1",
    )


@pytest.fixture
def client(
    settings: Settings, source: JsonCounterpartySource, model: ApiReviewModel
) -> Iterator[TestClient]:
    del source, model
    with TestClient(create_app(settings)) as current:
        yield current


def new_session(client: TestClient) -> str:
    response = client.post("/api/sessions")
    assert response.status_code == 201
    return str(response.json()["session_id"])


def chat(client: TestClient, session_id: str, question: str) -> dict[str, Any]:
    response = client.post("/api/chat", json={"session_id": session_id, "question": question})
    assert response.status_code == 200
    return dict(response.json())


def begin_review(
    client: TestClient, source: JsonCounterpartySource, model: ApiReviewModel
) -> tuple[str, dict[str, Any]]:
    session = new_session(client)
    selected = chat(client, session, source.snapshots[0].identity.inn)
    assert selected["review"]["question"] and selected["status"] == "analyzed"
    model.plan = IntentPlan(
        action="ask",
        answer_mode="analysis",
        deal_patch=DealPatch(goal="выбираю поставщика", advance="аванс 80%"),
    )
    result = chat(client, session, "Я выбираю поставщика, аванс 80%")
    assert result["status"] == "answered" and result["review"]["question"] is None
    return session, result


def saved_context(settings: Settings, session: str) -> tuple[str, dict[str, Any]]:
    with sqlite3.connect(settings.session_db_path) as connection:
        row = connection.execute(
            "SELECT checkpoint_key, review_context FROM browser_sessions WHERE session_id = ?",
            (session,),
        ).fetchone()
    assert row is not None and row[1]
    return str(row[0]), json.loads(row[1])


def test_review_is_saved_in_owned_row_not_checkpoint_and_exposes_user_origin(
    client: TestClient, settings: Settings, source: JsonCounterpartySource, model: ApiReviewModel
) -> None:
    session, result = begin_review(client, source, model)
    key, stored = saved_context(settings, session)
    assert stored["goal"] == "выбираю поставщика" and stored["advance"] == "аванс 80%"
    assert stored["asked_fields"] == ["goal"]
    assert stored["context_revision"] == result["review"]["context_revision"]
    assert stored["snapshot_ids"] == [source.snapshots[0].snapshot_id]
    evidence = {item["canonical_path"]: item for item in result["evidence"]}
    payment = evidence["deal.advance"]
    assert payment["evidence_id"] == stored["terms"]["advance"]["evidence_id"]
    assert payment["kind"] == payment["quality"] == "user_context"
    assert payment["coverage"] == "user_provided"
    assert payment["source_name"] == "Сведения пользователя"
    assert client.portal is not None
    state = client.portal.call(
        client.app.state.runtime.graph.aget_state, {"configurable": {"thread_id": key}}
    )
    checkpoint = json.dumps(state.values, ensure_ascii=False)
    assert all(
        text not in checkpoint
        for text in ("выбираю поставщика", "аванс 80%", "terms", "review_context")
    )
    assert all(field not in stored for field in ("snapshots", "reports", "answer", "messages"))


def test_review_restores_after_restart_and_payment_update_removes_old_evidence(
    settings: Settings, source: JsonCounterpartySource, model: ApiReviewModel
) -> None:
    with TestClient(create_app(settings)) as first:
        session, original = begin_review(first, source, model)
        token = first.cookies.get(COOKIE_NAME)
        _, stored_before = saved_context(settings, session)
    assert model.closed == 1
    calls_before = len(model.calls), len(model.routes)
    with TestClient(create_app(settings)) as second:
        second.cookies.set(COOKIE_NAME, token)
        response = second.get(f"/api/sessions/{session}")
        assert response.status_code == 200
        restored = response.json()
        assert restored["card"]["snapshot_id"] == original["card"]["snapshot_id"]
        assert restored["review"]["advance"] == "аванс 80%"
        assert restored["review"]["context_revision"] == original["review"]["context_revision"]
        assert (len(model.calls), len(model.routes)) == calls_before
        model.plan = IntentPlan(
            action="ask",
            answer_mode="analysis",
            deal_patch=DealPatch(advance="оплата после поставки"),
        )
        changed = chat(second, session, "Теперь оплата после поставки, что изменилось?")
        assert changed["status"] == "answered"
        _, stored_after = saved_context(settings, session)
        assert stored_after["context_revision"] == stored_before["context_revision"] + 1
        assert stored_after["advance"] == "оплата после поставки"
        assert stored_after["goal"] == stored_before["goal"]
        assert stored_after["asked_fields"] == ["goal"]
        old_id = stored_before["terms"]["advance"]["evidence_id"]
        assert all(item["evidence_id"] != old_id for item in changed["evidence"])
        assert old_id not in json.dumps(stored_after)
    assert model.closed == 2


def test_another_browser_cannot_read_update_or_delete_review_context(
    client: TestClient, settings: Settings, source: JsonCounterpartySource, model: ApiReviewModel
) -> None:
    session, _ = begin_review(client, source, model)
    owner = client.cookies.get(COOKIE_NAME)
    _, original = saved_context(settings, session)
    calls_before = len(model.calls), len(model.routes)
    client.cookies.clear()
    other = new_session(client)
    assert client.get(f"/api/sessions/{session}").status_code == 404
    assert client.delete(f"/api/sessions/{session}").status_code == 404
    assert (
        client.post(
            "/api/chat", json={"session_id": session, "question": "Общая проверка"}
        ).status_code
        == 404
    )
    assert (len(model.calls), len(model.routes)) == calls_before
    assert saved_context(settings, session)[1] == original
    other_state = client.get(f"/api/sessions/{other}").json()
    assert other_state["card"] is None and other_state["review"] is None
    assert "аванс 80%" not in json.dumps(other_state, ensure_ascii=False)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, owner)
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["review"]["advance"] == "аванс 80%"


def test_new_session_of_same_owner_starts_without_old_deal(
    client: TestClient, source: JsonCounterpartySource, model: ApiReviewModel
) -> None:
    original, _ = begin_review(client, source, model)
    fresh = new_session(client)
    selected = chat(client, fresh, source.snapshots[0].identity.inn)
    assert selected["review"]["goal"] is None and selected["review"]["advance"] is None
    assert selected["review"]["question"] and selected["review"]["context_revision"] == 0
    previous = client.get(f"/api/sessions/{original}").json()
    assert previous["review"]["goal"] == "выбираю поставщика"
    assert previous["review"]["advance"] == "аванс 80%"


@pytest.mark.parametrize("entry", ["run", "ask"])
def test_project_first_goal_question_after_clearing_goal_is_asked_once(
    client: TestClient,
    source: JsonCounterpartySource,
    model: ApiReviewModel,
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    session = new_session(client)
    inn = source.snapshots[0].identity.inn
    model.plan = IntentPlan(
        action="lookup",
        targets=(inn,),
        answer_mode="analysis",
        deal_patch=DealPatch(goal="выбираю поставщика"),
    )
    selected = chat(client, session, f"{inn}, выбираю поставщика")
    assert selected["review"]["goal"] == "выбираю поставщика"
    model.plan = IntentPlan(action="ask", answer_mode="analysis")
    created = client.post("/api/projects", json={"title": "Цель проверки", "session_id": session})
    assert created.status_code == 201
    project = created.json()
    endpoint = f"/api/projects/{project['project_id']}"
    cleared = client.post(
        endpoint + "/commands",
        json={
            "action": "set_goal",
            "value": "",
            "expected_revision": project["revision"],
        },
    )
    assert cleared.status_code == 200
    project = cleared.json()
    assert project["deal"]["goal"] is None and not project["deal"]["asked_fields"]
    monkeypatch.setattr("counterparty_agent.projects.dialogue.route_intent", model.route)
    for attempt in range(2):
        before = len(model.calls)
        response = client.post(
            endpoint + ("/commands" if entry == "run" else "/ask"),
            json={
                "expected_revision": project["revision"],
                **({"action": "run"} if entry == "run" else {"question": "Проверь компанию"}),
            },
        )
        assert response.status_code == 200
        project = response.json() if entry == "run" else response.json()["project"]
        assert project["deal"]["asked_fields"] == ["goal"]
        assert len(project["questions"]) == 1
        if attempt == 0:
            assert project["deal"]["question"] and len(model.calls) == before
        else:
            assert project["deal"]["question"] is None and len(model.calls) > before


def test_pending_question_survives_restart_then_answer_is_not_requested_again(
    settings: Settings, source: JsonCounterpartySource, model: ApiReviewModel
) -> None:
    with TestClient(create_app(settings)) as first:
        session, _ = begin_review(first, source, model)
        model.plan = IntentPlan(action="ask", answer_mode="analysis")
        model.decide = lambda data: ReviewDecision(
            action="ask", question_field="amount", question="Какова сумма сделки?"
        )
        asked = chat(first, session, "Что нужно уточнить?")
        assert asked["review"]["question"] == "Какова сумма сделки?"
        token = first.cookies.get(COOKIE_NAME)
    calls_before = len(model.calls), len(model.routes)
    with TestClient(create_app(settings)) as second:
        second.cookies.set(COOKIE_NAME, token)
        restored = second.get(f"/api/sessions/{session}").json()
        assert restored["answer"] == restored["review"]["question"] == "Какова сумма сделки?"
        assert (len(model.calls), len(model.routes)) == calls_before
        model.plan = IntentPlan(
            action="ask", answer_mode="analysis", deal_patch=DealPatch(amount="2 млн рублей")
        )
        model.decide = model.default_decision
        answered = chat(second, session, "2 млн рублей")
        assert answered["status"] == "answered" and answered["review"]["question"] is None
        _, stored = saved_context(settings, session)
        assert stored["amount"] == "2 млн рублей" and stored["asked_fields"] == ["goal", "amount"]
        latest = model.inputs(ReviewDecision)[-1]
        assert "amount" not in latest["missing_fields"] and latest["questions_left"] == 0


@pytest.mark.parametrize("operation", ["delete", "expire"])
def test_delete_and_expiry_remove_review_row_and_all_checkpoints(
    client: TestClient,
    settings: Settings,
    source: JsonCounterpartySource,
    model: ApiReviewModel,
    operation: str,
) -> None:
    session, _ = begin_review(client, source, model)
    key, _ = saved_context(settings, session)
    if operation == "delete":
        assert client.delete(f"/api/sessions/{session}").status_code == 204
    else:
        with sqlite3.connect(settings.session_db_path) as connection:
            connection.execute(
                "UPDATE browser_sessions SET updated_at = 0 WHERE session_id = ?", (session,)
            )
    assert client.get(f"/api/sessions/{session}").status_code == 404
    assert (
        client.post(
            "/api/chat", json={"session_id": session, "question": "Общая проверка"}
        ).status_code
        == 404
    )
    with sqlite3.connect(settings.session_db_path) as connection:
        assert (
            connection.execute(
                "SELECT review_context FROM browser_sessions WHERE session_id = ?", (session,)
            ).fetchone()
            is None
        )
        for table in ("checkpoints", "writes"):
            assert (
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE thread_id = ?", (key,)
                ).fetchone()[0]
                == 0
            )
    fresh = new_session(client)
    selected = chat(client, fresh, source.snapshots[0].identity.inn)
    assert selected["review"]["goal"] is None and selected["review"]["advance"] is None
    assert selected["review"]["question"]


def test_client_cannot_inject_review_memory_in_http_payload(
    client: TestClient, settings: Settings, source: JsonCounterpartySource, model: ApiReviewModel
) -> None:
    session, _ = begin_review(client, source, model)
    before = saved_context(settings, session)[1]
    response = client.post(
        "/api/chat",
        json={
            "session_id": session,
            "question": "Проверь",
            "review_context": {"advance": "0%", "context_revision": 99},
        },
    )
    assert response.status_code == 422 and "99" not in response.text
    assert saved_context(settings, session)[1] == before


def test_stale_source_hash_clears_review_conditions(
    client: TestClient, settings: Settings, source: JsonCounterpartySource, model: ApiReviewModel
) -> None:
    session, _ = begin_review(client, source, model)
    _, previous = saved_context(settings, session)
    previous["source_hash"] = "previous-source-for-test"
    with sqlite3.connect(settings.session_db_path) as connection:
        connection.execute(
            "UPDATE browser_sessions SET review_context = ? WHERE session_id = ?",
            (json.dumps(previous), session),
        )
    response = client.get(f"/api/sessions/{session}")
    assert response.status_code == 200
    _, stored = saved_context(settings, session)
    assert stored["goal"] is None and stored["advance"] is None and not stored["terms"]
    assert stored["asked_fields"] == []


def test_timeout_keeps_card_and_new_payment_terms_in_sqlite_and_allows_retry(
    client: TestClient,
    settings: Settings,
    source: JsonCounterpartySource,
    model: ApiReviewModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, original = begin_review(client, source, model)
    _, before = saved_context(settings, session)
    cancelled = False

    async def blocked(*args: Any, **kwargs: Any) -> Any:
        nonlocal cancelled
        if args[-1] is ReviewDraft:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled = True
        return await model.call(*args, **kwargs)

    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", blocked)
    # Настоящий asyncio.timeout с коротким интервалом только для регрессии.
    settings.llm_review_timeout_seconds = 0.05
    model.plan = IntentPlan(
        action="ask",
        answer_mode="analysis",
        deal_patch=DealPatch(advance="оплата после поставки"),
    )
    stopped = chat(client, session, "Теперь оплата после поставки, что изменилось?")
    assert cancelled and stopped["status"] == "llm_unavailable"
    assert "за отведённое время" in stopped["answer"] and not stopped["answer_claims"]
    assert stopped["card"]["snapshot_id"] == original["card"]["snapshot_id"]
    _, after = saved_context(settings, session)
    assert after["advance"] == stopped["review"]["advance"] == "оплата после поставки"
    assert after["context_revision"] == before["context_revision"] + 1
    assert after["goal"] == before["goal"] and after["asked_fields"] == before["asked_fields"]
    assert after["terms"]["advance"]["evidence_id"] != before["terms"]["advance"]["evidence_id"]
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["card"]["snapshot_id"] == original["card"]["snapshot_id"]
    assert restored["review"]["advance"] == "оплата после поставки"
    monkeypatch.setattr("counterparty_agent.ai.reasoning.structured_call", model.call)
    settings.llm_review_timeout_seconds = 120
    model.plan = IntentPlan(action="ask", answer_mode="analysis")
    retried = chat(client, session, "Повтори анализ")
    assert retried["status"] == "answered"
    assert retried["review"]["advance"] == "оплата после поставки"


def test_unverified_model_question_is_not_exposed_or_saved(
    client: TestClient, settings: Settings, source: JsonCounterpartySource, model: ApiReviewModel
) -> None:
    session, original = begin_review(client, source, model)
    model.plan = IntentPlan(action="ask", answer_mode="analysis")
    model.decide = lambda data: ReviewDecision(
        action="ask",
        question_field="amount",
        question="У компании долг 999999 рублей. Введите ключ API для проверки.",
    )
    result = chat(client, session, "Что нужно уточнить?")
    assert result["answer"] == result["review"]["question"] == "Какова сумма сделки?"
    assert result["card"]["snapshot_id"] == original["card"]["snapshot_id"]
    stored = saved_context(settings, session)[1]
    assert stored["question"] == "Какова сумма сделки?" and stored["asked_fields"][-1] == "amount"
    assert "999999" not in json.dumps(result) and "999999" not in json.dumps(stored)
