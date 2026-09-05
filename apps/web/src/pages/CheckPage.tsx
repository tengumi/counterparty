/**
 * S2 — the conversation surface of one check.
 *
 * The screen holds what is shared between the conversation and the panel: the
 * chats of the project, the state of the materials panel and the way a basis
 * opens it. Nothing here is persisted on a server yet; the local state is a
 * per-viewer convenience only.
 */

import { useCallback, useRef, useState } from 'react';
import { Button } from '@alfalab/core-components/button';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { addCompanies, getProject, removeCompany, renameProject, WorkspaceApiError } from '../api/client';
import type { AddCompanyResult, ApiProject } from '../api/contracts';
import { requestErrorMessage } from '../api/messages';
import { projectDetail, withCompanies, workspaceKeys } from '../api/workspace';
import { ChatSurface } from '../screens/s2/ChatSurface';
import { CompanyContextStrip } from '../screens/s2/CompanyContextStrip';
import { MaterialsPanel } from '../screens/s2/MaterialsPanel';
import { ProjectHeader } from '../screens/s2/ProjectHeader';
import { readTaskHandoff } from '../screens/s2/taskHandoff';
import { parseMaterialsState, initialMaterials } from '../screens/s2/materialsView';
import type { MaterialsState, MaterialsView } from '../screens/s2/materialsView';
import { usePersistentState } from '../screens/s2/persisted';
import type { ChatSummary, ProjectDetail } from '../mocks/types';
import { newChat } from '../mocks/workspace';
import styles from '../screens/s2/S2.module.css';

function ProjectNotFound() {
  return (
    <section className={styles.conversationInner}>
      <h1>Проверка не найдена</h1>
      <p className={styles.muted}>Возможно, её удалили или ссылка устарела.</p>
      <Link to="/checks">Все проверки</Link>
    </section>
  );
}

function ChatNotFound() {
  return (
    <div className={styles.conversation}>
      <div className={styles.conversationInner}>
        <h2>Чат не найден</h2>
        <p className={styles.muted}>Выберите чат этой проверки в переключателе «Чат».</p>
      </div>
    </div>
  );
}

