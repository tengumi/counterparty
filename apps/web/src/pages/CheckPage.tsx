/**
 * S2 — the conversation surface of one check.
 *
 * The screen holds what is shared between the conversation and the panel: the
 * chats of the project, the state of the materials panel and the way a basis
 * opens it. Nothing here is persisted on a server yet; the local state is a
 * per-viewer convenience only.
 */

import { useCallback, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ChatSurface } from '../screens/s2/ChatSurface';
import { CompanyContextStrip } from '../screens/s2/CompanyContextStrip';
import { MaterialsPanel } from '../screens/s2/MaterialsPanel';
import { ProjectHeader } from '../screens/s2/ProjectHeader';
import { readTaskHandoff } from '../screens/s2/taskHandoff';
import { parseMaterialsState, initialMaterials } from '../screens/s2/materialsView';
import type { MaterialsState, MaterialsView } from '../screens/s2/materialsView';
import { usePersistentState } from '../screens/s2/persisted';
import type { ChatSummary, ProjectDetail } from '../mocks/types';
import { findProject, newChat } from '../mocks/workspace';
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

function ProjectScreen({ project, threadId }: { project: ProjectDetail; threadId?: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [chats, setChats] = useState<readonly ChatSummary[]>(project.chats);
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
        saveState={project.saveState}
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
  const project = findProject(projectId);

  if (!project) return <ProjectNotFound />;
  return <ProjectScreen key={project.id} project={project} threadId={threadId} />;
}
