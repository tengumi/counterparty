"""Сквозные HTTP-проверки реального JSON и AI-помощник с подменённым сетевым клиентом."""

import asyncio
import json
import re
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langsmith.run_helpers import get_tracing_context
from pydantic import SecretStr

from counterparty_agent.api.routes import create_app
from counterparty_agent.api.runtime import COOKIE_NAME
from counterparty_agent.config import Settings
from counterparty_agent.data.repository import JsonCounterpartySource
from counterparty_agent.models import ResolutionStatus


@pytest.fixture(scope="module")
def source() -> JsonCounterpartySource:
    path = Settings().snapshot_json_path
    if not path.is_file():
        pytest.skip("Реальный JSON не настроен в COUNTERPARTY_SNAPSHOT_JSON_PATH")
    return JsonCounterpartySource.from_path(path)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        snapshot_json_path=Settings().snapshot_json_path,
        session_db_path=tmp_path / "sessions.sqlite3",
        llm_api_key=None,
        _env_file=None,
    )


@pytest.fixture
def client(
    settings: Settings, source: JsonCounterpartySource, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    del source

    async def unexpected_llm(*args: Any, **kwargs: Any) -> None:
        pytest.fail("HTTP workflow не должен вызывать LLM", pytrace=False)

    monkeypatch.setattr("counterparty_agent.ai.transport.generate_answer", unexpected_llm)
    with TestClient(create_app(settings)) as current:
        yield current


def _session(client: TestClient) -> str:
    response = client.post("/api/sessions")
    assert response.status_code == 201
    return str(response.json()["session_id"])


def _lookup(client: TestClient, session: str, source: JsonCounterpartySource) -> dict[str, Any]:
    response = client.post(
        "/api/chat",
        json={
            "session_id": session,
            "question": f"ИНН {source.snapshots[0].identity.inn}",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "analyzed"
    return dict(response.json())


def test_index_health_and_real_card_work_without_key(
    client: TestClient,
    source: JsonCounterpartySource,
) -> None:
    assert client.get("/").status_code == 200
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["companies_count"] == len(source.snapshots)
    assert health["llm_configured"] is False and health["llm_used"] is False
    session = _session(client)
    data = _lookup(client, session, source)
    card = data["card"]
    assert data["mode"] == "deterministic"
    assert card["snapshot_id"] == source.snapshots[0].snapshot_id
    assert card["bank_risk"] == source.snapshots[0].bank_risk.model_dump(mode="json")
    ledger = {item["evidence_id"]: item for item in card["evidence"]}
    for key in (
        "identity_evidence_id",
        "status_evidence_id",
        "report_evidence_id",
        "bank_evidence_id",
    ):
        assert card[key] in ledger
    for finding in card["findings"]:
        assert finding["snapshot_id"] == card["snapshot_id"]
        assert all(key in ledger for key in finding["evidence_ids"])
    identity = ledger[card["identity_evidence_id"]]
    assert set(identity["value"]) == {"inn", "ogrn", "full_name", "short_name", "party_type"}
    assert identity["value_is_projection"] is True
    assert set(ledger[card["status_evidence_id"]]["value"]) == {"raw_status", "effective_at"}
    assert "report" not in card and "enforcement_proceedings" not in card


def test_largest_card_keeps_projection_bounded(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    snapshot = max(source.snapshots, key=lambda item: len(item.enforcement_proceedings))
    response = client.post(
        "/api/chat",
        json={
            "session_id": _session(client),
            "question": snapshot.identity.inn,
        },
    )
    assert response.status_code == 200
    assert len(response.content) < 100_000
    evidence = response.json()["card"]["evidence"]
    assert all(len(item["source_paths"]) <= 8 for item in evidence)
    assert all(len(item["derived_from"]) <= 8 for item in evidence)
    assert any(item["derived_from_total"] > len(item["derived_from"]) for item in evidence)


def test_cookie_owner_cannot_be_replaced_with_client_user_id(
    client: TestClient,
    source: JsonCounterpartySource,
) -> None:
    created = client.post("/api/sessions")
    cookie = created.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    session = created.json()["session_id"]
    _lookup(client, session, source)
    first_browser_token = client.cookies.get(COOKIE_NAME)
    # Меняем только cookie jar: сервер и его event loop остаются общими для двух браузеров.
    client.cookies.clear()
    assert client.get(f"/api/sessions/{session}").status_code == 404
    assert client.delete(f"/api/sessions/{session}").status_code == 404
    assert (
        client.post(
            "/api/chat",
            json={
                "session_id": session,
                "question": "покажи карточку",
            },
        ).status_code
        == 404
    )
    own = _session(client)
    assert client.get(f"/api/sessions/{own}").json()["card"] is None
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, first_browser_token)
    assert client.get(f"/api/sessions/{session}").json()["card"] is not None


def test_new_session_does_not_inherit_old_company(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    first = _session(client)
    _lookup(client, first, source)
    second = _session(client)
    response = client.post("/api/chat", json={"session_id": second, "question": "покажи карточку"})
    assert response.json()["status"] == "no_selection"
    assert response.json()["card"] is None
    assert client.get(f"/api/sessions/{first}").json()["card"] is not None


def test_typo_and_explicit_selection_then_stale_candidate(
    client: TestClient,
    source: JsonCounterpartySource,
) -> None:
    session = _session(client)
    typo = _typo(source)
    result = client.post("/api/chat", json={"session_id": session, "question": typo}).json()
    assert result["status"] == "needs_confirmation" and result["card"] is None
    assert 1 <= len(result["candidates"]) <= 3
    candidate_id = result["candidates"][0]["snapshot_id"]
    unknown = next(
        item.snapshot_id
        for item in source.snapshots
        if item.snapshot_id not in {item["snapshot_id"] for item in result["candidates"]}
    )
    assert (
        client.post(
            "/api/chat",
            json={
                "session_id": session,
                "candidate_snapshot_id": unknown,
            },
        ).status_code
        == 409
    )
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["candidates"][0]["snapshot_id"] == candidate_id
    selected = client.post(
        "/api/chat",
        json={
            "session_id": session,
            "candidate_snapshot_id": candidate_id,
        },
    )
    assert selected.status_code == 200 and selected.json()["card"]["snapshot_id"] == candidate_id
    assert (
        client.post(
            "/api/chat",
            json={
                "session_id": session,
                "candidate_snapshot_id": candidate_id,
            },
        ).status_code
        == 409
    )


def test_invalid_missing_and_unsupported_are_not_fake_cards(client: TestClient) -> None:
    session = _session(client)
    for question, status in [
        ("ИНН 123", "invalid_identifier"),
        ("ООО «несуществующееимядляпроверкимаршрута»", "not_found"),
        ("А сколько у неё судов?", "no_selection"),
        ("Подбери похожих контрагентов", "unsupported"),
    ]:
        response = client.post("/api/chat", json={"session_id": session, "question": question})
        assert response.status_code == 200
        assert response.json()["status"] == status and response.json()["card"] is None


def test_client_facts_and_empty_query_rejected_without_echo(client: TestClient) -> None:
    session = _session(client)
    for extra in [{"context": {"secret": "private_marker"}}, {"user_id": "private_marker"}]:
        response = client.post(
            "/api/chat",
            json={
                "session_id": session,
                "question": "private_marker",
                **extra,
            },
        )
        assert response.status_code == 422 and "private_marker" not in response.text
    assert (
        client.post("/api/chat", json={"session_id": session, "question": " "}).status_code == 422
    )
    assert (
        client.post("/api/sessions", headers={"origin": "https://untrusted.example"}).status_code
        == 403
    )


def test_delete_and_ttl_remove_checkpoint_rows(
    client: TestClient,
    settings: Settings,
    source: JsonCounterpartySource,
) -> None:
    for operation in ("delete", "expire"):
        session = _session(client)
        _lookup(client, session, source)
        with sqlite3.connect(settings.session_db_path) as connection:
            key = connection.execute(
                "SELECT checkpoint_key FROM browser_sessions WHERE session_id = ?", (session,)
            ).fetchone()[0]
            assert (
                connection.execute(
                    "SELECT count(*) FROM checkpoints WHERE thread_id = ?", (key,)
                ).fetchone()[0]
                > 0
            )
            if operation == "expire":
                connection.execute(
                    "UPDATE browser_sessions SET updated_at = 0 WHERE session_id = ?", (session,)
                )
        if operation == "delete":
            assert client.delete(f"/api/sessions/{session}").status_code == 204
        assert client.get(f"/api/sessions/{session}").status_code == 404
        with sqlite3.connect(settings.session_db_path) as connection:
            for table in ("checkpoints", "writes"):
                assert (
                    connection.execute(
                        f"SELECT count(*) FROM {table} WHERE thread_id = ?", (key,)
                    ).fetchone()[0]
                    == 0
                )


def test_session_restores_after_process_restart(
    settings: Settings, source: JsonCounterpartySource
) -> None:
    with TestClient(create_app(settings)) as first:
        session = _session(first)
        original = _lookup(first, session, source)["card"]
        token = first.cookies.get(COOKIE_NAME)
    with TestClient(create_app(settings)) as second:
        second.cookies.set(COOKIE_NAME, token)
        restored = second.get(f"/api/sessions/{session}")
        assert restored.status_code == 200
        assert restored.json()["card"]["snapshot_id"] == original["snapshot_id"]


@pytest.mark.parametrize(
    "kind,expected", [("missing", "unavailable"), ("invalid", "invalid"), ("empty", "empty")]
)
def test_source_failure_has_no_demo_fallback(tmp_path: Path, kind: str, expected: str) -> None:
    path = tmp_path / "input.json"
    if kind != "missing":
        path.write_text("[]" if kind == "empty" else "{", encoding="utf-8")
    settings = Settings(
        snapshot_json_path=path, session_db_path=tmp_path / "sessions.sqlite3", _env_file=None
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health").json()
        assert health["source_status"] == expected
        session = _session(client)
        result = client.post(
            "/api/chat", json={"session_id": session, "question": "проверь компанию"}
        )
        if kind == "empty":
            assert result.status_code == 200 and result.json()["card"] is None
        else:
            assert result.status_code == 503 and "card" not in result.json()


def test_failed_validation_does_not_return_unchecked_card(
    client: TestClient,
    source: JsonCounterpartySource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise ValueError("private_error_marker")

    monkeypatch.setattr("counterparty_agent.workflow.single.validate_analysis", fail)
    session = _session(client)
    result = client.post(
        "/api/chat", json={"session_id": session, "question": source.snapshots[0].identity.inn}
    )
    assert result.status_code == 503
    assert "private_error_marker" not in result.text and "card" not in result.json()
    assert client.get(f"/api/sessions/{session}").json()["status"] == "no_selection"


def test_parallel_requests_do_not_mix_snapshots(
    client: TestClient,
    source: JsonCounterpartySource,
) -> None:
    session = _session(client)

    def send(index: int) -> str:
        response = client.post(
            "/api/chat",
            json={
                "session_id": session,
                "question": source.snapshots[index].identity.inn,
            },
        )
        assert response.status_code == 200
        return str(response.json()["card"]["snapshot_id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        actual = list(executor.map(send, (0, 1)))
    assert actual == [item.snapshot_id for item in source.snapshots[:2]]
    assert client.get(f"/api/sessions/{session}").json()["card"]["snapshot_id"] in actual


def test_graph_tracing_is_disabled_even_when_enabled_by_environment(
    client: TestClient,
    source: JsonCounterpartySource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    original = runtime.graph.ainvoke
    observed: list[object] = []

    async def inspect_context(*args: Any, **kwargs: Any) -> Any:
        observed.append(get_tracing_context()["enabled"])
        return await original(*args, **kwargs)

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setattr(runtime.graph, "ainvoke", inspect_context)
    _lookup(client, _session(client), source)
    assert observed == [False]


class _MockLlmClient:
    """Провайдер выбирает реальный факт из отправленного каталога, не создавая карточек."""

    def __init__(self, failure: str | None = None, slow: bool = False) -> None:
        self.chat = SimpleNamespace(completions=self)
        self.contexts: list[dict[str, Any]] = []
        self.router_calls: list[dict[str, Any]] = []
        self.failure = failure
        self.slow = slow
        self.started = Event()
        self.release = Event()
        self.closed = False

    async def create(self, **kwargs: Any) -> Any:
        content = kwargs["messages"][1]["content"]
        context = json.loads(content.split("<INPUT_DATA>\n", 1)[1].split("\n</INPUT_DATA>", 1)[0])
        if "session" in context:
            self.router_calls.append(context)
            question = content.split("<QUESTION>\n", 1)[1].split("\n</QUESTION>", 1)[0]
            return self._completion(self._route_plan(question, context["session"]))
        # Задержки и повреждения относятся к выбору фактов, а не к разбору намерения.
        self.started.set()
        if self.slow:
            await asyncio.to_thread(self.release.wait, 5)
        self.contexts.append(context)
        if self.failure == "provider":
            raise RuntimeError("private_provider_error")
        bank = next(
            item
            for item in context["approved_facts"]
            if item["topic"] in {"bank_signal", "comparison_bank_signal"}
        )
        selected_ids = [bank["fact_id"]]
        if context.get("explain_bank_reason"):
            selected_ids.append(
                next(
                    item["fact_id"]
                    for item in context["approved_facts"]
                    if item["metric"] == "reason_unavailable"
                )
            )
        if context.get("answer_mode") == "attention_explanation" or context.get(
            "explain_bank_reason"
        ):
            selected_ids.append(
                next(
                    item["fact_id"]
                    for item in context["approved_facts"]
                    if item["topic"] in {"attention_signal", "comparison_attention_signals"}
                )
            )
        output = (
            {"status": "answered", "fact_ids": ["fact_" + "f" * 24]}
            if self.failure == "invalid"
            else {"status": "insufficient_data", "fact_ids": []}
            if self.failure == "insufficient"
            else {"status": "answered", "fact_ids": selected_ids}
        )
        return self._completion(output)

    @staticmethod
    def _route_plan(question: str, session: dict[str, Any]) -> dict[str, Any]:
        """Заданные семантические ответы для сценариев этого HTTP-набора."""

        text = question.casefold()
        identifiers = re.findall(r"(?<!\d)\d{10,15}(?!\d)", question)
        if text.startswith("сравни"):
            return {"action": "compare", "targets": identifiers}
        if text.startswith("добавь"):
            return {"action": "add_to_comparison", "targets": identifiers}
        if text in {"подробнее про вторую", "покажи карточку №2"}:
            return {"action": "show", "position": 2}
        scope = (
            "group"
            if "у всех" in text
            or (session.get("companies") and not session.get("focused_position"))
            else "current"
        )
        return {"action": "ask", "scope": scope}

    @staticmethod
    def _completion(output: dict[str, Any]) -> Any:
        return SimpleNamespace(
            model="qwen3.7-plus",
            usage=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(output)),
                    finish_reason="stop",
                )
            ],
        )

    async def close(self) -> None:
        self.closed = True


def _install_qwen(client: TestClient, mock: _MockLlmClient) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    runtime.settings.llm_api_key = SecretStr("not-a-real-key")
    runtime.llm_client = mock


def test_qwen_answer_has_card_sources_and_scoped_topic_memory(
    client: TestClient,
    source: JsonCounterpartySource,
) -> None:
    mock = _MockLlmClient()
    _install_qwen(client, mock)
    session = _session(client)
    _lookup(client, session, source)
    assert not mock.contexts
    assert not mock.router_calls
    response = client.post("/api/chat", json={"session_id": session, "question": "Какой светофор?"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered" and data["mode"] == "llm" and data["llm_used"]
    assert data["model"] == "qwen3.7-plus"
    assert data["answer_claims"][0]["evidence_ids"] == [data["card"]["bank_evidence_id"]]
    assert len(mock.router_calls) == 1
    assert (
        mock.router_calls[0]["session"]["selected_company"]["inn"]
        == source.snapshots[0].identity.inn
    )
    assert mock.contexts[0]["previous_fact_ids"] == []
    followup = client.post("/api/chat", json={"session_id": session, "question": "А почему?"})
    assert followup.json()["status"] == "answered"
    assert len(followup.json()["answer_claims"]) == 3
    assert mock.contexts[1]["answer_mode"] == "attention_explanation"
    assert {item["topic"] for item in mock.contexts[1]["approved_facts"]} == {
        "bank_signal",
        "attention_signal",
    }
    assert len(mock.contexts[1]["previous_fact_ids"]) == 1
    other_snapshot = source.snapshots[1]
    client.post("/api/chat", json={"session_id": session, "question": other_snapshot.identity.inn})
    client.post("/api/chat", json={"session_id": session, "question": "Какой светофор?"})
    assert mock.contexts[2]["previous_fact_ids"] == []
    new = _session(client)
    assert (
        client.post("/api/chat", json={"session_id": new, "question": "А почему?"}).json()["status"]
        == "no_selection"
    )
    assert len(mock.contexts) == 3
    assert mock.router_calls[-1]["session"].get("selected_company") is None
    assert mock.router_calls[-1]["session"]["companies"] == []


@pytest.mark.parametrize(
    "failure,status,calls",
    [
        ("provider", "llm_unavailable", 1),
        ("invalid", "validation_failed", 2),
        ("insufficient", "insufficient_data", 1),
    ],
)
def test_qwen_failure_keeps_verified_card(
    client: TestClient,
    source: JsonCounterpartySource,
    failure: str,
    status: str,
    calls: int,
) -> None:
    mock = _MockLlmClient(failure)
    _install_qwen(client, mock)
    session = _session(client)
    original = _lookup(client, session, source)["card"]
    response = client.post("/api/chat", json={"session_id": session, "question": "Какие риски?"})
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert response.json()["answer_claims"] == []
    assert response.json()["card"]["snapshot_id"] == original["snapshot_id"]
    assert "private_provider_error" not in response.text
    assert len(mock.contexts) == calls
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["card"]["snapshot_id"] == original["snapshot_id"]
    assert len(mock.contexts) == calls


def test_missing_qwen_key_does_not_break_card(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    session = _session(client)
    original = _lookup(client, session, source)["card"]
    response = client.post("/api/chat", json={"session_id": session, "question": "Какие риски?"})
    assert response.json()["status"] == "llm_unavailable"
    assert response.json()["llm_used"] is False
    assert response.json()["card"]["snapshot_id"] == original["snapshot_id"]


def test_slow_qwen_does_not_block_other_session_or_resurrect_deleted_one(
    client: TestClient,
    source: JsonCounterpartySource,
    settings: Settings,
) -> None:
    mock = _MockLlmClient(slow=True)
    _install_qwen(client, mock)
    session = _session(client)
    other = _session(client)
    _lookup(client, session, source)
    with ThreadPoolExecutor(max_workers=3) as pool:
        slow = pool.submit(
            client.post,
            "/api/chat",
            json={
                "session_id": session,
                "question": "Какой светофор?",
            },
        )
        try:
            assert mock.started.wait(2)
            # Эмулируем запрос дольше TTL: активный checkpoint не должен удалиться чужим запросом.
            with sqlite3.connect(settings.session_db_path) as connection:
                connection.execute(
                    "UPDATE browser_sessions SET updated_at = 0 WHERE session_id = ?", (session,)
                )
            quick = pool.submit(_lookup, client, other, source)
            assert quick.result(timeout=2)["status"] == "analyzed"
            deletion = pool.submit(client.delete, f"/api/sessions/{session}")
            assert not deletion.done()
        finally:
            mock.release.set()
        assert slow.result(timeout=3).json()["status"] == "answered"
        assert deletion.result(timeout=3).status_code == 204
    assert client.get(f"/api/sessions/{session}").status_code == 404


def test_lifespan_closes_shared_qwen_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock = _MockLlmClient()
    settings.llm_api_key = SecretStr("not-a-real-key")
    monkeypatch.setattr("counterparty_agent.api.runtime.create_client", lambda _: mock)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["qa_available"]
        assert not mock.closed
    assert mock.closed


def _typo(source: JsonCounterpartySource) -> str:
    for snapshot in source.snapshots:
        name = snapshot.identity.short_name
        middle = len(name) // 2
        query = name[:middle] + name[middle + 1 :]
        if (
            source.find_by_name_exact(query).status is ResolutionStatus.NOT_FOUND
            and source.find_by_name_fuzzy(query).status is ResolutionStatus.NEEDS_CONFIRMATION
        ):
            return query
    raise AssertionError("Не найден сценарий опечатки в реальном наборе")


@pytest.mark.parametrize("count", [2, 10])
def test_comparison_returns_scoped_matrix_without_llm(
    client: TestClient,
    source: JsonCounterpartySource,
    count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_llm(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Построение сравнения не должно вызывать AI-помощник", pytrace=False)

    monkeypatch.setattr("counterparty_agent.workflow.single.answer_question", unexpected_llm)
    snapshots = source.snapshots[:count]
    session = _session(client)
    response = client.post(
        "/api/chat",
        json={
            "session_id": session,
            "question": "Сравни " + ", ".join(item.identity.inn for item in snapshots),
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "compared" and data["card"] is None
    assert data["mode"] == "deterministic" and data["llm_used"] is False
    assert data["answer_claims"] == []
    comparison = data["comparison"]
    assert comparison["snapshot_ids"] == [item.snapshot_id for item in snapshots]
    assert [item["snapshot_id"] for item in data["cards"]] == comparison["snapshot_ids"]
    ledgers = {
        card["snapshot_id"]: {item["evidence_id"] for item in card["evidence"]}
        for card in data["cards"]
    }
    for row in comparison["rows"]:
        assert [cell["snapshot_id"] for cell in row["cells"]] == comparison["snapshot_ids"]
        for cell in row["cells"]:
            assert cell["evidence_ids"]
            assert set(cell["evidence_ids"]) <= ledgers[cell["snapshot_id"]]
    for snapshot, card in zip(snapshots, data["cards"], strict=True):
        assert card["bank_risk"] == snapshot.bank_risk.model_dump(mode="json")
        assert "report" not in card and "enforcement_proceedings" not in card
        identity = next(
            item for item in card["evidence"] if item["evidence_id"] == card["identity_evidence_id"]
        )
        assert set(identity["value"]) <= {"inn", "ogrn", "full_name", "short_name", "party_type"}
        assert all(len(item["source_paths"]) <= 8 for item in card["evidence"])
    assert len(response.content) < 1_000_000
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["status"] == "compared"
    assert restored["comparison"]["snapshot_ids"] == comparison["snapshot_ids"]
    followup = client.post(
        "/api/chat", json={"session_id": session, "question": "Какая выручка?"}
    ).json()
    assert followup["status"] == "llm_unavailable"
    assert followup["card"] is None and followup["comparison"] is not None
    assert followup["llm_used"] is False


def test_comparison_incomplete_preserves_each_position(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    session = _session(client)
    question = f"Сравни ИНН {source.snapshots[0].identity.inn} и ИНН 123"
    data = client.post("/api/chat", json={"session_id": session, "question": question}).json()
    assert data["status"] == "comparison_incomplete"
    assert data["comparison"] is None and data["cards"] == [] and data["card"] is None
    assert [item["status"] for item in data["comparison_selections"]] == [
        "resolved",
        "invalid_identifier",
    ]
    assert [item["position"] for item in data["comparison_selections"]] == [1, 2]
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["comparison_selections"] == data["comparison_selections"]


def test_comparison_candidate_requires_matching_slot_and_cannot_be_replayed(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    typo = _typo(source)
    candidates = source.find_by_name_fuzzy(typo).candidates
    candidate_ids = {item.snapshot_id for item in candidates}
    other = next(item for item in source.snapshots if item.snapshot_id not in candidate_ids)
    session = _session(client)
    question = f"Сравни ИНН {other.identity.inn} и «{typo.replace(chr(34), '')}»"
    first = client.post("/api/chat", json={"session_id": session, "question": question}).json()
    assert first["status"] == "comparison_needs_confirmation"
    slot = next(
        item for item in first["comparison_selections"] if item["status"] == "needs_confirmation"
    )
    candidate_id = slot["candidates"][0]["snapshot_id"]
    selection_id = slot["selection_id"]
    for selection in [None, "selection_" + "f" * 24]:
        payload = {"session_id": session, "candidate_snapshot_id": candidate_id}
        if selection is not None:
            payload["candidate_selection_id"] = selection
        assert client.post("/api/chat", json=payload).status_code == 409
    assert (
        client.post(
            "/api/chat",
            json={
                "session_id": session,
                "candidate_snapshot_id": other.snapshot_id,
                "candidate_selection_id": selection_id,
            },
        ).status_code
        == 409
    )
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["status"] == "comparison_needs_confirmation"
    payload = {
        "session_id": session,
        "candidate_snapshot_id": candidate_id,
        "candidate_selection_id": selection_id,
    }
    final = client.post("/api/chat", json=payload)
    assert final.status_code == 200 and final.json()["status"] == "compared"
    assert final.json()["comparison"]["snapshot_ids"] == [other.snapshot_id, candidate_id]
    assert client.post("/api/chat", json=payload).status_code == 409


def test_comparison_limit_and_duplicate_do_not_produce_partial_table(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    session = _session(client)
    response = client.post(
        "/api/chat",
        json={
            "session_id": session,
            "question": "Сравни " + ", ".join(item.identity.inn for item in source.snapshots[:11]),
        },
    ).json()
    assert response["status"] == "compared"
    assert len(response["cards"]) == 11
    assert len(response["comparison"]["snapshot_ids"]) == 11
    identity = source.snapshots[0].identity
    duplicate = client.post(
        "/api/chat",
        json={
            "session_id": session,
            "question": f"Сравни ИНН {identity.inn} и ОГРН {identity.ogrn}",
        },
    ).json()
    assert duplicate["comparison"] is None and not duplicate["cards"]
    assert any(item["status"] == "duplicate" for item in duplicate["comparison_selections"])


def test_comparison_context_is_private_and_cleared_for_single_company(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    session = _session(client)
    client.post(
        "/api/chat",
        json={
            "session_id": session,
            "question": "Сравни " + ", ".join(item.identity.inn for item in source.snapshots[:2]),
        },
    )
    assert client.get(f"/api/sessions/{_session(client)}").json()["comparison"] is None
    owner_token = client.cookies.get(COOKIE_NAME)
    client.cookies.clear()
    assert client.get(f"/api/sessions/{session}").status_code == 404
    assert client.delete(f"/api/sessions/{session}").status_code == 404
    client.cookies.set(COOKIE_NAME, owner_token)
    single = client.post(
        "/api/chat",
        json={"session_id": session, "question": source.snapshots[2].identity.inn},
    ).json()
    assert single["status"] == "analyzed"
    assert single["comparison"] is None and single["comparison_selections"] == []
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["card"]["snapshot_id"] == source.snapshots[2].snapshot_id
    assert restored["comparison"] is None


def test_selection_id_without_candidate_is_rejected_without_echo(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "session_id": _session(client),
            "question": "private_marker",
            "candidate_selection_id": "selection_" + "a" * 24,
        },
    )
    assert response.status_code == 422 and "private_marker" not in response.text


def _compare(client: TestClient, session: str, source: JsonCounterpartySource) -> dict[str, Any]:
    response = client.post(
        "/api/chat",
        json={
            "session_id": session,
            "question": "Сравни " + ", ".join(item.identity.inn for item in source.snapshots[:2]),
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "compared"
    return dict(response.json())


def test_comparison_qwen_sources_and_group_topic_survive_restore(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    mock = _MockLlmClient()
    _install_qwen(client, mock)
    session = _session(client)
    original = _compare(client, session, source)
    assert not mock.contexts
    assert not mock.router_calls
    response = client.post(
        "/api/chat", json={"session_id": session, "question": "Какой светофор у всех?"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered" and data["mode"] == "llm"
    assert data["comparison"]["snapshot_ids"] == original["comparison"]["snapshot_ids"]
    assert data["focus_snapshot_id"] is None and data["card"] is None
    assert not data["comparison_pending"]
    claim_ids = {key for claim in data["answer_claims"] for key in claim["evidence_ids"]}
    assert claim_ids
    for card in data["cards"]:
        assert card["bank_evidence_id"] in claim_ids
    ledger = {item["evidence_id"] for card in data["cards"] for item in card["evidence"]}
    assert claim_ids <= ledger
    assert mock.contexts[0]["previous_fact_ids"] == []
    assert len(mock.router_calls) == 1
    assert len(mock.router_calls[0]["session"]["companies"]) == 2
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["comparison"]["snapshot_ids"] == original["comparison"]["snapshot_ids"]
    assert len(mock.contexts) == 1
    assert len(mock.router_calls) == 1
    followup = client.post("/api/chat", json={"session_id": session, "question": "А почему?"})
    assert followup.json()["status"] == "answered"
    assert mock.contexts[1]["previous_fact_ids"]


def test_comparison_focus_single_question_and_return_keep_group(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    mock = _MockLlmClient()
    _install_qwen(client, mock)
    session = _session(client)
    original = _compare(client, session, source)
    focus = client.post(
        "/api/chat", json={"session_id": session, "question": "Подробнее про вторую"}
    ).json()
    second_id = source.snapshots[1].snapshot_id
    assert focus["focus_snapshot_id"] == second_id
    assert focus["card"]["snapshot_id"] == second_id
    assert focus["comparison"]["snapshot_ids"] == original["comparison"]["snapshot_ids"]
    assert not mock.contexts
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["focus_snapshot_id"] == second_id
    answer = client.post(
        "/api/chat", json={"session_id": session, "question": "Какой у неё светофор?"}
    ).json()
    assert answer["status"] == "answered" and answer["focus_snapshot_id"] == second_id
    assert answer["answer_claims"][0]["evidence_ids"] == [answer["card"]["bank_evidence_id"]]
    assert mock.contexts[0]["previous_fact_ids"] == []
    table = client.post(
        "/api/chat", json={"session_id": session, "question": "Покажи сравнение"}
    ).json()
    assert table["focus_snapshot_id"] is None and table["card"] is None
    assert table["comparison"]["snapshot_ids"] == original["comparison"]["snapshot_ids"]
    assert len(mock.contexts) == 1
    # Явный групповой вопрос сбрасывает одиночный фокус, но не подмешивает его тему.
    client.post("/api/chat", json={"session_id": session, "question": "Покажи карточку №2"})
    grouped = client.post(
        "/api/chat", json={"session_id": session, "question": "Какой светофор у всех?"}
    ).json()
    assert grouped["status"] == "answered" and grouped["focus_snapshot_id"] is None
    assert len(grouped["cards"]) == 2 and grouped["card"] is None
    assert mock.contexts[-1]["previous_fact_ids"] == []


@pytest.mark.parametrize(
    "failure,status", [("provider", "llm_unavailable"), ("invalid", "validation_failed")]
)
def test_comparison_qwen_failure_preserves_table(
    client: TestClient, source: JsonCounterpartySource, failure: str, status: str
) -> None:
    mock = _MockLlmClient(failure)
    _install_qwen(client, mock)
    session = _session(client)
    original = _compare(client, session, source)
    response = client.post(
        "/api/chat", json={"session_id": session, "question": "Какой светофор у всех?"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == status and not data["answer_claims"]
    assert data["comparison"]["snapshot_ids"] == original["comparison"]["snapshot_ids"]
    assert "private_provider_error" not in response.text
    assert client.get(f"/api/sessions/{session}").json()["comparison"] is not None


def test_comparison_addition_commits_whole_group_and_rejects_duplicate(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    session = _session(client)
    original = _compare(client, session, source)
    third = source.snapshots[2]
    added = client.post(
        "/api/chat",
        json={"session_id": session, "question": f"Добавь к сравнению ИНН {third.identity.inn}"},
    ).json()
    expected = [*original["comparison"]["snapshot_ids"], third.snapshot_id]
    assert added["status"] == "compared" and not added["comparison_pending"]
    assert added["comparison"]["snapshot_ids"] == expected
    duplicate = client.post(
        "/api/chat",
        json={"session_id": session, "question": f"Добавь к сравнению ОГРН {third.identity.ogrn}"},
    ).json()
    assert duplicate["comparison_pending"]
    assert duplicate["comparison"]["snapshot_ids"] == expected
    assert any(item["status"] == "duplicate" for item in duplicate["comparison_selections"])
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["comparison_pending"] and restored["comparison"]["snapshot_ids"] == expected


def test_comparison_pending_addition_restores_and_confirms_one_position(
    client: TestClient, source: JsonCounterpartySource
) -> None:
    typo = _typo(source)
    candidate_ids = {item.snapshot_id for item in source.find_by_name_fuzzy(typo).candidates}
    base = [item for item in source.snapshots if item.snapshot_id not in candidate_ids][:2]
    session = _session(client)
    client.post(
        "/api/chat",
        json={
            "session_id": session,
            "question": "Сравни " + ", ".join(item.identity.inn for item in base),
        },
    )
    pending = client.post(
        "/api/chat",
        json={
            "session_id": session,
            "question": f"Добавь к сравнению «{typo.replace(chr(34), '')}»",
        },
    ).json()
    assert pending["comparison_pending"]
    assert pending["comparison"]["snapshot_ids"] == [item.snapshot_id for item in base]
    slot = next(
        item for item in pending["comparison_selections"] if item["status"] == "needs_confirmation"
    )
    assert slot["position"] == 3
    restored = client.get(f"/api/sessions/{session}").json()
    assert restored["comparison_pending"]
    assert restored["comparison_selections"] == pending["comparison_selections"]
    payload = {
        "session_id": session,
        "candidate_snapshot_id": slot["candidates"][0]["snapshot_id"],
        "candidate_selection_id": slot["selection_id"],
    }
    result = client.post("/api/chat", json=payload)
    assert result.status_code == 200 and result.json()["status"] == "compared"
    assert not result.json()["comparison_pending"]
    assert result.json()["comparison"]["snapshot_ids"] == [
        *[item.snapshot_id for item in base],
        payload["candidate_snapshot_id"],
    ]
    assert client.post("/api/chat", json=payload).status_code == 409


@pytest.mark.parametrize(
    "tamper", ["foreign_focus", "wrong_card", "foreign_claim", "claim_text", "answer_text"]
)
def test_api_rejects_forged_group_scope_and_text(
    source: JsonCounterpartySource, tamper: str
) -> None:
    from counterparty_agent.ai.comparison_catalog import build_comparison_fact_catalog
    from counterparty_agent.ai.contracts import GroundedClaim
    from counterparty_agent.analytics.comparison import compare_snapshots
    from counterparty_agent.analytics.core import analyze_snapshot
    from counterparty_agent.api.projections import _response
    from counterparty_agent.workflow.contracts import WorkflowResult

    snapshots = tuple(source.snapshots[:2])
    evaluated_at = datetime.now(UTC)
    analyses = tuple(analyze_snapshot(item, evaluated_at=evaluated_at) for item in snapshots)
    comparison = compare_snapshots(snapshots, evaluated_at=evaluated_at)
    fact = build_comparison_fact_catalog(snapshots, comparison)[0]
    result = WorkflowResult(
        status="answered",
        answer=fact.claim.text,
        answer_claims=(fact.claim,),
        comparison=comparison,
        snapshots=snapshots,
        analyses=analyses,
    )
    if tamper == "foreign_focus":
        result.focus_snapshot_id = source.snapshots[2].snapshot_id
    elif tamper == "wrong_card":
        result.focus_snapshot_id = snapshots[0].snapshot_id
        result.snapshot, result.analysis = snapshots[1], analyses[1]
    elif tamper == "foreign_claim":
        foreign = analyze_snapshot(source.snapshots[2], evaluated_at=evaluated_at)
        result.answer_claims = (
            GroundedClaim(text=fact.claim.text, evidence_ids=(foreign.bank_evidence_id,)),
        )
    elif tamper == "claim_text":
        result.answer_claims = (fact.claim.model_copy(update={"text": "Неподтверждённый вывод"}),)
        result.answer = result.answer_claims[0].text
    else:
        result.answer += " Неподтверждённый вывод."
    with pytest.raises(ValueError):
        _response("a" * 32, result)
