/**
 * S1 — start or continue a check.
 *
 * Sending the task hands the draft to S2 through router state; nothing is
 * persisted yet, so the screen never claims a project was saved.
 */

import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@alfalab/core-components/button';
import { useNavigate } from 'react-router-dom';
import { createProject, listProjects } from '../api/client';
import { requestErrorMessage } from '../api/messages';
import { projectSummary, workspaceKeys } from '../api/workspace';
import { SavedChecksList } from '../screens/s1/SavedChecksList';
import { TaskComposer } from '../screens/s1/TaskComposer';
import type { TaskHandoff } from '../screens/s2/taskHandoff';
import styles from '../screens/s1/S1.module.css';

export function ChecksPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pending = useRef<{ task: string; requestId: string } | null>(null);
  const projectsQuery = useQuery({ queryKey: workspaceKeys.all, queryFn: listProjects, retry: false });
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
  const projects = (projectsQuery.data ?? []).map(projectSummary);

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
        {projectsQuery.isPending ? <p className={styles.state} role="status">Загружаем проверки…</p> : null}
        {projectsQuery.isError ? (
          <div className={styles.errorState} role="alert">
            <p>{requestErrorMessage(projectsQuery.error)}</p>
            <p>Это не означает, что сохранённых проверок нет.</p>
            <Button onClick={() => void projectsQuery.refetch()} size={40} view="outlined">Повторить</Button>
          </div>
        ) : null}
        {projectsQuery.isSuccess ? <SavedChecksList projects={projects} /> : null}
      </section>
    </div>
  );
}
