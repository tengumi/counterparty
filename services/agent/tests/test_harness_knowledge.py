"""AG-06: the domain-knowledge reference and its internal lookup (Specs 04 §6).

The reference is versioned, sourced and carries worked examples; the lookup is
a plain keyword match with no vector search. These checks pin all three.
"""

from dataclasses import replace
from uuid import uuid4

import pytest

from counterparty_agent.harness.context import build_context
from counterparty_agent.harness.knowledge import (
    REFERENCE,
    REFERENCE_VERSION,
    lookup,
    render_reference,
    render_relevant,
)
from counterparty_agent.harness.prompts import render_system_prompt

_SOURCES = {"case", "qa", "verified_reference"}


def test_every_entry_is_versioned_sourced_and_has_a_worked_example() -> None:
    """Each entry carries provenance and at least one full example."""
    ids = [entry.id for entry in REFERENCE]
    assert len(ids) == len(set(ids)), "entry ids must be unique"
    for entry in REFERENCE:
        assert entry.version >= 1
        assert entry.source in _SOURCES
        assert entry.statement.strip()
        assert entry.topics and all(topic == topic.casefold() for topic in entry.topics)
        assert entry.examples, f"{entry.id} has no worked example"
        for example in entry.examples:
            assert example.signal.strip()
            assert example.correct.strip()
            assert example.incorrect.strip()


def test_reference_covers_every_specs_6_note() -> None:
    """One entry per obligatory note of Specs 04 §6."""
    assert {entry.id for entry in REFERENCE} == {
        "okved_mass",
        "bank_traffic_light",
        "zsk_vs_bank_risk",
        "enforcement_proceedings",
        "fns_block",
        "relocation_vs_capital_decrease",
        "no_universal_signals",
        "annual_report_cash",
        "counts_vs_performance",
    }


def test_the_standing_notes_name_the_reference_version() -> None:
    """The rendered baseline block pins the reference version and every statement."""
    rendered = render_reference()
    assert f"v{REFERENCE_VERSION}" in rendered
    for entry in REFERENCE:
        assert entry.statement in rendered


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Светофор зелёный, а капитал отрицательный — это нормально?", "bank_traffic_light"),
        ("Есть исполнительное производство на 15 тысяч, что с ним?", "enforcement_proceedings"),
        ("Он просит аванс 80%, на что смотреть?", "no_universal_signals"),
        ("Сколько у него закупок и контрактов в реестре?", "counts_vs_performance"),
        ("Что означает блокировка ФНС по счёту?", "fns_block"),
    ],
)
def test_lookup_selects_the_relevant_entry(question: str, expected: str) -> None:
    """A question about a topic pulls the entry that covers it."""
    assert expected in {entry.id for entry in lookup(question)}


def test_lookup_ranks_more_topic_matches_first_and_caps_the_result() -> None:
    """The entry matching the most distinct topics leads; the limit is honoured."""
    question = "ЗСК YELLOW и банковский светофор — это один риск или разные?"
    hits = lookup(question, limit=2)
    assert len(hits) <= 2
    assert hits[0].id == "zsk_vs_bank_risk"


def test_lookup_returns_nothing_for_unrelated_text() -> None:
    """No topic mentioned means no fragment selected."""
    assert lookup("hello world, unrelated question") == ()


def test_render_relevant_is_empty_without_matches() -> None:
    """An empty selection renders no section at all."""
    assert render_relevant(()) == ""


def test_render_relevant_shows_the_statement_and_a_worked_example() -> None:
    """The selected block carries the guidance and its correct/incorrect framing."""
    entries = lookup("светофор при отрицательном капитале")
    block = render_relevant(entries)
    assert block.startswith("## ")
    first = entries[0]
    assert first.statement in block
    assert first.examples[0].correct in block
    assert first.examples[0].incorrect in block


def test_the_system_prompt_carries_the_selected_notes() -> None:
    """The runner-filled relevant notes reach the rendered system prompt."""
    base = build_context(
        project_id=uuid4(),
        tenant_id=uuid4(),
        title="Проверка",
        workflow_status="collecting",
        context_version=1,
        companies=[],
        thread_id=uuid4(),
        thread_title="Чат",
        thread_status="active",
    )
    selected = lookup("зелёный светофор, но капитал отрицательный")
    context = replace(base, relevant_notes=render_relevant(selected))
    prompt = render_system_prompt(context)

    assert render_relevant(selected) in prompt
    # The full standing notes are still present as the baseline.
    for entry in REFERENCE:
        assert entry.statement in prompt
