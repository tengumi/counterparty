import { Fragment, useId, useState } from 'react';
import type { DiscussionContext, FinancialPeriod, ReportRecord } from '../../../api/reportContracts';
import { factLabel, factText } from '../liveReportView';
import { reportHelp } from './helpContent';
import { ReportHelpButton, ReportHelpText } from './ReportHelp';
import styles from './Report.module.css';

const fields = ['proceeds', 'total_assets', 'equity', 'accounts_payable', 'profit', 'cash', 'receivables'] as const;

export function FinancialTable({ records, companyName, onEvidence, onDiscuss }: {
  records: readonly ReportRecord[];
  companyName: string;
  onEvidence: (ref: string) => void;
  onDiscuss: (context: DiscussionContext) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const id = useId();
  const periods = records.filter((record): record is FinancialPeriod => record.kind === 'financial_period')
    .sort((a, b) => a.year - b.year);
  if (!periods.length) return null;
  return <div className={styles.financialScroll} role="region" aria-label="Финансовые показатели по годам" tabIndex={0}>
    <table className={styles.financialTable}>
      <thead><tr><th scope="col">Показатель</th>
        {periods.map((period) => <th scope="col" key={period.year}>{period.year}</th>)}
        <th scope="col"><span className={styles.hidden}>Действия</span></th>
      </tr></thead>
      <tbody>{fields.map((key) => {
        const latest = periods.at(-1)![key];
        const label = factLabel(latest);
        const ref = latest.evidence_refs[0];
        const help = reportHelp(label);
        const helpId = `${id}-${key}`;
        const isExpanded = expanded === key;
        return <Fragment key={key}>
          <tr className={styles.financialRow}>
            <th scope="row">{ref ? <button className={styles.factLabel} type="button"
              aria-label={`Основание: ${label}`} onClick={() => onEvidence(ref)}>{label}</button> : label}</th>
            {periods.map((period) => {
              const fact = period[key];
              const evidence = fact.evidence_refs[0];
              return <td key={period.year} className={fact.availability !== 'available' ? styles.missing : undefined}>
                {evidence ? <button className={styles.financialValue} type="button"
                  title={`Основание: ${label} · ${period.year}`}
                  onClick={() => onEvidence(evidence)}>{factText(fact)}</button> : factText(fact)}
              </td>;
            })}
            <td><div className={styles.tableActions}>
              {help ? <ReportHelpButton label={label} id={helpId} expanded={isExpanded}
                onClick={() => setExpanded(isExpanded ? null : key)} /> : null}
              {ref ? <button className={styles.textAction} type="button"
                aria-label={`Обсудить: ${label}`} onClick={() => onDiscuss({
                  kind: 'evidence', evidence_ref: ref,
                  label: `${label} · ${companyName} · ${latest.period}`,
                })}>Обсудить</button> : null}
            </div></td>
          </tr>
          {isExpanded && help ? <tr className={styles.financialHelp}><td colSpan={periods.length + 2}>
            <ReportHelpText id={helpId} text={help} evidenceRef={ref} onEvidence={onEvidence} />
          </td></tr> : null}
        </Fragment>;
      })}</tbody>
    </table>
  </div>;
}
