/** Старт проверки: создаём проект и передаём первый вопрос в разговор. История — в общей навигации. */

import { useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { createProject } from '../api/client';
import { requestErrorMessage } from '../api/messages';
import { workspaceKeys } from '../api/workspace';
import { TaskComposer } from '../screens/s1/TaskComposer';
import type { TaskHandoff } from '../screens/s2/taskHandoff';
import styles from '../screens/s1/S1.module.css';

export function ChecksPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pending = useRef<{ task: string; requestId: string } | null>(null);
  const create = useMutation({
    mutationFn: ({ task, requestId }: { task: string; requestId: string }) =>
      createProject(task, requestId),
    onSuccess: ({ project }, variables) => {
      pending.current = null;
      queryClient.setQueryData(workspaceKeys.project(project.id), project);
      void queryClient.invalidateQueries({ queryKey: workspaceKeys.all, exact: true });
      const handoff: TaskHandoff = { draft: variables.task };
      navigate(`/checks/${project.id}/chats/${project.default_thread_id}`, { state: handoff });
    },
  });

  const start = (task: string) => {
    if (pending.current?.task !== task) {
      pending.current = { task, requestId: crypto.randomUUID() };
    }
    create.mutate(pending.current);
  };

  return (
    <div className={styles.scroll}>
      <section className={styles.screen}>
        <h1 className={styles.title}>Проверка контрагентов</h1>
        <p className={styles.subtitle}>
          Разберитесь, готовы ли вы работать с компанией и на каких условиях
        </p>
        <TaskComposer
          error={create.error ? requestErrorMessage(create.error) : null}
          loading={create.isPending}
          onSubmit={start}
        />
      </section>
    </div>
  );
}
