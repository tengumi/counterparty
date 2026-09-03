"""Minimal test that keeps the initial repository scaffold verifiable."""


def test_package_import() -> None:
    import counterparty_agent

    assert counterparty_agent.__version__ == "0.1.0"
