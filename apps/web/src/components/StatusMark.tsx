/**
 * One status line: a colour dot plus its text label.
 *
 * The label carries the meaning; colour is only a repetition of it, because
 * colour alone is not an accessible status (07 §12).
 */

import styles from './StatusMark.module.css';
import type { ChatStatus, ProjectStatus } from '../mocks/types';
import { chatStatusLabels, projectStatusLabels } from '../mocks/types';

type Tone = 'neutral' | 'attention' | 'positive' | 'progress';

const projectTones: Readonly<Record<ProjectStatus, Tone>> = {
  in_progress: 'neutral',
  needs_input: 'attention',
  decision_recorded: 'positive',
};

const chatTones: Readonly<Record<ChatStatus, Tone>> = {
  running: 'progress',
  needs_input: 'attention',
  ready: 'positive',
};

export function ProjectStatusMark({ status }: { status: ProjectStatus }) {
  return (
    <span className={styles.mark}>
      <span aria-hidden="true" className={styles.dot} data-tone={projectTones[status]} />
      {projectStatusLabels[status]}
    </span>
  );
}

export function ChatStatusMark({ status }: { status: ChatStatus }) {
  return (
    <span className={styles.mark}>
      <span aria-hidden="true" className={styles.dot} data-tone={chatTones[status]} />
      {chatStatusLabels[status]}
    </span>
  );
}
