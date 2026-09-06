"""The domain package performs no I/O, including at import time."""

import subprocess
import sys

_FORBIDDEN = (
    "socket",
    "ssl",
    "http",
    "urllib.request",
    "sqlite3",
    "asyncio",
    "subprocess",
)
# ``pathlib`` is deliberately absent: pydantic imports it for its Path type
# support, which is a type declaration and not a filesystem access.

_PROBE = """
import sys
before = set(sys.modules)
import counterparty_domain
added = set(sys.modules) - before
print(",".join(sorted(name for name in {names!r} if name in added)))
"""


def _loaded_forbidden_modules() -> str:
    """Import the package in a clean interpreter and report I/O modules pulled in."""
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(names=_FORBIDDEN)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_import_loads_no_io_modules() -> None:
    """Importing the package must not pull in network, db or filesystem I/O."""
    assert _loaded_forbidden_modules() == ""
