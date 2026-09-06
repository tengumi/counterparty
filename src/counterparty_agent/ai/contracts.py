"""Типы разрешённых фактов, ответов и ошибок модели."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from counterparty_agent.ai.prompts import MAX_ANSWER_FACTS

ChatRole = Literal["user", "assistant"]
ReviewTopic = Literal[
    "company",
    "finance",
    "arbitration",
    "enforcement",
    "reputation",
    "licenses",
    "data_quality",
    "documents",
]


ChatHistory = Sequence[tuple[ChatRole, str]]


GroundedStatus = Literal["answered", "insufficient_data", "llm_unavailable", "validation_failed"]


class LlmNotConfiguredError(RuntimeError):
    """Ошибка при отсутствии настроенного API-ключа провайдер."""


class LlmContextLimitError(ValueError):
    """Контекст не помещается в лимит и не должен незаметно обрезаться."""


class LlmInvalidResponseError(ValueError):
    """Ответ провайдера пуст, прерван или не соответствует ожидаемому формату."""


class GroundedClaim(BaseModel):
    """Серверный текст с доказательствами, а не свободная формулировка модели."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, repr=False)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class ReviewBlock(BaseModel):
    """Короткий абзац анализа с проверяемыми основаниями."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["fact", "interpretation", "limitation", "action"]
    text: str = Field(min_length=1, max_length=1100)
    fact_ids: list[str] = Field(min_length=1, max_length=32)


class ReviewDraft(BaseModel):
    """Общий формат модельного и резервного ответа; правила проверки одинаковые."""

    model_config = ConfigDict(extra="forbid")
    blocks: list[ReviewBlock] = Field(min_length=1, max_length=8)


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """Проверенный ответ или безопасный исход без неподтверждённых утверждений."""

    status: GroundedStatus
    answer: str = field(repr=False)
    claims: tuple[GroundedClaim, ...]
    fact_ids: tuple[str, ...]
    model: str | None
    used_llm: bool


class _FactSelection(BaseModel):
    """Минимальная схема ответа модели с запретом дополнительных полей."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["answered", "insufficient_data"]
    fact_ids: tuple[str, ...] = Field(max_length=MAX_ANSWER_FACTS)

    @model_validator(mode="after")
    def validate_selection(self) -> _FactSelection:
        if len(set(self.fact_ids)) != len(self.fact_ids):
            raise ValueError("Повторяющиеся идентификаторы фактов")
        if bool(self.fact_ids) != (self.status == "answered"):
            raise ValueError("Статус не соответствует набору фактов")
        return self


@dataclass(frozen=True, slots=True)
class ApprovedFact:
    """Допустимый факт каталога, связанный с конкретной версией снимка."""

    fact_id: str
    claim: GroundedClaim
    topic: str
    period: int | None = None
    metric: str | None = None
    signal_code: str | None = None


@dataclass(frozen=True, slots=True)
class LlmResult:
    """Независимый от провайдера результат для слоя API."""

    answer: str = field(repr=False)
    model: str
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
