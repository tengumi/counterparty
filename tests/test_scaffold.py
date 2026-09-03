"""Минимальный тест проверяемости начального каркаса репозитория."""

from html.parser import HTMLParser
from pathlib import Path

import pytest


class _StrictEnoughHtmlParser(HTMLParser):
    """Разобрать макет стандартной библиотекой и собрать идентификаторы элементов."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for name, value in attrs:
            if name == "id" and value:
                self.ids.add(value)


def test_package_import() -> None:
    import counterparty_agent

    assert counterparty_agent.__version__ == "0.1.0"


def test_src_main_delegates_to_application(monkeypatch: pytest.MonkeyPatch) -> None:
    import main as entrypoint

    calls = 0

    def fake_run() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(entrypoint, "run", fake_run)
    entrypoint.main()

    assert calls == 1


def test_ui_mockup_contains_core_flows() -> None:
    html_path = Path(__file__).parents[1] / "src" / "counterparty_agent" / "ui" / "index.html"
    parser = _StrictEnoughHtmlParser()
    html = html_path.read_text(encoding="utf-8")
    parser.feed(html)

    assert {
        "searchForm",
        "reportView",
        "chatForm",
        "findingsList",
        "agentStatus",
        "newSessionButton",
    } <= parser.ids
    assert 'fetch("/api/chat"' in html
    assert "innerHTML" not in html
    assert len(html.splitlines()) < 1_200