function ProjectScreen({ apiProject, project, threadId }: { apiProject: ApiProject; project: ProjectDetail; threadId?: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [chats, setChats] = useState<readonly ChatSummary[]>(project.chats);
  const [companyResults, setCompanyResults] = useState<readonly AddCompanyResult[]>([]);
  const [materials, setMaterials] = usePersistentState<MaterialsState>(
    `materials:${project.id}`,
    initialMaterials,
    parseMaterialsState,
  );
  const handoff = readTaskHandoff(location.state);
  // Set by the active chat so the panel can put a context chip in its composer.
  const insertDraft = useRef<((text: string) => void) | null>(null);
  const registerInsert = useCallback((insert: (text: string) => void) => {
    insertDraft.current = insert;
  }, []);
  const opener = useRef<HTMLElement | null>(null);

  const activeChatId = threadId ?? project.lastThreadId;
  const activeChat = chats.find((chat) => chat.id === activeChatId);

  const updateProject = (next: ApiProject) => {
    queryClient.setQueryData(workspaceKeys.project(project.id), next);
    void queryClient.invalidateQueries({ queryKey: workspaceKeys.all, exact: true });
  };
  const rename = useMutation({
    mutationFn: (title: string) => renameProject(project.id, title),
    onSuccess: updateProject,
  });
  const add = useMutation({
    mutationFn: (inns: readonly string[]) => addCompanies(project.id, inns, apiProject.context_version),
    onSuccess: (response) => {
      setCompanyResults(response.results);
      updateProject(withCompanies(apiProject, response));
    },
  });
  const remove = useMutation({
    mutationFn: (companyId: string) => removeCompany(project.id, companyId, apiProject.context_version),
    onSuccess: (response) => updateProject(withCompanies(apiProject, response)),
  });

  const openMaterials = (view: MaterialsView) => {
    // Focus returns to whatever opened the panel (07 §12).
    if (!materials.open) opener.current = document.activeElement as HTMLElement | null;
    setMaterials({
      ...materials,
      open: true,
      stack: view.kind === 'list' ? [{ kind: 'list' }] : [{ kind: 'list' }, view],
    });
  };

  const closeMaterials = () => {
    setMaterials({ ...materials, open: false });
    opener.current?.focus();
  };

  const openChat = (chatId: string) => {
    navigate(`/checks/${project.id}/chats/${chatId}`);
  };

  const createChat = () => {
    const created = newChat(chats.filter((chat) => chat.id.startsWith('local-chat-')).length + 1);
    setChats([...chats, created]);
    openChat(created.id);
  };

  return (
    <div className={styles.screen}>
      <ProjectHeader
        activeChatId={activeChat?.id}
        chats={chats}
        materialsOpen={materials.open}
        onCreateChat={createChat}
        onSelectChat={openChat}
        onToggleMaterials={() =>
          materials.open ? closeMaterials() : openMaterials({ kind: 'list' })
        }
        onRename={(title) => rename.mutate(title)}
        onRetryRename={rename.variables ? () => rename.mutate(rename.variables) : undefined}
        saveError={rename.error ? requestErrorMessage(rename.error) : null}
        saveState={rename.isPending ? 'saving' : rename.isError ? 'error' : project.saveState}
        title={project.title}
      />
      <CompanyContextStrip
        companies={project.companies}
        isDemo={project.isDemo}
        onAddCompany={() => openMaterials({ kind: 'list' })}
        onCompare={() => openMaterials({ kind: 'list' })}
        onOpenCompany={(companyId) => openMaterials({ kind: 'company', companyId })}
        status={project.status}
      />
      <div className={styles.body}>
        {activeChat === undefined ? (
          <ChatNotFound />
        ) : (
          <ChatSurface
            chat={activeChat}
            handoffDraft={handoff?.draft ?? null}
            key={activeChat.id}
            materialActions={{
              onOpenEvidence: (evidenceId) => openMaterials({ kind: 'evidence', evidenceId }),
              onOpenDocument: (documentId) => openMaterials({ kind: 'document', documentId }),
              onOpenSummary: () => openMaterials({ kind: 'summary' }),
            }}
            onInsertDraftReady={registerInsert}
            project={project}
          />
        )}
        {materials.open ? (
          <MaterialsPanel
            companyChange={{
              busy: add.isPending || remove.isPending,
              error: add.error ? requestErrorMessage(add.error) : remove.error ? requestErrorMessage(remove.error) : null,
              results: companyResults,
              onAdd: (inns) => add.mutate(inns),
              onRemove: (companyId) => remove.mutate(companyId),
            }}
            onChange={setMaterials}
            onClose={closeMaterials}
            onDiscuss={(text) => insertDraft.current?.(text)}
            project={project}
            state={materials}
          />
        ) : null}
      </div>
    </div>
  );
}

export function CheckPage() {
  const { projectId, threadId } = useParams();
  const projectQuery = useQuery({
    enabled: projectId !== undefined,
    queryKey: workspaceKeys.project(projectId ?? ''),
    queryFn: () => getProject(projectId as string),
    retry: false,
  });

  if (projectQuery.isPending) {
    return <section className={styles.conversationInner} role="status">Загружаем проверку…</section>;
  }
  if (projectQuery.isError) {
    if (projectQuery.error instanceof WorkspaceApiError && projectQuery.error.status === 404) {
      return <ProjectNotFound />;
    }
    return (
      <section className={styles.conversationInner} role="alert">
        <h1>Сведения проверки недоступны</h1>
        <p>{requestErrorMessage(projectQuery.error)}</p>
        <p className={styles.muted}>Это не означает, что рисков или сохранённых данных нет.</p>
        <Button onClick={() => void projectQuery.refetch()} size={40} view="outlined">Повторить</Button>
        <Link to="/checks">Все проверки</Link>
      </section>
    );
  }
  const project = projectDetail(projectQuery.data);
  return <ProjectScreen apiProject={projectQuery.data} key={project.id} project={project} threadId={threadId} />;
}
