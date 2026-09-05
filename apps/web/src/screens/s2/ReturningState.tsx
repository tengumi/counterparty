/**
 * What a returning user sees at the top of the conversation (07 §5, 06 §5).
 *
 * Coming back to a check should answer three things without scrolling: what was
 * decided, whether anything has changed since, and what to do next. Only the
 * server's own fields are shown — the recorded decision, the freshness of the
 * conclusion and the open question — so the strip never claims progress that
 * was not saved.
 */

import { Button } from '@alfalab/core-components/button';
import type { ApiProject } from '../../api/contracts';
import { decisionDate, decisionStaleMark, outcomeLabels } from './decisionView';
import styles from './conversation/Conversation.module.css';

interface Props {
  readonly project: ApiProject;
  /** Opens «Итог проверки», where a decision is read and recorded. */
  readonly onOpenSummary: () => void;
  /** Puts the cursor in the composer to continue the conversation. */
  readonly onContinue: () => void;
}

export function ReturningState({ project, onOpenSummary, onContinue }: Props) {
  const decision = project.latest_decision ?? null;
  const artifact = project.latest_artifact ?? null;

  if (decision !== null) {
    const stale = decisionStaleMark(decision, project.context_version);
    return (
      <div className={styles.resume} data-testid="returning-state">
        <p className={styles.resumeLabel}>Вы уже записали решение</p>
        <p className={styles.resumeText}>
          {outcomeLabels[decision.outcome]} · {decisionDate(decision.created_at)}
        </p>
        {stale === null ? null : <p className={styles.stale}>{stale.detail}</p>}
        <span className={styles.resumeAction}>
          <Button onClick={onOpenSummary} size={40} view="outlined">
            {stale === null ? 'Открыть итог' : 'Пересмотреть решение'}
          </Button>
        </span>
      </div>
    );
  }

  if (artifact !== null && artifact.freshness !== 'current') {
    return (
      <div className={styles.resume} data-testid="returning-state">
        <p className={styles.resumeLabel}>Вывод помощника устарел</p>
        <p className={styles.resumeText}>
          {artifact.freshness === 'source_removed'
            ? 'Источник вывода удалён из проверки. Прежний вывод остаётся историей, а не текущей оценкой.'
            : 'Сведения проверки изменились после того, как вывод был сделан.'}
        </p>
        <span className={styles.resumeAction}>
          <Button onClick={onOpenSummary} size={40} view="outlined">
            Открыть итог
          </Button>
        </span>
      </div>
    );
  }

  if (project.last_open_question !== null) {
    return (
      <div className={styles.resume} data-testid="returning-state">
        <p className={styles.resumeLabel}>Остановились на…</p>
        <p className={styles.resumeText}>{project.last_open_question}</p>
        <span className={styles.resumeAction}>
          <Button onClick={onContinue} size={40} view="outlined">
            Продолжить
          </Button>
        </span>
      </div>
    );
  }

  return null;
}
