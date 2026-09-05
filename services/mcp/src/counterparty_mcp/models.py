"""Typed request-independent output models for the MCP shell."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from counterparty_contracts import ErrorCode
from pydantic import BaseModel, ConfigDict, Field


class McpStatus(StrEnum):
    """Business outcome of an MCP tool call."""

    OK = "ok"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class ToolError(BaseModel):
    """Safe structured business error returned inside a tool envelope."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool = False


class CompanyOverviewStub(BaseModel):
    """Placeholder data marker until the reports repository is connected."""

    model_config = ConfigDict(extra="forbid")

    implementation: Literal["stub"] = "stub"
    lookup_inn: str | None = None
    lookup_report_id: UUID | None = None


class CompanyOverviewEnvelope(BaseModel):
    """MCP envelope shape for the overview read operation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1"] = "0.1"
    status: McpStatus
    data: CompanyOverviewStub | None = None
    errors: list[ToolError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_report_ids: list[UUID] = Field(default_factory=list)
    rule_version: Literal["stub-v0"] = "stub-v0"
