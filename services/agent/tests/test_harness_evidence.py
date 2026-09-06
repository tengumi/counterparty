"""Where an answer stops being text: the grounding boundary (AG-03)."""

import json

from harness_fixtures import CAPITAL_REF, PROCEEDS_REF, company_overview

from counterparty_agent.harness import (
    RunEvidenceLedger,
    repair_answer,
    split_claims,
    validate_answer,
)
from counterparty_agent.harness.prompts import UNKNOWN_HEADING, UNVERIFIED_FALLBACK


def ledger() -> RunEvidenceLedger:
    """Build a ledger that observed one overview envelope."""
    observed = RunEvidenceLedger()
    observed.observe(company_overview().model_dump_json())
    return observed


def test_ledger_collects_refs_from_a_real_envelope() -> None:
    """Ledger collects refs from a real envelope."""
    assert PROCEEDS_REF in ledger().known_refs()


def test_ledger_ignores_a_ref_it_never_observed() -> None:
    """Ledger ignores a ref it never observed."""
    assert not ledger().resolves(CAPITAL_REF)


def test_ledger_survives_a_tool_result_that_is_not_json() -> None:
    """Ledger survives a tool result that is not json."""
    observed = RunEvidenceLedger()
    observed.observe("connection reset")
    assert observed.known_refs() == []


def test_ledger_reads_a_nested_tool_payload() -> None:
    """Ledger reads a nested tool payload."""
    observed = RunEvidenceLedger()
    observed.observe(json.dumps({"data": {"records": [{"evidence_refs": ["ev-1"]}]}}))
    assert observed.resolves("ev-1")


def test_ledger_reads_a_content_block_tool_result() -> None:
    """The MCP adapter returns text content blocks, not a JSON string."""
    observed = RunEvidenceLedger()
    observed.observe(
        [
            {"type": "text", "text": '{"data": {"facts": ['},
            {
                "type": "text",
                "text": '{"evidence_refs": ["report:r1:/finReports/0/common/profit"]}]}}',
            },
        ]
    )
    assert observed.resolves("report:r1:/finReports/0/common/profit")


def test_a_cited_claim_passes() -> None:
    """A cited claim passes."""
    answer = f"- Proceeds 2025: 74586000 RUB [evidence:{PROCEEDS_REF}]"
    assert validate_answer(answer, ledger()).ok


def test_a_claim_without_a_ref_is_refused() -> None:
    """A claim without a ref is refused."""
    report = validate_answer("- Proceeds 2025 grew by 12 percent.", ledger())
    assert [violation.reason for violation in report.violations] == ["missing_evidence_ref"]


def test_a_claim_citing_an_unknown_ref_is_refused() -> None:
    """A claim citing an unknown ref is refused."""
    report = validate_answer("- Capitals: -300000 [evidence:ev-invented]", ledger())
    assert [violation.reason for violation in report.violations] == ["unresolvable_evidence_ref"]
    assert report.violations[0].refs == ("ev-invented",)


def test_a_ref_from_another_run_does_not_resolve() -> None:
    """A ledger belongs to one run of one thread, so grounding is scoped too."""
    other_run = RunEvidenceLedger(refs={"ev-from-another-thread"})
    answer = "- Capitals: -300000 [evidence:ev-from-another-thread]"
    assert validate_answer(answer, other_run).ok
    assert not validate_answer(answer, ledger()).ok


def test_a_question_needs_no_ref() -> None:
    """A question needs no ref."""
    assert validate_answer("When will the goods be ready?", ledger()).ok


def test_a_gap_under_the_unknown_heading_needs_no_ref() -> None:
    """A gap under the unknown heading needs no ref."""
    answer = f"{UNKNOWN_HEADING}\n- The delivery date is not stated anywhere."
    assert validate_answer(answer, ledger()).ok


def test_a_number_under_the_unknown_heading_still_needs_a_ref() -> None:
    """A number under the unknown heading still needs a ref."""
    answer = f"{UNKNOWN_HEADING}\n- Capitals were -300000 last year."
    assert not validate_answer(answer, ledger()).ok


def test_split_marks_headings_and_sentences() -> None:
    """Split marks headings and sentences."""
    claims = split_claims("Findings:\n- One. Two.")
    assert [claim.exempt for claim in claims] == [True, False, False]


def test_repair_keeps_the_grounded_claim_and_drops_the_rest() -> None:
    """Repair keeps the grounded claim and drops the rest."""
    answer = (
        f"- Proceeds 2025: 74586000 RUB [evidence:{PROCEEDS_REF}]\n"
        "- The company will certainly deliver in 21 days."
    )
    outcome = repair_answer(answer, ledger())
    assert PROCEEDS_REF in outcome.text
    assert "21 days" not in outcome.text
    assert outcome.dropped == ("The company will certainly deliver in 21 days.",)


def test_repair_never_republishes_an_unverified_number() -> None:
    """Repair never republishes an unverified number."""
    outcome = repair_answer("- Capitals: -300000 [evidence:ev-invented]", ledger())
    assert "-300000" not in outcome.text
    assert UNVERIFIED_FALLBACK in outcome.text


def test_a_repaired_answer_always_validates() -> None:
    """A repaired answer always validates."""
    answer = "- Revenue doubled.\n- Capitals: -300000 [evidence:ev-invented]"
    outcome = repair_answer(answer, ledger())
    assert validate_answer(outcome.text, ledger()).ok


def test_currency_after_abbreviation_stays_with_its_cited_amount() -> None:
    """Repair must preserve amounts, but still reject a later uncited claim."""
    for currency in ("₽", "RUB"):
        answer = f"Profit: 23 thousand-abbr. {currency} [evidence:{PROCEEDS_REF}]."
        assert validate_answer(answer, ledger()).ok
        assert repair_answer(answer, ledger()).text == answer
        combined = answer + " Unverified claim."
        repaired = repair_answer(combined, ledger())
        assert answer in repaired.text
        assert "Unverified claim." not in repaired.text
