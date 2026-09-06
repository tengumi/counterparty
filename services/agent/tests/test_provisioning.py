"""The agent asks the UI backend to pin a company; it never writes itself."""

from typing import Any, ClassVar
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from counterparty_agent.config import AgentSettings
from counterparty_agent.harness import provisioning
from counterparty_agent.harness.provisioning import add_company_by_inn, build_add_company_tool

SETTINGS = AgentSettings(
    ui_api_url="http://ui_api.internal:8000",
    ui_api_internal_token=SecretStr("s3cret"),
)
PROJECT_ID = uuid4()
INN = "7712345678"


class _Response:
    """Minimal stand-in for an ``httpx`` response."""

    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        """Return the decoded body."""
        return self._payload


class _Client:
    """Stand-in for ``httpx.AsyncClient`` that records the one request made."""

    last_call: ClassVar[dict[str, Any]] = {}

    def __init__(self, response: _Response) -> None:
        self._response = response

    def __call__(self, *_args: Any, **_kwargs: Any) -> "_Client":
        """Act as the ``AsyncClient(...)`` constructor."""
        return self

    async def __aenter__(self) -> "_Client":
        """Enter the ``async with`` block."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Leave the ``async with`` block."""
        return None

    async def post(self, url: str, *, json: Any, headers: dict[str, str]) -> _Response:
        """Record the call and return the scripted response."""
        type(self).last_call = {"url": url, "json": json, "headers": headers}
        return self._response


def _install(monkeypatch: pytest.MonkeyPatch, response: _Response) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _Client(response))


async def test_a_successful_pin_sends_the_scoped_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pin request carries the company, project and internal credential."""
    _install(monkeypatch, _Response(200, {"outcome": "added", "name": "ООО РОМАШКА", "inn": INN}))

    await add_company_by_inn(SETTINGS, project_id=PROJECT_ID, inn=INN)
    assert _Client.last_call["json"] == {"inn": INN}
    assert _Client.last_call["headers"]["X-Internal-Token"] == "s3cret"
    assert str(PROJECT_ID) in _Client.last_call["url"]


async def test_a_transport_failure_degrades_to_a_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection error never fails the run; it returns a sentence."""

    class _Boom(_Client):
        async def post(self, *_a: Any, **_k: Any) -> _Response:
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom(_Response(200, {})))

    message = await add_company_by_inn(SETTINGS, project_id=PROJECT_ID, inn=INN)

    assert message


async def test_the_tool_rejects_a_malformed_inn_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value that is not 10 or 12 digits never reaches the network."""
    called = False

    async def _fail(*_a: Any, **_k: Any) -> str:
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr(provisioning, "add_company_by_inn", _fail)
    tool = build_add_company_tool(SETTINGS, project_id=PROJECT_ID)

    await tool.ainvoke({"inn": "12-34"})

    assert not called
