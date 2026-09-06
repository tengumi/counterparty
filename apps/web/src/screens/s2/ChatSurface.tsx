/**
 * One chat of S2: saved conversation, live thread and the composer.
 *
 * The surface owns the per-viewer conveniences of this chat — draft and scroll
 * position — and hands the conversation blocks to the renderers. The saved
 * blocks come from typed mocks today and from REST later; the live thread is
 * the Agent Service transport and is only mounted for the chat that has one.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Button } from '@alfalab/core-components/button';
import type { DiscussionContext } from '../../api/reportContracts';
import type { ApiProject } from '../../api/contracts';
import { ReturningState } from './ReturningState';
import { AgentChat } from '../../chat/AgentChat';
import { ProjectChat } from '../../chat/ProjectChat';
import {
  ConversationFeed,
  EmptyConversation,
} from './conversation/ConversationFeed';
import type { ConversationActions } from './conversation/ConversationFeed';
import { AssistantBoundary, Composer } from './conversation/Composer';
import { useAutoScroll } from './conversation/useAutoScroll';
import { parseNonEmptyString, parseNumber, readStored, usePersistentState, useRestoredScroll } from './persisted';
import type { ChatSummary, ProjectDetail } from '../../mocks/types';
import { getConversation } from '../../mocks/workspace';
import styles from './S2.module.css';

type MaterialActions = Pick<
  ConversationActions,
  'onOpenEvidence' | 'onOpenDocument' | 'onOpenSummary'
>;

interface Props {
  readonly project: ProjectDetail;
  readonly fixtureMode?: boolean;
  readonly chat: ChatSummary;
  /** Task text carried from S1; it is a draft, not a sent message. */
  readonly handoffDraft: string | null;
  readonly materialActions: MaterialActions;
  /** Lets the panel put a context chip into this chat's composer. */
  readonly onInsertDraftReady?: (insert: (text: string | DiscussionContext) => void) => void;
  /** What a returning user is told before the conversation itself. */
  readonly resume?: ApiProject;
}

const UNAVAILABLE =
  'Помощник пока недоступен. Черновик сохраняется; сведения компаний и сравнение доступны в материалах.';

export function ChatSurface({
  project,
  chat,
  handoffDraft,
  materialActions,
  onInsertDraftReady,
  resume,
  fixtureMode = false,
}: Props) {
  const draftKey = `draft:${project.id}:${chat.id}`;
  const scrollKey = `scroll:${project.id}:${chat.id}`;
  const [draft, setDraft] = usePersistentState(draftKey, handoffDraft ?? '', parseNonEmptyString);

  // The S1 task is auto-sent exactly once for the life of this chat. Clearing
  // it as state (not a ref) means the transport's own remount, when the stored
  // conversation loads, never sees the task a second time.
  const [autoSendTask, setAutoSendTask] = useState<string | null>(
    handoffDraft !== null && draft === handoffDraft ? handoffDraft : null,
  );
  const consumeAutoSend = useCallback(() => setAutoSendTask(null), []);

  const feedRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [hasSavedScroll] = useState(() => readStored(scrollKey, parseNumber) !== null);
  const saveScroll = useRestoredScroll(scrollKey, feedRef);
  const trackScroll = useAutoScroll(feedRef, contentRef, !hasSavedScroll);

  const blocks = fixtureMode ? getConversation(chat.id) : [];
  const isLive = fixtureMode && project.isDemo && chat.id === project.lastThreadId;
  const showsHandoff = handoffDraft !== null && draft === handoffDraft;

  const [contexts, setContexts] = usePersistentState<readonly DiscussionContext[]>(
    `contexts:${project.id}:${chat.id}`, [], (value) => Array.isArray(value) && value.every((item) =>
      item && typeof item === 'object' && typeof item.label === 'string' &&
      ((item.kind === 'evidence' && typeof item.evidence_ref === 'string') ||
       (item.kind === 'comparison' && item.selection && Array.isArray(item.selection.report_ids)))) ? value as DiscussionContext[] : null,
  );
  const insertDraft = useCallback(
    (text: string | DiscussionContext) => {
      if (typeof text !== 'string') {
        setContexts((current) => [...current.filter((item) => JSON.stringify(item) !== JSON.stringify(text)), text]);
        inputRef.current?.focus();
        return;
      }
      setDraft((previous) => {
        const current = previous.trim();
        return current.length === 0 ? text : `${current} ${text}`;
      });
      inputRef.current?.focus();
    },
    [setDraft, setContexts],
  );

  useEffect(() => {
    onInsertDraftReady?.(insertDraft);
  }, [insertDraft, onInsertDraftReady]);

  const actions: ConversationActions = {
    ...materialActions,
    onFocusComposer: () => inputRef.current?.focus(),
    onInsertDraft: insertDraft,
  };
  const focusComposer = useCallback(() => inputRef.current?.focus(), []);

  const history = (
    <>
      {resume ? <ReturningState project={resume} onContinue={focusComposer} onOpenSummary={materialActions.onOpenSummary} /> : null}
      <ConversationFeed actions={actions} blocks={blocks} />
      {blocks.length === 0 && !isLive && fixtureMode ? <EmptyConversation /> : null}
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
          {contexts.length ? <div className={styles.draftContexts} aria-label="Материалы в черновике">{contexts.map((context, index) => <span className={styles.draftContext} key={index}>
            <span>{context.label}</span>
            {context.kind === 'evidence' ? <Button size={32} view="text" onClick={() => materialActions.onOpenEvidence(context.evidence_ref)}>Открыть</Button> : null}
            <Button aria-label={`Убрать материал: ${context.label}`} size={32} view="text" onClick={() => setContexts((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Убрать</Button>
          </span>)}</div> : null}
          {composer}
          <AssistantBoundary />
        </div>
      </div>
    </div>
  );

  // Fixture chats keep the demo transport; a real project restores its stored
  // conversation over REST before it subscribes (06 §3).
  if (!fixtureMode) {
    return (
      <ProjectChat
        autoSend={autoSendTask ?? undefined}
        draft={draft}
        history={history}
        inputRef={inputRef}
        layout={layout}
        onAutoSent={consumeAutoSend}
        onDraftChange={setDraft}
        onOpenEvidence={materialActions.onOpenEvidence}
        projectId={project.id}
        threadId={chat.id}
      />
    );
  }

  if (isLive) {
    return (
      <AgentChat
        draft={draft}
        history={history}
        inputRef={inputRef}
        layout={layout}
        onDraftChange={setDraft}
        onOpenEvidence={materialActions.onOpenEvidence}
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
