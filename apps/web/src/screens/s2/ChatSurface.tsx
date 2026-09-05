/**
 * One chat of S2: saved conversation, live thread and the composer.
 *
 * The surface owns the per-viewer conveniences of this chat — draft and scroll
 * position — and hands the conversation blocks to the renderers. The saved
 * blocks come from typed mocks today and from REST later; the live thread is
 * the Agent Service transport and is only mounted for the chat that has one.
 */

import { useCallback, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { AgentChat } from '../../chat/AgentChat';
import {
  ConversationFeed,
  EmptyConversation,
} from './conversation/ConversationFeed';
import type { ConversationActions } from './conversation/ConversationFeed';
import { AssistantBoundary, Composer } from './conversation/Composer';
import { useAutoScroll } from './conversation/useAutoScroll';
import { parseNonEmptyString, usePersistentState, useRestoredScroll } from './persisted';
import type { ChatSummary, ProjectDetail } from '../../mocks/types';
import { getConversation } from '../../mocks/workspace';
import styles from './S2.module.css';

type MaterialActions = Pick<
  ConversationActions,
  'onOpenEvidence' | 'onOpenDocument' | 'onOpenSummary'
>;

interface Props {
  readonly project: ProjectDetail;
  readonly chat: ChatSummary;
  /** Task text carried from S1; it is a draft, not a sent message. */
  readonly handoffDraft: string | null;
  readonly materialActions: MaterialActions;
  /** Lets the panel put a context chip into this chat's composer. */
  readonly onInsertDraftReady?: (insert: (text: string) => void) => void;
}

const UNAVAILABLE =
  'Помощник отвечает только в учебном примере: сервер этой проверки не подключён. Черновик сохраняется.';

export function ChatSurface({
  project,
  chat,
  handoffDraft,
  materialActions,
  onInsertDraftReady,
}: Props) {
  const draftKey = `draft:${project.id}:${chat.id}`;
  const scrollKey = `scroll:${project.id}:${chat.id}`;
  const [draft, setDraft] = usePersistentState(draftKey, handoffDraft ?? '', parseNonEmptyString);

  const feedRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const saveScroll = useRestoredScroll(scrollKey, feedRef);
  const trackScroll = useAutoScroll(feedRef, contentRef);

  const blocks = getConversation(chat.id);
  const isLive = project.isDemo && chat.id === project.lastThreadId;
  const showsHandoff = handoffDraft !== null && draft === handoffDraft;

  const insertDraft = useCallback(
    (text: string) => {
      setDraft((previous) => {
        const current = previous.trim();
        return current.length === 0 ? text : `${current} ${text}`;
      });
      inputRef.current?.focus();
    },
    [setDraft],
  );

  useEffect(() => {
    onInsertDraftReady?.(insertDraft);
  }, [insertDraft, onInsertDraftReady]);

  const actions: ConversationActions = {
    ...materialActions,
    onFocusComposer: () => inputRef.current?.focus(),
    onInsertDraft: insertDraft,
  };

  const history = (
    <>
      <ConversationFeed actions={actions} blocks={blocks} />
      {blocks.length === 0 && !isLive ? <EmptyConversation /> : null}
    </>
  );

  const onScroll = () => {
    trackScroll();
    saveScroll();
  };

  const layout = (feed: ReactNode, composer: ReactNode) => (
    <div className={styles.conversation}>
      <div className={styles.feedScroll} onScroll={onScroll} ref={feedRef}>
        <div className={styles.conversationInner} ref={contentRef}>
          {feed}
        </div>
      </div>
      <div className={styles.dock}>
        <div className={styles.dockInner}>
          {showsHandoff ? (
            <p className={styles.handoff}>
              Текст перенесён из «Проверки». Он ещё не отправлен и не сохранён.
            </p>
          ) : null}
          {composer}
          <AssistantBoundary />
        </div>
      </div>
    </div>
  );

  if (isLive) {
    return (
      <AgentChat
        draft={draft}
        history={history}
        inputRef={inputRef}
        layout={layout}
        onDraftChange={setDraft}
        projectId={project.id}
        threadId={chat.id}
      />
    );
  }

  return layout(
    history,
    <Composer
      inputRef={inputRef}
      onChange={setDraft}
      onSend={() => undefined}
      onStop={() => undefined}
      status="unavailable"
      unavailableReason={UNAVAILABLE}
      value={draft}
    />,
  );
}
