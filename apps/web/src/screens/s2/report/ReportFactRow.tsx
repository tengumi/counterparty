import { useId, useState } from 'react';
import type { DiscussionContext, SectionName } from '../../../api/reportContracts';
import type { DisplayRow } from '../liveReportView';
import { reportHelp } from './helpContent';
import { ReportHelpButton, ReportHelpText } from './ReportHelp';
import styles from './Report.module.css';

export function ReportFactRow({ row, section, companyName, onEvidence, onDiscuss }: {
  row: DisplayRow;
  section?: SectionName;
  companyName: string;
  onEvidence: (ref: string) => void;
  onDiscuss: (context: DiscussionContext) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const ref = row.refs[0];
  const help = reportHelp(row.label, section);
  return <div className={styles.fact}>
    <div className={styles.factRow}>
      {ref ? <button className={styles.factLabel} type="button"
        aria-label={`Основание: ${row.label}`} onClick={() => onEvidence(ref)}>
        {row.label}
      </button> : <span className={styles.factLabel}>{row.label}</span>}
      <span className={styles.factValue}>
        <span className={row.fact && row.fact.availability !== 'available' ? styles.missing : undefined}>
          {row.value}
        </span>
        {row.period != null ? <span className={styles.factPeriod}>{row.period} год</span> : null}
      </span>
      <span className={styles.tableActions}>
        {help ? <ReportHelpButton label={row.label} id={id} expanded={expanded}
          onClick={() => setExpanded(!expanded)} /> : null}
        {ref ? <button className={styles.textAction} type="button"
          aria-label={`Обсудить: ${row.label}`} onClick={() => onDiscuss({
            kind: 'evidence', evidence_ref: ref,
            label: `${row.label} · ${companyName}${row.period != null ? ` · ${row.period}` : ''}`,
          })}>Обсудить</button> : null}
      </span>
    </div>
    {expanded && help ? <ReportHelpText id={id} text={help} evidenceRef={ref} onEvidence={onEvidence} /> : null}
  </div>;
}
