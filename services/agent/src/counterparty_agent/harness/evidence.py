"""Where a model answer stops being text and has to be grounded (AG-03).

This is the applied boundary of the service, not a framework feature, so it is
written here deliberately. It answers one question: *may this sentence reach
the user as a fact?*

The rule, in full:

* the answer is split into claims -- one per line, then per sentence;
* a claim is exempt when it is a question, a heading, an empty/bullet marker,
  or a non-numeric line under one of :data:`~.prompts.UNKNOWN_HEADINGS`
  (naming a gap is allowed, quoting a number under that heading is not);
* every other claim must carry at least one ``[evidence:<id>]`` citation, and
  every cited id must resolve.

Resolution is delegated to :class:`EvidenceResolver`. The default resolver is
:class:`RunEvidenceLedger`: an id resolves only when this run actually observed
it in a tool result. That has two consequences worth stating. A model cannot
invent an id, because it never saw one that the tools did not return. And a
ledger belongs to one run of one thread, so an id learned in another thread
does not resolve here -- grounding inherits the isolation of the thread.

The ledger deliberately does not verify that the *claim* matches the source;
it verifies that a source was named and can be opened. Matching value to text
is an eval question (Specs 08 §5), not a parser's.
"""

import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .prompts import (
    UNKNOWN_HEADING,
    UNKNOWN_HEADINGS,
    UNVERIFIED_DROPPED,
    UNVERIFIED_FALLBACK,
)

CITATION = re.compile(r"\[evidence:([^\]\s]+)\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_DIGIT = re.compile(r"\d")
_EVIDENCE_KEYS = ("evidence_refs", "evidence_ref_ids", "input_refs")


class UnresolvableEvidenceError(ValueError):
    """Raised when an answer cannot be repaired into a grounded one."""


class EvidenceResolver(Protocol):
    """Decides whether one evidence reference can actually be opened."""

    def resolves(self, evidence_ref_id: str) -> bool:
        """Return whether the reference points at a known source."""
        ...

    def known_refs(self) -> Sequence[str]:
        """List the references an answer may cite, for the repair prompt."""
        ...


@dataclass(slots=True)
class RunEvidenceLedger:
    """Evidence references observed in the tool results of one run."""

    refs: set[str] = field(default_factory=set)
    report_ids: set[str] = field(default_factory=set)

    def observe(self, payload: object) -> None:
        """Record every evidence reference carried by one tool result."""
        for value in _walk(_as_json(payload)):
            if not isinstance(value, Mapping):
                continue
            for key in _EVIDENCE_KEYS:
                self.refs.update(_strings(value.get(key)))
            if _is_evidence_ref(value):
                self.refs.add(str(value["id"]))
            report_id = value.get("report_id")
            if isinstance(report_id, str):
                self.report_ids.add(report_id)

    def resolves(self, evidence_ref_id: str) -> bool:
        """Return whether this run observed the reference in a tool result."""
        return evidence_ref_id in self.refs

    def known_refs(self) -> Sequence[str]:
        """Return the observed references in a stable order."""
        return sorted(self.refs)


def _is_evidence_ref(value: Mapping[str, object]) -> bool:
    """Whether a mapping is a serialized ``EvidenceRef`` rather than a container."""
    return (
        isinstance(value.get("id"), str)
        and value.get("kind") is not None
        and value.get("schema_version") is not None
    )


def _as_json(payload: object) -> object:
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except (TypeError, ValueError):
            return {}
    if hasattr(payload, "model_dump"):
        dumped: Any = payload.model_dump(mode="json")
        return dumped
    return payload


def _walk(node: object) -> Iterator[object]:
    yield node
    if isinstance(node, Mapping):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list | tuple):
        for value in node:
            yield from _walk(value)


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(item for item in value if isinstance(item, str))
    return ()


@dataclass(frozen=True, slots=True)
class Claim:
    """One sentence of the answer and the references it cites."""

    text: str
    refs: tuple[str, ...]
    exempt: bool

    @property
    def is_factual(self) -> bool:
        """Whether this claim must be grounded before it reaches the user."""
        return not self.exempt


@dataclass(frozen=True, slots=True)
class Violation:
    """One reason a claim is not allowed through."""

    claim: str
    reason: str
    refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairedAnswer:
    """A publishable answer and the claims removed to make it publishable."""

    text: str
    dropped: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Outcome of checking one answer against a resolver."""

    claims: tuple[Claim, ...]
    violations: tuple[Violation, ...]

    @property
    def ok(self) -> bool:
        """Whether every factual claim is grounded in a resolvable source."""
        return not self.violations


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("#") or (stripped.endswith(":") and not _DIGIT.search(stripped))


def _heading_key(line: str) -> str:
    return line.strip().lstrip("#").strip().rstrip(":").strip().lower()


def split_claims(answer: str) -> tuple[Claim, ...]:
    """Split an answer into claims, marking the exempt ones."""
    claims: list[Claim] = []
    under_unknown = False
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_heading(line):
            under_unknown = _heading_key(line) in UNKNOWN_HEADINGS
            claims.append(Claim(text=line, refs=(), exempt=True))
            continue
        body = _BULLET.sub("", line).strip()
        if not body:
            continue
        for sentence in _SENTENCE_SPLIT.split(body):
            text = sentence.strip()
            if not text:
                continue
            refs = tuple(CITATION.findall(text))
            exempt = text.endswith("?") or (under_unknown and not _DIGIT.search(text))
            claims.append(Claim(text=text, refs=refs, exempt=exempt))
    return tuple(claims)


def validate_answer(answer: str, resolver: EvidenceResolver) -> ValidationReport:
    """Check that every factual claim names a reference that resolves."""
    claims = split_claims(answer)
    violations: list[Violation] = []
    for claim in claims:
        if not claim.is_factual:
            continue
        if not claim.refs:
            violations.append(Violation(claim=claim.text, reason="missing_evidence_ref"))
            continue
        unresolved = tuple(ref for ref in claim.refs if not resolver.resolves(ref))
        if unresolved:
            violations.append(
                Violation(claim=claim.text, reason="unresolvable_evidence_ref", refs=unresolved)
            )
    return ValidationReport(claims=claims, violations=tuple(violations))


def repair_answer(answer: str, resolver: EvidenceResolver) -> "RepairedAnswer":
    """Drop every ungrounded claim and say plainly that something was dropped.

    This is the last, deterministic pass. It runs after the model has had its
    chance to add references, so its output is always publishable: no
    ungrounded sentence survives it, and no unverified number is repeated back
    to the user under a disclaimer. The dropped claims are returned separately
    for the run log, not for the answer.
    """
    report = validate_answer(answer, resolver)
    if report.ok:
        return RepairedAnswer(text=answer, dropped=())
    rejected = tuple(sorted({violation.claim for violation in report.violations}))
    kept = [claim.text for claim in report.claims if claim.text not in rejected]
    while kept and _is_heading(kept[-1]):
        kept.pop()
    notes = [UNVERIFIED_DROPPED]
    if not any(not _is_heading(text) for text in kept):
        kept = []
        notes.insert(0, UNVERIFIED_FALLBACK)
    lines = [*kept, "", UNKNOWN_HEADING, *(f"- {note}" for note in notes)]
    return RepairedAnswer(text="\n".join(lines).strip(), dropped=rejected)
