"""Единый запуск и доставка собранного frontend; UI-контракты проверяет Vitest."""

import ast
import re
from importlib import import_module
from importlib.metadata import distribution
from pathlib import Path

import pytest


def test_package_import() -> None:
    import counterparty_agent

    assert counterparty_agent.__version__ == "0.1.0"


def test_src_main_delegates_to_application(monkeypatch: pytest.MonkeyPatch) -> None:
    import main as entrypoint
    from counterparty_agent.api.routes import run

    assert entrypoint.run is run
    calls = []
    monkeypatch.setattr(entrypoint, "run", lambda: calls.append(True))
    entrypoint.main()
    assert calls == [True]


@pytest.mark.parametrize(
    ("name", "target"),
    [
        ("counterparty-api", "counterparty_agent.api.routes:run"),
        ("counterparty-llm-check", "counterparty_agent.ai.transport:main"),
    ],
)
def test_installed_commands_point_directly_to_implementation(name: str, target: str) -> None:
    """Проверяем установленный launcher, а не только текст pyproject.toml."""
    command = next(
        item
        for item in distribution("counterparty-agent").entry_points
        if item.group == "console_scripts" and item.name == name
    )
    module, function = target.split(":")
    assert command.value == target
    assert command.load() is getattr(import_module(module), function)


def test_server_start_uses_configured_application(monkeypatch: pytest.MonkeyPatch) -> None:
    """Запуск проверяется без открытия порта и сетевого обращения к модели."""
    import uvicorn

    from counterparty_agent.api import routes
    from counterparty_agent.config import Settings

    settings = Settings(_env_file=None, port=8123, log_level="WARNING")
    calls = []
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    routes.run()
    assert calls == [
        (
            routes.app,
            {
                "host": "127.0.0.1",
                "port": 8123,
                "log_level": "warning",
                "access_log": False,
            },
        )
    ]


def test_implementation_modules_are_not_reexport_only() -> None:
    """Не возвращаем файлы-фасады; маркеры Python-пакетов допустимы."""
    package = Path(__file__).parents[1] / "src/counterparty_agent"
    for name in ("sources", "analysis", "graph", "llm", "app"):
        assert not (package / f"{name}.py").exists()
    for path in package.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        nodes = ast.parse(path.read_text(encoding="utf-8")).body
        substantive = [
            node for node in nodes if not isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom))
        ]
        assert substantive, f"Модуль без реализации: {path.relative_to(package)}"


def test_bundled_ui_assets_exist_and_contain_no_provider_branding() -> None:
    root = Path(__file__).parents[1] / "src/counterparty_agent/ui/build"
    html = (root / "index.html").read_text()
    assert 'id="root"' in html
    assets = re.findall(r'(?:src|href)="/ui/([^"]+)"', html)
    assert assets
    for asset in assets:
        content = (root / asset).read_text()
        assert "dslab" not in content.lower() and "qwen" not in content.lower()
