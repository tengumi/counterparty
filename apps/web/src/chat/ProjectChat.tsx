/**
 * One live chat of a real project: restore first, then subscribe (06 §3).
 *
 * Opening a thread reads the stored public projection over REST and only then
 * mounts the transport, so a run that is still working is re-attached instead
 * of being started again. A restore that fails is said out loud: an empty
 * thread and a silent thread look identical, and the difference matters.
 *
 * The composer is available from the first render — waiting for the restore
 * behind a disabled field would cost the draft's focus for nothing. The live
 * thread is only re-created when the restore actually brings something back,
 * which is the one moment the saved conversation has to replace the empty one.
 */

import type { ReactNode, RefObject } from 'react';
import { Button } from '@alfalab/core-components/button';
import { useQuery } from '@tanstack/react-query';
import { AgentChat } from './AgentChat';
import { conversationKeys, getThreadConversation } from './conversation';
import type { ThreadConversation } from './conversation';
import { WorkspaceApiError } from '../api/client';
import { requestErrorMessage } from '../api/messages';
import { EmptyConversation } from '../screens/s2/conversation/ConversationFeed';
import styles from '../screens/s2/conversation/Conversation.module.css';

export interface ProjectChatProps {
  readonly projectId: string;
  readonly threadId: string;
  readonly history?: ReactNode;
  readonly draft: string;
  readonly onDraftChange: (value: string) => void;
  readonly inputRef?: RefObject<HTMLTextAreaElement | null>;
  readonly onOpenEvidence?: (evidenceRef: string) => void;
  /** A task carried from S1, sent once on the first mount. */
  readonly autoSend?: string;
  readonly layout: (feed: ReactNode, composer: ReactNode) => ReactNode;
}

/** Whether the restore brought anything the empty thread does not already show. */
function hasStoredConversation(conversation: ThreadConversation | undefined): boolean {
  if (conversation === undefined) return false;
  return conversation.state.messages.length > 0 || conversation.activeRunId !== null;
}

export function ProjectChat({
  projectId,
  threadId,
  history,
  draft,
  onDraftChange,
  inputRef,
  onOpenEvidence,
  autoSend,
  layout,
}: ProjectChatProps) {
  const conversation = useQuery({
    queryKey: conversationKeys.thread(projectId, threadId),
    queryFn: () => getThreadConversation(projectId, threadId),
    retry: false,
    // The stored projection is read once per open; the stream owns it after.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const restored = hasStoredConversation(conversation.data) ? conversation.data : undefined;

  // A failed restore never becomes an empty history: the chat still works for
  // new messages, but what was said before is reported as not loaded. A thread
  // the service does not serve at all is a missing feature, not a failure, and
  // is stated as calmly as it deserves.
  const missing =
    conversation.error instanceof WorkspaceApiError && conversation.error.status === 404;
  const notice = conversation.isError ? (
    missing ? (
      <p className={styles.notice} data-testid="restore-state" role="status">
        Сохранённая история этого чата пока недоступна. Новые сообщения видны здесь, черновик
        сохраняется.
      </p>
    ) : (
      <p className={styles.composerError} data-testid="restore-state" role="alert">
        <span>
          Сохранённый разговор не загружен. {requestErrorMessage(conversation.error)} Это не
          значит, что переписки нет.
        </span>
        <Button onClick={() => void conversation.refetch()} size={32} view="outlined">
          Повторить
        </Button>
      </p>
    )
  ) : conversation.isPending ? (
    <p className={styles.notice} data-testid="restore-state" role="status">
      Загружаем сохранённый разговор…
    </p>
  ) : null;

  return (
    <AgentChat
      activeRunId={restored?.activeRunId ?? null}
      draft={draft}
      emptyState={conversation.isSuccess ? <EmptyConversation /> : null}
      history={
        <>
          {history}
          {notice}
        </>
      }
      initialState={restored?.state}
      autoSend={autoSend}
      inputRef={inputRef}
      onOpenEvidence={onOpenEvidence}
      key={restored === undefined ? 'live' : 'restored'}
      layout={layout}
      onDraftChange={onDraftChange}
      projectId={projectId}
      threadId={threadId}
    />
  );
}
