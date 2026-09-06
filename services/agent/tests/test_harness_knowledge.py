"""Knowledge entry integrity and empty lookup results."""

from counterparty_agent.harness.knowledge import (
    REFERENCE,
    lookup,
    render_relevant,
)

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


def test_lookup_returns_nothing_for_unrelated_text() -> None:
    """No topic mentioned means no fragment selected."""
    assert lookup("hello world, unrelated question") == ()


def test_render_relevant_is_empty_without_matches() -> None:
    """An empty selection renders no section at all."""
    assert render_relevant(()) == ""
