"""Deterministic summaries and calculations over reported financial periods.

The source carries one object per reporting period, and the periods are not
uniform: a year may be absent, the series may have holes, a field may be
missing, empty, malformed or a real zero. None of that is normalised away
here. A calculation whose input is unknown stays unknown, so a gap in the
reporting is visible as a gap rather than as a confident zero.

Three amounts are kept strictly apart, because the source names invite
confusion:

* ``balance_total_liabilities_side`` — ``liabilities.totalLiabilities``, the
  balance-sheet total of the liabilities side, **not** an amount of debt;
* ``equity`` — ``liabilities.capitals``, capital as reported;
* ``share_capital`` — ``foundersInfo.shareCapital``, the charter capital,
  which belongs to a different section entirely.

No aggregate score, rating or ranking is produced anywhere in this module.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from counterparty_contracts import Availability

from .derivation import DEFAULT_RULE_VERSION, attach_derivation
from .evidence import EvidenceLedger
from .facts import FactSlot
from .values import ratio, subtract_decimals, sum_decimals

__all__ = [
    "NEGATIVE_EQUITY_NOTE",
    "BalanceConsistency",
    "CapitalView",
    "EquityPosition",
    "FinancialHistory",
    "FinancialMetric",
    "FinancialPeriod",
    "FinancialSummary",
    "MetricChange",
    "PeriodCalculation",
    "PeriodCoverage",
    "calculate_period",
    "compare_metric",
    "metric_of",
    "summarize_financials",
]

NEGATIVE_EQUITY_NOTE = (
    "negative reported capital is a balance-sheet observation, not proof of "
    "insolvency or bankruptcy"
)
"""Wording rule: a negative equity never becomes a proven bankruptcy claim."""

_DEFAULT_CHANGE_METRICS: tuple["FinancialMetric", ...] = ()


def _absent(label: str) -> FactSlot[Decimal]:
    """Build the default slot for a field the caller never supplied."""
    return FactSlot[Decimal].missing(f"{label} was not supplied to the domain layer")


class FinancialMetric(StrEnum):
    """Reported financial fields addressable by a stable name.

    The names match the storage columns of ``financial_statements`` so a
    calculation can be traced to one documented source path.
    """

    PROCEEDS = "proceeds"
    PROFIT = "profit"
    TOTAL_ASSETS = "total_assets"
    CURRENT_ASSETS = "current_assets"
    STOCKS = "stocks"
    RECEIVABLES = "receivables"
    CASH = "cash"
    NONCURRENT_ASSETS = "noncurrent_assets"
    FIXED_ASSETS = "fixed_assets"
    BALANCE_TOTAL_LIABILITIES_SIDE = "balance_total_liabilities_side"
    EQUITY = "equity"
    LONG_TERM_TOTAL = "long_term_total"
    LONG_TERM_OTHER = "long_term_other"
    SHORT_TERM_TOTAL = "short_term_total"
    SHORT_TERM_BORROWED = "short_term_borrowed"
    ACCOUNTS_PAYABLE = "accounts_payable"


class EquityPosition(StrEnum):
    """Sign of the reported capital, or the absence of a usable value."""

    POSITIVE = "positive"
    ZERO = "zero"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class BalanceConsistency(StrEnum):
    """Whether the two sides of the reported balance sheet agree."""

    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FinancialPeriod:
    """One reporting period exactly as the source described it.

    Attributes:
        year: The fiscal year of the period; unknown when the source omitted
            or malformed ``common.year``. The snapshot date is a different
            thing and never substitutes for it.
        ordinal: Position of the period inside the source array, which keeps
            the origin recoverable when two records claim the same year.
        evidence_refs: Evidence ids covering the period as a whole.
    """

    year: FactSlot[int]
    ordinal: int | None = None
    proceeds: FactSlot[Decimal] = field(default_factory=lambda: _absent("proceeds"))
    profit: FactSlot[Decimal] = field(default_factory=lambda: _absent("profit"))
    total_assets: FactSlot[Decimal] = field(default_factory=lambda: _absent("total_assets"))
    current_assets: FactSlot[Decimal] = field(default_factory=lambda: _absent("current_assets"))
    stocks: FactSlot[Decimal] = field(default_factory=lambda: _absent("stocks"))
    receivables: FactSlot[Decimal] = field(default_factory=lambda: _absent("receivables"))
    cash: FactSlot[Decimal] = field(default_factory=lambda: _absent("cash"))
    noncurrent_assets: FactSlot[Decimal] = field(
        default_factory=lambda: _absent("noncurrent_assets")
    )
    fixed_assets: FactSlot[Decimal] = field(default_factory=lambda: _absent("fixed_assets"))
    balance_total_liabilities_side: FactSlot[Decimal] = field(
        default_factory=lambda: _absent("balance_total_liabilities_side")
    )
    equity: FactSlot[Decimal] = field(default_factory=lambda: _absent("equity"))
    long_term_total: FactSlot[Decimal] = field(default_factory=lambda: _absent("long_term_total"))
    long_term_other: FactSlot[Decimal] = field(default_factory=lambda: _absent("long_term_other"))
    short_term_total: FactSlot[Decimal] = field(default_factory=lambda: _absent("short_term_total"))
    short_term_borrowed: FactSlot[Decimal] = field(
        default_factory=lambda: _absent("short_term_borrowed")
    )
    accounts_payable: FactSlot[Decimal] = field(default_factory=lambda: _absent("accounts_payable"))
    evidence_refs: tuple[str, ...] = ()

    @property
    def has_year(self) -> bool:
        """Whether the period can be placed on the reporting timeline."""
        return self.year.is_available

    def metric(self, metric: FinancialMetric) -> FactSlot[Decimal]:
        """Return one reported amount by its stable metric name."""
        return metric_of(self, metric)


def metric_of(period: FinancialPeriod, metric: FinancialMetric) -> FactSlot[Decimal]:
    """Return the slot a metric name addresses on a period."""
    value: FactSlot[Decimal] = getattr(period, metric.value)
    return value


@dataclass(frozen=True, slots=True)
class PeriodCalculation:
    """Values computed from one period, each grounded in its own inputs.

    Attributes:
        reported_obligations: ``long_term_total + short_term_total``. This is
            the reported debt-like total; it is deliberately not
            ``balance_total_liabilities_side``, which also carries capital.
        balance_gap: Assets minus the liabilities-side total. Zero means the
            two sides agree; a non-zero gap is reported, never silenced.
        working_capital: Current assets minus short-term liabilities.
        profit_margin: Profit divided by proceeds, unknown when proceeds are
            zero because the quotient does not exist.
        equity_position: Sign of the reported capital.
        notes: Interpretation rules a caller must repeat rather than restate.
    """

    year: FactSlot[int]
    reported_obligations: FactSlot[Decimal]
    balance_gap: FactSlot[Decimal]
    balance_consistency: BalanceConsistency
    working_capital: FactSlot[Decimal]
    profit_margin: FactSlot[Decimal]
    equity_position: EquityPosition
    notes: tuple[str, ...] = ()


def _equity_position(equity: FactSlot[Decimal]) -> EquityPosition:
    """Classify the sign of reported capital without inventing a value."""
    if not equity.is_available:
        return EquityPosition.UNKNOWN
    amount = equity.unwrap()
    if amount > 0:
        return EquityPosition.POSITIVE
    if amount < 0:
        return EquityPosition.NEGATIVE
    return EquityPosition.ZERO


def _balance_consistency(gap: FactSlot[Decimal]) -> BalanceConsistency:
    """Turn the balance gap into a three-valued verdict."""
    if not gap.is_available:
        return BalanceConsistency.UNKNOWN
    return BalanceConsistency.CONSISTENT if gap.unwrap() == 0 else BalanceConsistency.INCONSISTENT


def calculate_period(
    period: FinancialPeriod,
    *,
    ledger: EvidenceLedger | None = None,
    ref_prefix: str = "calc",
    rule_version: str = DEFAULT_RULE_VERSION,
) -> PeriodCalculation:
    """Compute the derived values of a single reporting period.

    Args:
        period: The reported period.
        ledger: When supplied, every computed value is registered as a derived
            reference over its inputs, so it can be expanded to the source.
        ref_prefix: Namespace for the generated derived reference ids.
        rule_version: Version recorded on the derived references.

    Returns:
        The computed values, each keeping the availability of its inputs.
    """
    obligations = sum_decimals(
        (period.long_term_total, period.short_term_total), label="reported obligations"
    )
    gap = subtract_decimals(
        period.total_assets,
        period.balance_total_liabilities_side,
        label="balance gap",
    )
    working_capital = subtract_decimals(
        period.current_assets, period.short_term_total, label="working capital"
    )
    margin = ratio(period.profit, period.proceeds, label="profit margin")
    position = _equity_position(period.equity)

    notes: list[str] = []
    if position is EquityPosition.NEGATIVE:
        notes.append(NEGATIVE_EQUITY_NOTE)
    if _balance_consistency(gap) is BalanceConsistency.INCONSISTENT:
        notes.append("reported assets and liabilities-side total do not match")

    if ledger is not None:
        year_key = period.year.value if period.year.is_available else "unknown-year"
        scope = f"{ref_prefix}:{year_key}"
        obligations = attach_derivation(
            obligations,
            ledger=ledger,
            ref_id=f"{scope}:reported_obligations",
            rule_version=rule_version,
            period=period.year.value,
        )
        gap = attach_derivation(
            gap,
            ledger=ledger,
            ref_id=f"{scope}:balance_gap",
            rule_version=rule_version,
            period=period.year.value,
        )
        working_capital = attach_derivation(
            working_capital,
            ledger=ledger,
            ref_id=f"{scope}:working_capital",
            rule_version=rule_version,
            period=period.year.value,
        )
        margin = attach_derivation(
            margin,
            ledger=ledger,
            ref_id=f"{scope}:profit_margin",
            rule_version=rule_version,
            period=period.year.value,
        )

    return PeriodCalculation(
        year=period.year,
        reported_obligations=obligations,
        balance_gap=gap,
        balance_consistency=_balance_consistency(gap),
        working_capital=working_capital,
        profit_margin=margin,
        equity_position=position,
        notes=tuple(notes),
    )


@dataclass(frozen=True, slots=True)
class PeriodCoverage:
    """What the reporting series actually covers.

    Attributes:
        years: Distinct fiscal years present, ascending.
        gap_years: Years between the first and the last that carry no report.
            A gap is never filled with the previous year's figures.
        duplicate_years: Years described by more than one source record.
        undated_count: Records whose fiscal year could not be established.
    """

    years: tuple[int, ...] = ()
    first_year: int | None = None
    last_year: int | None = None
    gap_years: tuple[int, ...] = ()
    duplicate_years: tuple[int, ...] = ()
    undated_count: int = 0

    @property
    def is_continuous(self) -> bool:
        """Whether the covered span has no missing year."""
        return not self.gap_years


@dataclass(frozen=True, slots=True)
class FinancialHistory:
    """All reported periods of one company, ordered by fiscal year.

    Attributes:
        periods: Dated periods sorted by year ascending, then by source
            ordinal, so the ordering is stable and reproducible.
        undated: Records whose year is unknown. They are kept, because a
            record that cannot be placed is not a record that does not exist.
        availability: Availability of the whole financial section.
        confirms_absence: Only for ``present_empty``: whether the empty
            section was confirmed to mean "no reporting", as opposed to an
            unexplained empty array.
    """

    periods: tuple[FinancialPeriod, ...] = ()
    undated: tuple[FinancialPeriod, ...] = ()
    availability: Availability = Availability.AVAILABLE
    confirms_absence: bool = False
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_periods(
        cls,
        periods: Sequence[FinancialPeriod],
        *,
        availability: Availability = Availability.AVAILABLE,
        confirms_absence: bool = False,
        warnings: Sequence[str] = (),
    ) -> "FinancialHistory":
        """Build a history, separating dated periods from undatable records."""
        dated = [period for period in periods if period.has_year]
        undated = tuple(period for period in periods if not period.has_year)
        dated.sort(key=lambda period: (period.year.unwrap(), period.ordinal or 0))
        collected = list(warnings)
        if undated:
            collected.append(
                f"{len(undated)} financial record(s) carry no usable fiscal year "
                "and were left out of the timeline"
            )
        years = [period.year.unwrap() for period in dated]
        duplicates = sorted({year for year in years if years.count(year) > 1})
        if duplicates:
            collected.append(
                "more than one financial record describes year(s) "
                + ", ".join(str(year) for year in duplicates)
            )
        resolved = availability
        if not periods and availability is Availability.AVAILABLE:
            resolved = Availability.PRESENT_EMPTY
        return cls(
            periods=tuple(dated),
            undated=undated,
            availability=resolved,
            confirms_absence=confirms_absence,
            warnings=tuple(collected),
        )

    def __len__(self) -> int:
        """Number of dated periods on the timeline."""
        return len(self.periods)

    def coverage(self) -> PeriodCoverage:
        """Describe the span, the holes and the ambiguities of the series."""
        if not self.periods:
            return PeriodCoverage(undated_count=len(self.undated))
        years = [period.year.unwrap() for period in self.periods]
        distinct = sorted(set(years))
        duplicates = sorted({year for year in years if years.count(year) > 1})
        gaps = tuple(
            year for year in range(distinct[0], distinct[-1] + 1) if year not in set(distinct)
        )
        return PeriodCoverage(
            years=tuple(distinct),
            first_year=distinct[0],
            last_year=distinct[-1],
            gap_years=gaps,
            duplicate_years=tuple(duplicates),
            undated_count=len(self.undated),
        )

    def _absent_period(self, reason: str) -> FactSlot[FinancialPeriod]:
        """Build the non-value that matches the section availability."""
        if self.availability is Availability.PRESENT_EMPTY:
            return FactSlot[FinancialPeriod].present_empty(
                reason, confirms_absence=self.confirms_absence
            )
        if self.availability is Availability.INVALID:
            return FactSlot[FinancialPeriod].invalid(reason)
        if self.availability is Availability.RESTRICTED:
            return FactSlot[FinancialPeriod].restricted(reason)
        return FactSlot[FinancialPeriod].missing(reason)

    def latest(self) -> FactSlot[FinancialPeriod]:
        """Return the period with the highest fiscal year.

        The latest period is chosen by year, never by array position: the
        source does not guarantee that index 0 is the most recent report.
        """
        if not self.periods:
            return self._absent_period("no dated financial period is available")
        return FactSlot[FinancialPeriod].available(self.periods[-1])

    def for_year(self, year: int) -> FactSlot[FinancialPeriod]:
        """Return the period of one fiscal year, without borrowing another.

        A year with no report stays unavailable; the previous year's figures
        are never carried forward into it.
        """
        matches = [period for period in self.periods if period.year.unwrap() == year]
        if not matches:
            return self._absent_period(f"no financial report covers {year}")
        slot = FactSlot[FinancialPeriod].available(matches[0])
        if len(matches) > 1:
            return slot.with_warning(
                f"{len(matches)} records describe {year}; the first by source order was used"
            )
        return slot

    def preceding(self, year: int) -> FactSlot[FinancialPeriod]:
        """Return the latest period strictly before ``year``."""
        earlier = [period for period in self.periods if period.year.unwrap() < year]
        if not earlier:
            return self._absent_period(f"no financial report precedes {year}")
        return FactSlot[FinancialPeriod].available(earlier[-1])


@dataclass(frozen=True, slots=True)
class MetricChange:
    """Movement of one metric between two reported periods.

    Attributes:
        years_skipped: Number of unreported years between the two periods. A
            change measured across a hole in the reporting is still reported,
            but it is labelled as such and never presented as year-on-year.
    """

    metric: FinancialMetric
    from_year: int | None
    to_year: int | None
    previous: FactSlot[Decimal]
    current: FactSlot[Decimal]
    absolute: FactSlot[Decimal]
    relative: FactSlot[Decimal]
    years_skipped: int = 0
    warnings: tuple[str, ...] = ()

    @property
    def is_year_on_year(self) -> bool:
        """Whether the two periods are consecutive reporting years."""
        return self.years_skipped == 0 and self.from_year is not None


def compare_metric(
    history: FinancialHistory,
    metric: FinancialMetric,
    *,
    ledger: EvidenceLedger | None = None,
    ref_prefix: str = "calc",
    rule_version: str = DEFAULT_RULE_VERSION,
) -> MetricChange:
    """Compare one metric in the latest period against the preceding one.

    Both the absolute difference and the relative change are unknown whenever
    either side is unknown, and the relative change is also unknown when the
    earlier value is zero, because the quotient does not exist.
    """
    latest = history.latest()
    if not latest.is_available:
        absent = FactSlot[Decimal].missing("no dated financial period is available")
        return MetricChange(
            metric=metric,
            from_year=None,
            to_year=None,
            previous=absent,
            current=absent,
            absolute=absent,
            relative=absent,
            warnings=(latest.reason,) if latest.reason else (),
        )
    current_period = latest.unwrap()
    to_year = current_period.year.unwrap()
    current = metric_of(current_period, metric)
    previous_slot = history.preceding(to_year)
    if not previous_slot.is_available:
        unknown = FactSlot[Decimal].missing(f"no financial report precedes {to_year}")
        return MetricChange(
            metric=metric,
            from_year=None,
            to_year=to_year,
            previous=unknown,
            current=current,
            absolute=unknown,
            relative=unknown,
            warnings=(f"{to_year} has no comparable earlier period",),
        )
    previous_period = previous_slot.unwrap()
    from_year = previous_period.year.unwrap()
    previous = metric_of(previous_period, metric)
    absolute = subtract_decimals(current, previous, label=f"{metric.value} change")
    relative = ratio(absolute, previous, label=f"{metric.value} relative change")
    skipped = to_year - from_year - 1
    warnings: list[str] = []
    if skipped > 0:
        warnings.append(
            f"{skipped} unreported year(s) lie between {from_year} and {to_year}; "
            "the change is not year-on-year"
        )
    if ledger is not None:
        scope = f"{ref_prefix}:{from_year}-{to_year}:{metric.value}"
        absolute = attach_derivation(
            absolute,
            ledger=ledger,
            ref_id=f"{scope}:absolute",
            rule_version=rule_version,
            period=to_year,
        )
        relative = attach_derivation(
            relative,
            ledger=ledger,
            ref_id=f"{scope}:relative",
            rule_version=rule_version,
            period=to_year,
        )
    return MetricChange(
        metric=metric,
        from_year=from_year,
        to_year=to_year,
        previous=previous,
        current=current,
        absolute=absolute,
        relative=relative,
        years_skipped=skipped,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True, slots=True)
class CapitalView:
    """The three capital-shaped amounts, kept apart on purpose.

    ``balance_total_liabilities_side`` is the total of the liabilities side of
    the balance sheet and includes capital; it is not an amount owed.
    ``reported_equity`` is capital per the financial statement, and
    ``share_capital`` is the charter capital declared in the founders section.
    They are never added together and never substituted for one another.
    """

    year: int | None = None
    share_capital: FactSlot[Decimal] = field(default_factory=lambda: _absent("share_capital"))
    reported_equity: FactSlot[Decimal] = field(default_factory=lambda: _absent("equity"))
    balance_total_liabilities_side: FactSlot[Decimal] = field(
        default_factory=lambda: _absent("balance_total_liabilities_side")
    )

    @property
    def equity_position(self) -> EquityPosition:
        """Sign of the reported capital, or unknown."""
        return _equity_position(self.reported_equity)

    @property
    def notes(self) -> tuple[str, ...]:
        """Interpretation notes a caller must carry alongside the numbers."""
        if self.equity_position is EquityPosition.NEGATIVE:
            return (NEGATIVE_EQUITY_NOTE,)
        return ()

    def equity_over_share_capital(self) -> FactSlot[Decimal]:
        """Difference between reported capital and charter capital.

        This is a comparison of two distinct amounts, not a total: the two are
        never summed, and the result carries no verdict of its own.
        """
        return subtract_decimals(
            self.reported_equity,
            self.share_capital,
            label="reported capital over charter capital",
        )


@dataclass(frozen=True, slots=True)
class FinancialSummary:
    """Deterministic summary of a company's reported finances.

    It reports what the periods say and what they fail to say. There is no
    combined score and no ranking: a caller reads the individual values and
    their availability.
    """

    availability: Availability
    confirms_absence: bool
    coverage: PeriodCoverage
    latest_year: FactSlot[int]
    latest_period: FactSlot[FinancialPeriod]
    latest_calculation: PeriodCalculation | None
    capital: CapitalView
    changes: tuple[MetricChange, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def has_reporting(self) -> bool:
        """Whether at least one datable reporting period exists."""
        return self.coverage.last_year is not None


def summarize_financials(
    history: FinancialHistory,
    *,
    share_capital: FactSlot[Decimal] | None = None,
    change_metrics: Sequence[FinancialMetric] = _DEFAULT_CHANGE_METRICS,
    ledger: EvidenceLedger | None = None,
    ref_prefix: str = "calc",
    rule_version: str = DEFAULT_RULE_VERSION,
) -> FinancialSummary:
    """Summarise a financial history without collapsing its gaps.

    Args:
        history: The reported periods.
        share_capital: Charter capital from the founders section, which lives
            outside the financial statements and is only carried alongside.
        change_metrics: Metrics to compare against the preceding period.
        ledger: When supplied, computed values are registered as derived
            references so each one expands back to its inputs.
        ref_prefix: Namespace for generated derived reference ids.
        rule_version: Version recorded on the derived references.

    Returns:
        A summary in which every unknown input stays visibly unknown.
    """
    coverage = history.coverage()
    latest = history.latest()
    warnings = list(history.warnings)
    if coverage.gap_years:
        warnings.append(
            "no report covers "
            + ", ".join(str(year) for year in coverage.gap_years)
            + "; earlier figures were not carried forward"
        )

    if not latest.is_available:
        return FinancialSummary(
            availability=history.availability,
            confirms_absence=history.confirms_absence,
            coverage=coverage,
            latest_year=FactSlot[int].missing("no dated financial period is available"),
            latest_period=latest,
            latest_calculation=None,
            capital=CapitalView(
                share_capital=share_capital
                if share_capital is not None
                else _absent("share_capital")
            ),
            warnings=tuple(warnings),
        )

    period = latest.unwrap()
    calculation = calculate_period(
        period, ledger=ledger, ref_prefix=ref_prefix, rule_version=rule_version
    )
    capital = CapitalView(
        year=period.year.unwrap(),
        share_capital=share_capital if share_capital is not None else _absent("share_capital"),
        reported_equity=period.equity,
        balance_total_liabilities_side=period.balance_total_liabilities_side,
    )
    changes = tuple(
        compare_metric(
            history,
            metric,
            ledger=ledger,
            ref_prefix=ref_prefix,
            rule_version=rule_version,
        )
        for metric in change_metrics
    )
    for change in changes:
        warnings.extend(change.warnings)
    return FinancialSummary(
        availability=history.availability,
        confirms_absence=history.confirms_absence,
        coverage=coverage,
        latest_year=period.year,
        latest_period=latest,
        latest_calculation=calculation,
        capital=capital,
        changes=changes,
        warnings=tuple(dict.fromkeys(warnings)),
    )
