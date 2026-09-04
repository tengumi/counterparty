import type { Card, ChatResponse, Evidence } from "../types";

export const financialMetrics = [
  { key: "proceeds", label: "Выручка" },
  { key: "profit", label: "Прибыль / убыток" },
  { key: "assets_total", label: "Активы" },
  { key: "equity", label: "Капитал и резервы" },
] as const;
export type FinancialMetric = (typeof financialMetrics)[number]["key"];
export interface AnnualPoint {
  year: number;
  values: Record<FinancialMetric, string | null>;
  evidence: Evidence[];
}
const decimalPattern = /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/;
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

// Берём только проверенные годовые факты своей карточки, а не текст ответа LLM.
export function annualPoints(card: Card): AnnualPoint[] {
  // Backend проверяет календарный год в исходном часовом поясе отчёта.
  const reportYear =
    /^\d{4}-/.test(card.report_at) &&
    Number.isFinite(Date.parse(card.report_at))
      ? Number(card.report_at.slice(0, 4))
      : NaN;
  const result: AnnualPoint[] = [];
  for (const finding of card.findings) {
    if (finding.code !== "financial_period") continue;
    const evidence = finding.evidence_ids.map((id) =>
      card.evidence.find((item) => item.evidence_id === id),
    );
    if (!evidence.length || evidence.some((item) => !item)) continue;
    const period = evidence.find(
      (item) => item?.canonical_path === "analysis.financial_period",
    );
    const value = period?.value;
    if (
      !record(value) ||
      typeof value.year !== "number" ||
      !Number.isInteger(value.year) ||
      value.year < 1900 ||
      value.year > 2200 ||
      !Number.isFinite(reportYear) ||
      value.year >= reportYear ||
      finding.period !== value.year
    )
      continue;
    if (
      financialMetrics.some(
        ({ key }) =>
          value[key] !== null &&
          (typeof value[key] !== "string" || !decimalPattern.test(value[key])),
      )
    )
      continue;
    result.push({
      year: value.year,
      values: Object.fromEntries(
        financialMetrics.map(({ key }) => [key, value[key]]),
      ) as AnnualPoint["values"],
      evidence: evidence as Evidence[],
    });
  }
  // Не выбирать произвольно один из противоречащих друг другу периодов.
  if (new Set(result.map((point) => point.year)).size !== result.length)
    return [];
  return result.sort((a, b) => a.year - b.year);
}

export function exactNumber(value: string | null): string {
  if (value === null) return "Нет данных";
  if (/[eE]/.test(value)) return value.replace(".", ",");
  const [whole, fraction] = value.split(".");
  return (
    whole.replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f") +
    (fraction ? `,${fraction}` : "")
  );
}

// Number используется исключительно для координат SVG. Подписи и источники
// всегда сохраняют исходную Decimal-строку; расчётов сумм и рейтинга здесь нет.
export function chartCoordinate(value: string | null): number | null {
  if (value === null || !decimalPattern.test(value)) return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  if (number === 0 && !/^-?0+(?:\.0+)?(?:[eE][+-]?\d+)?$/.test(value))
    return null;
  return number;
}

export function financialChartPoints(
  periods: AnnualPoint[],
  metric: FinancialMetric,
) {
  if (!periods.length) return [];
  const byYear = new Map(periods.map((point) => [point.year, point]));
  const first = Math.min(...byYear.keys());
  const last = Math.max(...byYear.keys());
  // Пропущенные годы нужны только для разрыва линии: это не новые факты
  // и не основания для открытия источника. Исходные периоды не меняются.
  return Array.from({ length: last - first + 1 }, (_, index) => {
    const year = first + index;
    const exact = byYear.get(year)?.values[metric] ?? null;
    return { year, exact, plot: chartCoordinate(exact) };
  });
}

export const bankSegments = [
  { key: "GREEN", label: "Надёжный", color: "#348363" },
  { key: "YELLOW", label: "Требует внимания", color: "#bf840c" },
  { key: "RED", label: "В зоне риска", color: "#d34850" },
  { key: "GREY", label: "Нет данных для оценки", color: "#868d9a" },
  { key: "MISSING", label: "Сигнал не передан", color: "#c3c9d2" },
  { key: "UNKNOWN", label: "Сигнал не распознан", color: "#74758c" },
] as const;

export function bankDistribution(cards: Card[]) {
  const classified = cards.map((card) => {
    const raw = card.bank_risk.raw_level;
    const key =
      raw === null
        ? "MISSING"
        : ["GREEN", "YELLOW", "RED", "GREY"].includes(raw)
          ? raw
          : "UNKNOWN";
    return { card, key };
  });
  // Для проверки количества, включая ноль, нужны основания всей группы.
  const evidence = classified.flatMap(({ card, key }) =>
    card.evidence
      .filter((item) => item.evidence_id === card.bank_evidence_id)
      .map((item) => ({
        ...item,
        company_name: `${card.short_name || card.name} · ${bankSegments.find((item) => item.key === key)!.label}`,
      })),
  );
  return bankSegments.map((segment) => {
    return {
      ...segment,
      count: classified.filter((item) => item.key === segment.key).length,
      evidence,
      verified: evidence.length === cards.length,
    };
  });
}

export function financialCoverage(data: ChatResponse) {
  const comparison = data.comparison;
  if (!comparison || comparison.financial_year === null) return [];
  return financialMetrics
    .map(({ key, label }) => {
      const row = comparison.rows.find(
        (item) => item.key === `financial_${key}`,
      );
      if (!row || row.cells.length !== comparison.snapshot_ids.length)
        return null;
      const evidence: Evidence[] = [];
      let available = 0;
      for (const [index, id] of comparison.snapshot_ids.entries()) {
        const card = data.cards.find((item) => item.snapshot_id === id);
        const cell = row.cells[index];
        if (!card || cell.snapshot_id !== id || !cell.evidence_ids.length)
          return null;
        const sources = cell.evidence_ids.map((eid) =>
          card.evidence.find((item) => item.evidence_id === eid),
        );
        if (sources.some((item) => !item)) return null;
        evidence.push(
          ...(sources as Evidence[]).map((item) => ({
            ...item,
            company_name: card.short_name || card.name,
          })),
        );
        if (
          typeof cell.value === "string" &&
          decimalPattern.test(cell.value) &&
          ["confirmed", "partial"].includes(cell.data_status)
        )
          available += 1;
      }
      return {
        key,
        label,
        available,
        missing: row.cells.length - available,
        total: row.cells.length,
        evidence,
      };
    })
    .filter((item) => item !== null);
}
