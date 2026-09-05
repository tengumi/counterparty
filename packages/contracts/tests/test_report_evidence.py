"""Evidence responses bind one issued report ref to the same snapshot."""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from counterparty_contracts import ReportEvidence


def payload() -> dict[str, Any]:
    """Return one minimal grounded source fragment."""
    report_id = str(uuid4())
    return {
        "evidence": {
            "id": f"report:{report_id}:/baseInfo/inn",
            "kind": "report_field",
            "report_id": report_id,
            "source_path": "/baseInfo/inn",
        },
        "report": {
            "id": report_id,
            "source_report_at": "2026-09-05T00:00:00Z",
            "ingested_at": "2026-09-05T01:00:00Z",
        },
        "availability": "available",
        "value": 0,
    }


def test_report_evidence_preserves_zero_and_explicit_empty() -> None:
    """Neither a reported zero nor an explicit null is a missing source."""
    data = payload()
    assert ReportEvidence.model_validate(data).value == 0
    data.update(availability="present_empty", value=None)
    assert ReportEvidence.model_validate(data).availability.value == "present_empty"


@pytest.mark.parametrize("change", ["kind", "report", "missing", "restricted"])
def test_report_evidence_rejects_wrong_scope_and_unavailable_payload(change: str) -> None:
    """Kinds, snapshot identity and unavailable values cannot be substituted."""
    data = payload()
    if change == "kind":
        data["evidence"] = {"id": "message:x", "kind": "user_message", "message_id": "x"}
    elif change == "report":
        data["report"]["id"] = str(uuid4())
    else:
        data["availability"] = change
    with pytest.raises(ValidationError):
        ReportEvidence.model_validate(data)
