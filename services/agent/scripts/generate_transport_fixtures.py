"""Regenerate the wire fixtures the web transport tests decode.

Usage: `uv run python scripts/generate_transport_fixtures.py`
"""

import asyncio
from pathlib import Path

from counterparty_agent.transport.fixtures import FIXTURE_PROMPTS, render

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "apps/web/src/chat/__fixtures__"


async def main() -> None:
    """Write one `.sse` file per V01 case."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name in FIXTURE_PROMPTS:
        (FIXTURE_DIR / f"{name}.sse").write_text(await render(name), encoding="utf-8")
        print(f"wrote {name}.sse")


if __name__ == "__main__":
    asyncio.run(main())
