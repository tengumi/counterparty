"""Cursor pagination and response metadata shared by list endpoints."""

from pydantic import Field

from .base import ContractModel, NonEmptyString, SchemaVersion, UtcDatetime

__all__ = ["DEFAULT_PAGE_LIMIT", "MAX_PAGE_LIMIT", "Page", "PageInfo", "ResponseMeta"]

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


class PageInfo(ContractModel):
    """Where one page ends and how to ask for the next one.

    ``has_more`` is authoritative: an empty page does not by itself prove that
    a collection is exhausted.
    """

    limit: int = Field(ge=1, le=MAX_PAGE_LIMIT)
    next_cursor: NonEmptyString | None = None
    has_more: bool


class Page[ItemT](ContractModel):
    """One page of a cursor-paginated collection."""

    schema_version: SchemaVersion = "0.1"
    items: list[ItemT] = Field(default_factory=list)
    page: PageInfo


class ResponseMeta(ContractModel):
    """Correlation and cache metadata attached to a response.

    ``version`` and ``checksum`` are populated only where a client caches the
    payload; neither is a substitute for the ``context_version`` of a project.
    """

    request_id: NonEmptyString
    generated_at: UtcDatetime
    version: int | None = Field(default=None, ge=0)
    checksum: NonEmptyString | None = None
