import { Button } from '@alfalab/core-components/button';
import type { DiscussionContext, FinancialPeriod, ReportRecord } from '../../../api/reportContracts';
import { factLabel, factText } from '../liveReportView';
import styles from './Report.module.css';

const fields = ['proceeds', 'total_assets', 'equity', 'accounts_payable', 'profit', 'cash', 'receivables'] as const;
export function FinancialTable({ records, companyName, onEvidence, onDiscuss }: {
  records: readonly ReportRecord[];
  companyName: string;
  onEvidence: (ref: string) => void;
  onDiscuss: (context: DiscussionContext) => void;
}) {
  const periods = records.filter((record): record is FinancialPeriod => record.kind === 'financial_period')
    .sort((a, b) => a.year - b.year);
  if (!periods.length) return null;
  return <div className={styles.financialScroll}><table className={styles.financialTable}>
    <thead><tr><th>Показатель</th>{periods.map((period) => <th key={period.year}>{period.year}</th>)}<th><span className={styles.hidden}>Действия</span></th></tr></thead>
    <tbody>{fields.map((key) => {
      const latest = periods.at(-1)![key];
      const label = factLabel(latest);
      const ref = latest.evidence_refs[0];
      return <tr key={key}><th scope="row">{label}</th>
        {periods.map((period) => {
          const fact = period[key];
          const evidence = fact.evidence_refs[0];
          return <td key={period.year} className={fact.availability !== 'available' ? styles.missing : undefined}>
            {evidence ? <button title={`Основание: ${label} · ${period.year}`} onClick={() => onEvidence(evidence)}>{factText(fact)}</button> : factText(fact)}
          </td>;
        })}
        <td>{ref ? <div className={styles.tableActions}>
          <Button size={32} view="text" aria-label={`Основание: ${label}`} onClick={() => onEvidence(ref)}><span className={styles.helpIcon} aria-hidden="true">?</span></Button>
          <Button size={32} view="text" onClick={() => onDiscuss({ kind: 'evidence', evidence_ref: ref, label: `${label} · ${companyName} · ${latest.period}` })}>Обсудить</Button>
        </div> : null}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}
