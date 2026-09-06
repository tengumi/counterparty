"""Packaging smoke tests."""


def test_package_imports() -> None:
    """The installed distribution exposes its ASGI and MCP applications."""
    from counterparty_mcp import app, mcp

    assert app.title == "Counterparty MCP"
    assert mcp.name == "Counterparty Reports"
