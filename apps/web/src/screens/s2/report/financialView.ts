import type { FactValue, FinancialPeriod, ReportRecord } from '../../../api/reportContracts';

export const financialMetrics = [
  { key: 'proceeds', label: 'Выручка' },
  { key: 'profit', label: 'Прибыль' },
  { key: 'total_assets', label: 'Активы' },
  { key: 'equity', label: 'Капитал' },
  { key: 'cash', label: 'Денежные средства' },
  { key: 'receivables', label: 'Дебиторская задолженность' },
  { key: 'accounts_payable', label: 'Кредиторская задолженность' },
] as const;
export type FinancialMetric = typeof financialMetrics[number]['key'];
export type AmountTone = 'positive' | 'negative' | 'neutral';
export interface ChartPoint {
  readonly label: string;
  readonly value: number | null;
  readonly fact?: FactValue;
}

function decimal(fact: FactValue | undefined): string | null {
  if (!fact || fact.availability !== 'available' || !fact.evidence_refs.length) return null;
  if (fact.value_type === 'decimal' && typeof fact.value === 'string' && /^-?\d+(\.\d+)?$/.test(fact.value)) return fact.value;
  if (fact.value_type === 'integer' && typeof fact.value === 'number' && Number.isSafeInteger(fact.value)) return String(fact.value);
  return null;
}

/** Цвет — только знак исходного числа, не скоринг. Не округляем Decimal для определения знака. */
export function amountTone(fact: FactValue | undefined): AmountTone {
  const value = decimal(fact);
  if (value === null || !/[1-9]/.test(value)) return 'neutral';
  return value.startsWith('-') ? 'negative' : 'positive';
}

/** Number используется только для геометрии; точная подпись всегда берётся из FactValue. */
export function chartValue(fact: FactValue | undefined): number | null {
  const value = decimal(fact);
  if (value === null) return null;
  const number = Number(value);
  return Number.isFinite(number) && Math.abs(number) <= Number.MAX_SAFE_INTEGER
    && !(number === 0 && /[1-9]/.test(value)) ? number : null;
}

export function metricFact(facts: readonly FactValue[], key: FinancialMetric): FactValue | undefined {
  return facts.filter((fact) => fact.key.split(/[./]/).at(-1) === key)
    .sort((a, b) => Number(b.period) - Number(a.period))[0];
}

export function financialPeriods(records: readonly ReportRecord[]): FinancialPeriod[] {
  return records.filter((record): record is FinancialPeriod => record.kind === 'financial_period')
    .sort((a, b) => a.year - b.year);
}

export function historyPoints(records: readonly ReportRecord[], metric: FinancialMetric): ChartPoint[] {
  const periods = financialPeriods(records).filter((period) => Number.isInteger(period.year) && period.year >= 1900 && period.year <= 2200);
  const first = periods[0];
  const last = periods.at(-1);
  if (!first || !last) return [];
  // Незаполненные годы разрывают линию, вместо выдуманной непрерывной динамики.
  return Array.from({ length: last.year - first.year + 1 }, (_, index) => {
    const year = first.year + index;
    const matches = periods.filter((period) => period.year === year);
    const fact = matches.length === 1 ? matches[0]![metric] : undefined;
    return { label: String(year), value: chartValue(fact), fact };
  });
}

/** Разные валюты/масштабы не должны делить одну ось. Никакой конвертации на клиенте. */
export function chartUnit(points: readonly ChartPoint[]): string | null {
  const facts = points.filter((point) => point.value !== null).map((point) => point.fact!);
  if (!facts.length) return 'Значение';
  if (new Set(facts.map((fact) => JSON.stringify([fact.currency ?? null, fact.unit ?? null]))).size > 1) return null;
  const fact = facts[0]!;
  const currency = fact.currency === 'RUB' ? '₽' : fact.currency;
  return [fact.unit, currency].filter(Boolean).join(' · ') || 'Единицы источника';
}

export function axisAmount(value: number): string {
  const scale = Math.abs(value) >= 1e9 ? 1e9 : Math.abs(value) >= 1e6 ? 1e6 : Math.abs(value) >= 1e3 ? 1e3 : 1;
  const suffix = scale === 1e9 ? ' млрд' : scale === 1e6 ? ' млн' : scale === 1e3 ? ' тыс.' : '';
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value / scale)}${suffix}`;
}
