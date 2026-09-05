"""A read-only summary of a source file, used to check it before importing.

The summary answers the question the import report has to answer anyway: for
each section, in how many records was it absent, empty, populated or
unparsable. Those four are reported separately on purpose — "no rows" is not
evidence of "no events", and neither is a confirmed zero.
"""

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from counterparty_storage.reports import SourceState

from .approved_source import SourceVerification, verify_source
from .extended_json import decode, probe_section
from .fingerprint import snapshot_digest

__all__ = ["REPORT_SECTIONS", "SourceSummary", "summarize"]

#: Sections of ``report`` that the importer is expected to account for. A key
#: found in the source but absent from this tuple is reported as unknown rather
#: than ignored.
REPORT_SECTIONS: Final = (
    "baseInfo",
    "status",
    "kindsOfActivityInfo",
    "reportDate",
    "zskRiskLevel",
    "reputationalRisks",
    "arbitrationByStatus",
    "arbitrationCases",
    "executionProceedings",
    "procurements",
    "finReports",
    "coefficient",
    "foundersInfo",
    "taxSystem",
    "phones",
    "licenses",
    "inspections",
    "relatedCompanies",
    "branchesInfo",
)


@dataclass(frozen=True, slots=True)
class SourceSummary:
    """What one source file contains, without interpreting any value."""

    verification: SourceVerification
    record_count: int
    unique_snapshot_digests: int
    section_states: dict[str, dict[str, int]]
    unknown_sections: dict[str, int]
    decode_issues: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        """Render the summary as plain JSON-serializable data."""
        payload = asdict(self)
        payload["verification"]["path"] = str(self.verification.path)
        return payload


def summarize(path: Path, records: list[Any]) -> SourceSummary:
    """Describe a loaded source file section by section."""
    states: dict[str, Counter[str]] = {section: Counter() for section in REPORT_SECTIONS}
    unknown: Counter[str] = Counter()
    issues: Counter[str] = Counter()
    digests: set[str] = set()

    for record in records:
        digests.add(snapshot_digest(record))
        decoded = decode(record)
        for issue in decoded.issues:
            issues[issue.code.value] += 1
        report = decoded.value.get("report") if isinstance(decoded.value, dict) else None
        if not isinstance(report, dict):
            unknown["<missing report object>"] += 1
            continue
        for section in REPORT_SECTIONS:
            probe = probe_section(report, section)
            states[section][probe.state.value] += 1
        for key in report:
            if key not in REPORT_SECTIONS:
                unknown[key] += 1

    ordered = [state.value for state in SourceState]
    return SourceSummary(
        verification=verify_source(path, records),
        record_count=len(records),
        unique_snapshot_digests=len(digests),
        section_states={
            section: {state: counter[state] for state in ordered if counter[state]}
            for section, counter in states.items()
        },
        unknown_sections=dict(unknown),
        decode_issues=dict(issues),
    )
