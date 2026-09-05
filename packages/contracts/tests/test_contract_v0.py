"""Contract v0 behavior and serialization tests."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from counterparty_contracts import (
    DecisionOutcome,
    EvidenceKind,
    EvidenceRef,
    EvidenceRefId,
    ProjectEnvelope,
    ProjectId,
    ReportId,
    RunId,
    RunInfo,
    RunStatus,
    TextLinesLocator,
    ThreadId,
    WorkflowStatus,
)

PROJECT_ID = ProjectId(UUID("00000000-0000-4000-8000-000000000001"))
THREAD_ID = ThreadId(UUID("00000000-0000-4000-8000-000000000002"))
RUN_ID = RunId(UUID("00000000-0000-4000-8000-000000000003"))
REPORT_ID = ReportId(UUID("00000000-0000-4000-8000-000000000004"))


def test_project_envelope_serializes_uuid_and_utc_timestamp() -> None:
    """The public envelope emits wire-ready UUID strings and UTC timestamps."""
    envelope = ProjectEnvelope(
        id=PROJECT_ID,
        title="Проверка поставщика",
        default_thread_id=THREAD_ID,
        threads_count=1,
        context_version=0,
        workflow_status=WorkflowStatus.IN_PROGRESS,
        created_at=datetime(2026, 9, 5, 15, 0, tzinfo=timezone(timedelta(hours=3))),
        updated_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )

    payload = envelope.model_dump(mode="json")

    assert payload["id"] == str(PROJECT_ID)
    assert payload["default_thread_id"] == str(THREAD_ID)
    assert payload["created_at"] == "2026-09-05T12:00:00Z"
    assert payload["schema_version"] == "0.1"


def test_naive_timestamp_is_rejected() -> None:
    """A timestamp without its UTC relationship is not accepted."""
    with pytest.raises(ValidationError, match="timestamp must include a timezone"):
        RunInfo(
            id=RUN_ID,
            thread_id=THREAD_ID,
            project_id=PROJECT_ID,
            status=RunStatus.ACCEPTED,
            started_at=datetime(2026, 9, 5, 12, 0),
            based_on_context_version=0,
            last_public_revision=0,
        )


def test_report_evidence_preserves_lossless_json_pointer() -> None:
    """Evidence refers to raw report data without assuming its Mongo source shape."""
    evidence = EvidenceRef(
        id=EvidenceRefId("report:fixture:finance:2025:proceeds"),
        kind=EvidenceKind.REPORT_FIELD,
        report_id=REPORT_ID,
        source_path="/finReports/0/common/proceeds",
        period=2025,
    )

    assert evidence.source_path == "/finReports/0/common/proceeds"
    assert evidence.model_dump(mode="json")["report_id"] == str(REPORT_ID)


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (EvidenceKind.REPORT_FIELD, {}),
        (EvidenceKind.DOCUMENT_FRAGMENT, {}),
        (EvidenceKind.USER_MESSAGE, {}),
        (EvidenceKind.ARTIFACT_SECTION, {}),
        (EvidenceKind.DERIVED, {"input_refs": ["ref-1"]}),
    ],
)
def test_unresolvable_evidence_is_rejected(kind: EvidenceKind, fields: dict[str, object]) -> None:
    """Every evidence kind requires enough fields for server-side resolution."""
    with pytest.raises(ValidationError, match="missing its required locator"):
        EvidenceRef.model_validate({"id": "invalid", "kind": kind, **fields})


def test_text_line_locator_must_be_ordered() -> None:
    """Document coordinates cannot point to an inverted range."""
    with pytest.raises(ValidationError, match="end_line must not precede start_line"):
        TextLinesLocator(start_line=8, end_line=3)


def test_availability_and_decision_outcome_remain_distinct() -> None:
    """The decision enum does not collapse missing information into a risk result."""
    assert DecisionOutcome.NEED_MORE_INFO.value == "need_more_info"
    assert len({DecisionOutcome.NOT_READY.value, DecisionOutcome.NEED_MORE_INFO.value}) == 2
