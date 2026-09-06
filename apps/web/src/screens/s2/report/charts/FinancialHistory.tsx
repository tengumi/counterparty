import { useState } from 'react';
import type { ReportRecord } from '../../../../api/reportContracts';
import { financialMetrics, historyPoints } from '../financialView';
import type { FinancialMetric } from '../financialView';
import { FinancialChart, MetricPicker } from './FinancialChart';
import styles from './FinancialChart.module.css';

export default function FinancialHistory({ records, onEvidence, partial }: {
  records: readonly ReportRecord[];
  onEvidence: (ref: string) => void;
  partial: boolean;
}) {
  const [selection, setMetric] = useState<FinancialMetric | null>(null);
  const metric = selection ?? financialMetrics.find((item) => historyPoints(records, item.key).some((point) => point.value !== null))?.key ?? 'proceeds';
  const points = historyPoints(records, metric);
  if (!points.length) return null;
  return <div className={styles.card} role="region" aria-label="Динамика финансов">
    <div className={styles.heading}>
      <h4>Динамика финансов</h4>
      <MetricPicker label="Показатель динамики" value={metric} onChange={setMetric} />
    </div>
    <FinancialChart points={points} metric={metric} onEvidence={onEvidence} />
    {partial ? <p className={styles.note}>Показаны загруженные периоды. Кнопка «Показать ещё записи» дополнит график.</p> : null}
  </div>;
}
