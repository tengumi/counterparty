import { QuestionCircleLineMIcon } from '@alfalab/icons-glyph/QuestionCircleLineMIcon';
import styles from './Report.module.css';

export function ReportHelpButton({ label, id, expanded, onClick }: {
  label: string;
  id: string;
  expanded: boolean;
  onClick: () => void;
}) {
  return <button type="button" className={styles.helpButton} title="Что это значит"
    aria-label={`Что это значит: ${label}`} aria-expanded={expanded} aria-controls={id}
    onClick={onClick}>
    <QuestionCircleLineMIcon width={18} height={18} aria-hidden="true" />
  </button>;
}

export function ReportHelpText({ id, text, evidenceRef, onEvidence }: {
  id: string;
  text: string;
  evidenceRef?: string;
  onEvidence: (ref: string) => void;
}) {
  return <div id={id} className={styles.helpText}>
    <span>{text}</span>
    {evidenceRef ? <button type="button" className={styles.textAction}
      onClick={() => onEvidence(evidenceRef)}>Основание</button> : null}
  </div>;
}
