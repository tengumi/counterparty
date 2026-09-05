/**
 * S1 — start or continue a check.
 *
 * Sending the task hands the draft to S2 through router state; nothing is
 * persisted yet, so the screen never claims a project was saved.
 */

import { useNavigate } from 'react-router-dom';
import { SavedChecksList } from '../screens/s1/SavedChecksList';
import { TaskComposer } from '../screens/s1/TaskComposer';
import { listProjects } from '../mocks/workspace';
import type { TaskHandoff } from '../screens/s2/taskHandoff';
import styles from '../screens/s1/S1.module.css';

export function ChecksPage() {
  const navigate = useNavigate();
  const projects = listProjects();

  const start = (task: string) => {
    const target = projects[0];
    if (!target) return;
    const handoff: TaskHandoff = { draft: task };
    navigate(`/checks/${target.id}/chats/${target.lastThreadId}`, { state: handoff });
  };

  return (
    <div className={styles.scroll}>
      <section className={styles.screen}>
        <h1 className={styles.title}>Проверка контрагентов</h1>
        <p className={styles.subtitle}>
          Разберитесь, готовы ли вы работать с компанией и на каких условиях
        </p>
        <TaskComposer onSubmit={start} />
        <SavedChecksList projects={projects} />
      </section>
    </div>
  );
}
