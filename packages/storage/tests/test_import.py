"""Smoke tests for the storage package."""

import counterparty_storage


def test_package_is_importable() -> None:
    """The package can be imported without runtime setup or I/O."""
    assert counterparty_storage.__version__ == "0.1.0"
