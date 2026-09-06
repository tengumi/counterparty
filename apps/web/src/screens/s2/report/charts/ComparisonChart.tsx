import { useState } from 'react';
import type { ProjectComparison } from '../../../../api/reportContracts';
import { chartValue, metricFact } from '../financialView';
import type { FinancialMetric } from '../financialView';
import { FinancialChart, MetricPicker } from './FinancialChart';
import styles from './FinancialChart.module.css';

export default function ComparisonChart({ comparison, onEvidence }: {
  comparison: ProjectComparison;
  onEvidence: (ref: string) => void;
}) {
  const [metric, setMetric] = useState<FinancialMetric>('proceeds');
  if (!comparison.criteria.includes('financials')) return null;
  const points = comparison.rows.map((row, index) => {
    const fact = metricFact(row.cells, metric);
    return { label: `${index + 1}. ${row.company.short_name}`, value: chartValue(fact), fact };
  });
  const known = points.filter((point) => point.value !== null);
  const periods = new Set(known.map((point) => point.fact?.period == null ? null : String(point.fact.period)));
  const blocked = periods.size > 1 || periods.has(null)
    ? 'Для графика нужен один и тот же год. Выберите общий или конкретный финансовый период выше и обновите сравнение.' : undefined;
  return <div className={styles.card} role="region" aria-label="Финансы в сравнении">
    <div className={styles.heading}>
      <h4>Финансы в сравнении{known[0]?.fact?.period && !blocked ? ` · ${known[0].fact.period}` : ''}</h4>
      <MetricPicker label="Показатель сравнения на графике" value={metric} onChange={setMetric} />
    </div>
    <FinancialChart points={points} metric={metric} comparison onEvidence={onEvidence} blocked={blocked} />
  </div>;
}
