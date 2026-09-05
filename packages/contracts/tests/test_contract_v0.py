"""Contract v0 behavior and serialization tests."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

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
        id="report:fixture:finance:2025:proceeds",
        kind=EvidenceKind.REPORT_FIELD,
        report_id=REPORT_ID,
        source_path="/finReports/0/common/proceeds",
        period=2025,
    )

    assert evidence.source_path == "/finReports/0/common/proceeds"
    assert evidence.model_dump(mode="json")["report_id"] == str(REPORT_ID)


def test_report_evidence_accepts_rfc_6901_escaped_tokens() -> None:
    """RFC 6901 tilde and slash escapes remain valid logical source paths."""
    evidence = EvidenceRef(
        id="report:escaped",
        kind=EvidenceKind.REPORT_FIELD,
        report_id=REPORT_ID,
        source_path="/field~0name/nested~1key",
    )

    assert evidence.source_path == "/field~0name/nested~1key"


@pytest.mark.parametrize("source_path", ["", "not/a/pointer", "/bad~2escape", "/trailing~"])
def test_report_evidence_rejects_invalid_json_pointer(source_path: str) -> None:
    """A report field must use a non-empty, correctly escaped RFC 6901 pointer."""
    with pytest.raises(ValidationError):
        EvidenceRef(
            id="report:invalid-pointer",
            kind=EvidenceKind.REPORT_FIELD,
            report_id=REPORT_ID,
            source_path=source_path,
        )


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


@pytest.mark.parametrize(
    "payload",
    [
        {
            "id": "",
            "kind": EvidenceKind.REPORT_FIELD,
            "report_id": REPORT_ID,
            "source_path": "/field",
        },
        {"id": "ref", "kind": EvidenceKind.USER_MESSAGE, "message_id": ""},
        {
            "id": "ref",
            "kind": EvidenceKind.DERIVED,
            "input_refs": [""],
            "rule_version": "rule-v1",
        },
        {
            "id": "ref",
            "kind": EvidenceKind.DERIVED,
            "input_refs": ["input-ref"],
            "rule_version": "",
        },
    ],
)
def test_opaque_evidence_identifiers_are_non_empty(payload: dict[str, object]) -> None:
    """Required opaque IDs and rule versions cannot be empty strings."""
    with pytest.raises(ValidationError, match="at least 1 character"):
        EvidenceRef.model_validate(payload)


def test_evidence_ref_id_alias_rejects_empty_value() -> None:
    """The reusable opaque ID type carries its non-empty wire constraint."""
    with pytest.raises(ValidationError, match="at least 1 character"):
        TypeAdapter(EvidenceRefId).validate_python("")


def test_derived_evidence_accepts_non_empty_inputs_and_rule_version() -> None:
    """A resolvable derivation retains its complete provenance chain."""
    evidence = EvidenceRef.model_validate(
        {
            "id": "derived:liquidity:v1",
            "kind": EvidenceKind.DERIVED,
            "input_refs": ["report:cash", "report:payables"],
            "rule_version": "liquidity-v1",
        }
    )

    assert evidence.input_refs == ["report:cash", "report:payables"]
    assert evidence.rule_version == "liquidity-v1"


def test_artifact_version_must_be_positive() -> None:
    """An artifact reference must identify an existing immutable version."""
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        EvidenceRef.model_validate(
            {
                "id": "artifact:invalid-version",
                "kind": EvidenceKind.ARTIFACT_SECTION,
                "artifact_id": "00000000-0000-4000-8000-000000000005",
                "artifact_version": 0,
            }
        )


def test_text_line_locator_must_be_ordered() -> None:
    """Document coordinates cannot point to an inverted range."""
    with pytest.raises(ValidationError, match="end_line must not precede start_line"):
        TextLinesLocator(start_line=8, end_line=3)


def test_availability_and_decision_outcome_remain_distinct() -> None:
    """The decision enum does not collapse missing information into a risk result."""
    assert DecisionOutcome.NEED_MORE_INFO.value == "need_more_info"
    assert len({DecisionOutcome.NOT_READY.value, DecisionOutcome.NEED_MORE_INFO.value}) == 2
