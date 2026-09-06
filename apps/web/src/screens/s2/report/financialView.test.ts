import { describe, expect, it } from 'vitest';
import type { FinancialPeriod } from '../../../api/reportContracts';
import { zeroFact, missingFact, financeSection } from '../../../test/reportFixtures';
import { amountTone, chartValue, chartUnit, historyPoints, metricFact } from './financialView';
import { fragmentRows, recordRows } from '../liveReportView';

describe('Числа и подписи финансовой визуализации', () => {
  it.each([['24.63', 'positive'], ['-28568000', 'negative'], ['0.00', 'neutral'], ['-0.00', 'neutral']])('определяет знак %s без округления', (value, tone) => {
    expect(amountTone({ ...zeroFact, value })).toBe(tone);
  });
  it('не принимает отсутствие, пустоту, ошибку или неподтверждённое значение за ноль', () => {
    for (const availability of ['missing', 'present_empty', 'invalid', 'restricted'] as const) {
      const fact = { ...zeroFact, availability, value: '1200' };
      expect(chartValue(fact)).toBeNull();
      expect(amountTone(fact)).toBe('neutral');
    }
    expect(chartValue({ ...zeroFact, evidence_refs: [] })).toBeNull();
    expect(chartValue({ ...zeroFact, value: '' })).toBeNull();
    expect(chartValue(zeroFact)).toBe(0);
    expect(chartValue({ ...zeroFact, value: '9007199254740993.25' })).toBeNull();
  });
  it('упорядочивает годы, разрывает линию на пропусках и сохраняет точный факт', () => {
    const period = financeSection.records[0] as FinancialPeriod;
    const points = historyPoints([
      { ...period, year: 2025 },
      { ...period, year: 2023, proceeds: { ...zeroFact, value: '60746000.25' } },
    ], 'proceeds');
    expect(points.map((point) => [point.label, point.value])).toEqual([
      ['2023', 60746000.25], ['2024', null], ['2025', 0],
    ]);
    expect(points[0]?.fact?.value).toBe('60746000.25');
  });
  it('не объединяет валюты или масштабы и не подставляет старую прибыль вместо отсутствующей новой', () => {
    const point = { label: '2025', value: 1, fact: zeroFact };
    expect(chartUnit([point, { ...point, fact: { ...zeroFact, currency: 'USD' } }])).toBeNull();
    expect(chartUnit([point, { ...point, fact: { ...zeroFact, unit: 'тыс.' } }])).toBeNull();
    expect(metricFact([{ ...zeroFact, key: 'financials.2024.profit', period: 2024 }, missingFact], 'profit')).toBe(missingFact);
  });
  it('форматирует даты записей и исходных фрагментов, а не только FactValue', () => {
    const result = recordRows({ kind: 'proceeding', id: '1', number: null, started_at: '2026-09-06', amount: zeroFact, active: missingFact, evidence_refs: ['ref'] });
    expect(result.rows[0]?.value).toBe('6 сентября 2026 г.');
    expect(fragmentRows({ $date: '2026-09-06' }, 'Дата')[0]?.value).toBe('6 сентября 2026 г.');
  });
});
