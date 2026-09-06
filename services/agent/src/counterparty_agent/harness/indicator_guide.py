"""A small reference the agent can quote when asked what a report field means.

``indicator_guide.md`` is the product's field dictionary: every report path with
a plain-language meaning, plus the definitions of the bank traffic light and the
ЗСК signal. These are *definitions*, not facts about a company, so an answer
built from them needs no evidence reference — the ``explain_indicator`` tool
below is what the agent uses for "что такое …" / "что значит …" questions.

The search is deliberately the simplest thing that works: lower-case token
overlap over the entry text. No index, no embedding.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

__all__ = ["GuideEntry", "explain_indicator", "search_guide"]

_ROW = re.compile(r"^\|\s*`?([^`|]+?)`?\s*\|\s*(.+?)\s*\|\s*$")
_HEADING = re.compile(r"^#+\s*\**\s*(.+?)\s*\**\s*$")
_WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
_REFLINK = re.compile(r"^\[\d+\]:\s")
_TERM_HEAD = re.compile(r"^(.{6,80}?)\s*(?:—|-|:| Это | это )")


@dataclass(frozen=True, slots=True)
class GuideEntry:
    """One term or field with its plain-language meaning and section."""

    name: str
    meaning: str
    section: str
    is_field: bool = True

    @property
    def text(self) -> str:
        """The line an answer can quote."""
        return f"{self.name} — {self.meaning}" if self.is_field else self.meaning


def _load_text() -> str:
    return (
        resources.files("counterparty_agent.harness")
        .joinpath("indicator_guide.md")
        .read_text(encoding="utf-8")
    )


@lru_cache(maxsize=1)
def _entries() -> tuple[GuideEntry, ...]:
    entries: list[GuideEntry] = []
    section = "Общее"
    para: list[str] = []

    def flush_para() -> None:
        if not para:
            return
        joined = " ".join(part.strip() for part in para if part.strip())
        # Drop the "([source][1])" and markdown-link citations the guide carries.
        joined = re.sub(r"\s*\(\[[^)]*\]\)", "", joined)
        joined = re.sub(r"\s*Официальные источники:.*$", "", joined).strip()
        para.clear()
        if len(joined) < 40:
            return
        head_match = _TERM_HEAD.match(joined)
        head = head_match.group(1).strip() if head_match else section
        entries.append(GuideEntry(name=head, meaning=joined, section=section, is_field=False))

    for raw in _load_text().splitlines():
        line = raw.strip()
        if not line or set(line) <= {"-", "|", " "} or _REFLINK.match(line):
            flush_para()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_para()
            section = heading.group(1).strip()
            continue
        row = _ROW.match(line)
        if row:
            flush_para()
            name, meaning = row.group(1).strip(), row.group(2).strip()
            if name.lower() in {"поле (спецификация)", "значение"} or not meaning:
                continue
            entries.append(GuideEntry(name=name, meaning=meaning, section=section))
            continue
        para.append(line)
    flush_para()
    return tuple(entries)


def _tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in _WORD.finditer(value)}


def search_guide(query: str, *, limit: int = 6) -> list[GuideEntry]:
    """Return the guide entries whose text best overlaps the query."""
    wanted = _tokens(query)
    if not wanted:
        return []
    scored: list[tuple[int, int, GuideEntry]] = []
    for index, entry in enumerate(_entries()):
        haystack = _tokens(f"{entry.name} {entry.meaning} {entry.section}")
        overlap = len(wanted & haystack)
        if overlap:
            # Prefer a name hit, then more overlap, then document order.
            name_hit = 1 if wanted & _tokens(entry.name) else 0
            scored.append((-(name_hit * 5 + overlap), index, entry))
    scored.sort()
    return [entry for _, _, entry in scored[:limit]]


def explain_indicator(query: str) -> str:
    """Look up what a report field or risk signal means (for 'что такое …')."""
    hits = search_guide(query)
    if not hits:
        return f"В справочнике показателей нет подходящей статьи по запросу «{query.strip()}»."
    return "\n".join(f"- {hit.text}" for hit in hits)
