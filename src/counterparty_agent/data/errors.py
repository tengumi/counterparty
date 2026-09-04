"""Безопасные типизированные ошибки источника."""

from __future__ import annotations

from counterparty_agent.models import (
    SourceOutcome,
)


class SnapshotSourceError(RuntimeError):
    """Безопасная ошибка загрузки источника без содержимого исходной записи."""

    def __init__(self, outcome: SourceOutcome, code: str, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.code = code
