"""Smoke tests for the domain package."""

import counterparty_domain


def test_package_is_importable() -> None:
    """The package can be imported without runtime setup or I/O."""
    assert counterparty_domain.__version__ == "0.1.0"
