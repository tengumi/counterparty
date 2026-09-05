"""Typed, resolvable evidence references and document locators."""

import re
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import ContractModel, SchemaVersion
from .enums import EvidenceKind
from .identifiers import (
    ArtifactId,
    CompanyId,
    DocumentId,
    EvidenceRefId,
    FragmentId,
    ReportId,
)

NonEmptyString = Annotated[str, Field(min_length=1)]
_JSON_POINTER = re.compile(r"/(?:[^~]|~[01])*")


class SpreadsheetRangeLocator(ContractModel):
    """A cell or range in a named spreadsheet sheet."""

    kind: Literal["spreadsheet_range"] = "spreadsheet_range"
    sheet: str = Field(min_length=1)
    range: str = Field(min_length=1)


class WordBlockLocator(ContractModel):
    """A paragraph or table location in a word-processing document."""

    kind: Literal["word_block"] = "word_block"
    paragraph_id: NonEmptyString | None = None
    table_id: NonEmptyString | None = None
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_block_id(self) -> "WordBlockLocator":
        """Require a stable paragraph or table identity."""
        if self.paragraph_id is None and self.table_id is None:
            raise ValueError("word_block requires paragraph_id or table_id")
        return self


class PdfPageLocator(ContractModel):
    """A page, optionally with coordinates, in a PDF document."""

    kind: Literal["pdf_page"] = "pdf_page"
    page: int = Field(ge=1)
    bbox: list[float] | None = None


class TextLinesLocator(ContractModel):
    """An inclusive line range in a text representation."""

    kind: Literal["text_lines"] = "text_lines"
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> "TextLinesLocator":
        """Keep the inclusive line range ordered."""
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


DocumentLocator = Annotated[
    SpreadsheetRangeLocator | WordBlockLocator | PdfPageLocator | TextLinesLocator,
    Field(discriminator="kind"),
]


class EvidenceRef(ContractModel):
    """A stable reference to one source or a deterministic derivation."""

    schema_version: SchemaVersion = "0.1"
    id: EvidenceRefId
    kind: EvidenceKind
    report_id: ReportId | None = None
    company_id: CompanyId | None = None
    source_path: NonEmptyString | None = None
    document_id: DocumentId | None = None
    fragment_id: FragmentId | None = None
    page: int | None = Field(default=None, ge=1)
    locator: DocumentLocator | None = None
    artifact_id: ArtifactId | None = None
    artifact_version: int | None = Field(default=None, ge=1)
    message_id: NonEmptyString | None = None
    period: int | str | None = None
    input_refs: list[EvidenceRefId] = Field(default_factory=list)
    rule_version: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_kind_requirements(self) -> "EvidenceRef":
        """Ensure each provenance kind remains resolvable by the server."""
        required: dict[EvidenceKind, tuple[object | None, ...]] = {
            EvidenceKind.REPORT_FIELD: (self.report_id, self.source_path),
            EvidenceKind.DOCUMENT_FRAGMENT: (self.document_id, self.fragment_id),
            EvidenceKind.USER_MESSAGE: (self.message_id,),
            EvidenceKind.ARTIFACT_SECTION: (self.artifact_id, self.artifact_version),
            EvidenceKind.DERIVED: (self.input_refs or None, self.rule_version),
        }
        if any(value is None for value in required[self.kind]):
            raise ValueError(f"{self.kind.value} evidence is missing its required locator")
        if (
            self.kind is EvidenceKind.REPORT_FIELD
            and self.source_path is not None
            and _JSON_POINTER.fullmatch(self.source_path) is None
        ):
            raise ValueError("report source_path must be a non-empty RFC 6901 JSON Pointer")
        return self
