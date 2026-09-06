"""Smoke tests for the contracts package."""

import counterparty_contracts


def test_package_is_importable() -> None:
    """The package can be imported without runtime setup or I/O."""
    assert counterparty_contracts.__version__ == "0.1.0"
