"""Verify real saver-table contents survive application migration rollback/upgrade.

This operates only on the explicitly supplied, isolated AGENT_TEST_POSTGRES_DSN.
Application agent_runs are disposable here; the probe preserves saver-table data.
"""

import json
import os
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
TABLES = (
    "checkpoint_migrations",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)


def digests(dsn: str) -> dict[str, tuple[int, str]]:
    """Hash every original framework row without printing any checkpoint payload."""
    result: dict[str, tuple[int, str]] = {}
    with psycopg.connect(dsn) as connection:
        for name in TABLES:
            row = connection.execute(
                sql.SQL(
                    "SELECT count(*), md5(COALESCE(string_agg(to_jsonb(t)::text, '' "
                    "ORDER BY to_jsonb(t)::text), '')) FROM workspace.{} t"
                ).format(sql.Identifier(name))
            ).fetchone()
            assert row is not None
            result[name] = (row[0], row[1])
    return result


def main() -> None:
    """Roundtrip only the app-run revision while retaining official saver tables."""
    dsn = os.environ["AGENT_TEST_POSTGRES_DSN"]
    before = digests(dsn)
    assert before["checkpoints"][0] > 0 and before["checkpoint_writes"][0] > 0
    env = {
        **os.environ,
        "COUNTERPARTY_DATABASE_URL": dsn.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        ),
    }
    command = [str(ROOT / "migrations/.venv/bin/python"), "-m", "alembic"]
    try:
        subprocess.run(
            [*command, "downgrade", "0004"],
            cwd=ROOT / "migrations",
            env=env,
            check=True,
        )
        assert digests(dsn) == before
    finally:
        subprocess.run(
            [*command, "upgrade", "head"], cwd=ROOT / "migrations", env=env, check=True
        )
    assert digests(dsn) == before
    subprocess.run([*command, "check"], cwd=ROOT / "migrations", env=env, check=True)
    print(
        json.dumps(
            {
                "framework_roundtrip": "passed",
                "row_counts": {name: data[0] for name, data in before.items()},
            }
        )
    )


if __name__ == "__main__":
    main()
