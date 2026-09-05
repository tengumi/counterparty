/**
 * S2 — the conversation surface of one check.
 *
 * D2 delivers the frame: header, chat switcher, company strip and the
 * responsive layout with the materials panel. The conversation itself is the
 * existing agent-transport demo; other chats stay honestly empty.
 */

import { useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { AgentChat } from '../chat/AgentChat';
import { CompanyContextStrip } from '../screens/s2/CompanyContextStrip';
import { MaterialsPanel } from '../screens/s2/MaterialsPanel';
import type { MaterialsSection } from '../screens/s2/MaterialsPanel';
import { ProjectHeader } from '../screens/s2/ProjectHeader';
import { readTaskHandoff } from '../screens/s2/taskHandoff';
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

function Conversation({
  project,
  chat,
  draft,
}: {
  project: ProjectDetail;
  chat: ChatSummary | undefined;
  draft: string | null;
}) {
  if (!chat) {
    return (
      <div className={styles.card}>
        <h2>Чат не найден</h2>
        <p className={styles.muted}>Выберите чат этой проверки в переключателе «Чат».</p>
      </div>
    );
  }

  const isDemoConversation = project.isDemo && chat.id === project.lastThreadId;

  return (
    <>
      {draft ? (
        <div className={styles.card}>
          <h2>Черновик задачи</h2>
          <p className={styles.draft}>{draft}</p>
          <p className={styles.muted}>
            Текст перенесён из «Проверки». Он ещё не отправлен и не сохранён.
          </p>
        </div>
      ) : null}
      <div className={styles.card}>
        <h2>{chat.title}</h2>
        {isDemoConversation ? (
          <AgentChat projectId={project.id} threadId={chat.id} />
        ) : (
          <p className={styles.muted}>
            Разговор этого чата пока недоступен: сведения проверки не загружены.
          </p>
        )}
      </div>
    </>
  );
}

function ProjectScreen({ project, threadId }: { project: ProjectDetail; threadId?: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [chats, setChats] = useState<readonly ChatSummary[]>(project.chats);
  const [materials, setMaterials] = useState<MaterialsSection | null>(null);
  const handoff = readTaskHandoff(location.state);

  const activeChatId = threadId ?? project.lastThreadId;
  const activeChat = chats.find((chat) => chat.id === activeChatId);

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
        materialsOpen={materials !== null}
        onCreateChat={createChat}
        onSelectChat={openChat}
        onToggleMaterials={() => setMaterials((open) => (open === null ? 'companies' : null))}
        saveState={project.saveState}
        title={project.title}
      />
      <CompanyContextStrip
        companies={project.companies}
        isDemo={project.isDemo}
        onAddCompany={() => setMaterials('companies')}
        onCompare={() => setMaterials('companies')}
        onOpenCompany={() => setMaterials('companies')}
        status={project.status}
      />
      <div className={styles.body}>
        <div className={styles.conversation}>
          <div className={styles.conversationInner}>
            <Conversation chat={activeChat} draft={handoff?.draft ?? null} project={project} />
          </div>
        </div>
        {materials !== null ? (
          <MaterialsPanel onClose={() => setMaterials(null)} section={materials} />
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
