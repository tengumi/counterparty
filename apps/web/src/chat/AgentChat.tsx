/**
 * The live conversation of one chat, on the Agent Service transport.
 *
 * The transport itself is C1's and is not touched here: this module only turns
 * the published projection into the S2 blocks (07 §5) and drives the composer
 * through the library's composer methods, so «Отправить» and «Остановить» stay
 * the runtime's own send and cancel commands.
 */

import { useMemo, useRef, useState } from 'react';
import { Button } from '@alfalab/core-components/button';
import type { ReactNode, RefObject } from 'react';
import {
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
} from '@assistant-ui/react';
import { useAgentRuntime } from './useAgentRuntime';
import type { AgentRuntimeOptions } from './useAgentRuntime';
import type { PublicActivity, PublicAgentState, RunStatus } from './publicAgentState';
import { emptyAgentState } from './publicAgentState';
import { useAgentProjection } from './useAgentProjection';
import { ActivityBlock } from '../screens/s2/conversation/ConversationFeed';
import { Composer } from '../screens/s2/conversation/Composer';
import type { ComposerStatus } from '../screens/s2/conversation/Composer';
import type { ActivityStep } from '../mocks/types';
import styles from '../screens/s2/conversation/Conversation.module.css';

/** Product wording for a run state; never a library or protocol term. */
const runLabels: Readonly<Record<RunStatus, string>> = {
  accepted: 'Помощник принял запрос',
  running: 'Помощник работает',
  cancelling: 'Останавливаем проверку…',
  completed: 'Ответ готов',
  awaiting_input: 'Нужны сведения',
  failed: 'Помощник временно недоступен',
  cancelled: 'Проверка остановлена. Выполненные действия сохранены',
  interrupted: 'Проверка прервана. Сохранённые данные доступны',
};

/** Human source of a typed activity; MCP arguments are never shown. */
const activitySources: Readonly<Record<string, string>> = {
  reading_report: 'Отчёт компании',
  reading_document: 'Документ проверки',
  comparing: 'Сравнение сведений',
  calculating: 'Расчёт по условиям',
  updating_analysis: 'Обновление вывода',
  skill_invocation: 'Навык помощника',
};

function toStep(activity: PublicActivity): ActivityStep {
  return {
    id: activity.id,
    kind: activity.kind,
    label: activity.label,
    source: activitySources[activity.kind] ?? 'Сведения проверки',
    status: activity.status,
  };
}

function LiveActivity({ state }: { state: PublicAgentState }) {
  if (state.activities.length === 0) return null;

  const running = state.activities.find((activity) => activity.status === 'running');
  const failed = state.activities.some((activity) => activity.status === 'failed');
  const label = running?.label ?? (failed ? 'Часть сведений прочитать не удалось' : 'Проверка завершена');
  const status = running ? 'running' : failed ? 'failed' : 'completed';

  return <ActivityBlock label={label} status={status} steps={state.activities.map(toStep)} />;
}

function LiveMessages() {
  return (
    <ThreadPrimitive.Messages
      components={{
        UserMessage: () => (
          <div className={styles.user}>
            <p className={styles.bubble}>
              <MessagePrimitive.Parts />
            </p>
          </div>
        ),
        AssistantMessage: () => (
          <div className={styles.answer}>
            <p className={styles.answerText}>
              <MessagePrimitive.Parts />
            </p>
          </div>
        ),
      }}
    />
  );
}

/**
 * The single place a failed run is announced (07 E04/E05).
 *
 * One alert with one retry: the composer only keeps the draft, so the user is
 * never offered two competing ways to recover from the same failure.
 */
function RunState({ state, onRetry }: { state: PublicAgentState; onRetry: () => void }) {
  const run = state.run;
  return (
    <>
      {/* The raw status stays in the DOM for tests and assistive tooling. */}
      <span data-testid="run-status" hidden={true}>
        {run?.status ?? 'нет запуска'}
      </span>
      {run !== null && run.status !== 'accepted' && !run.error ? (
        <p className={styles.notice} role="status">
          {runLabels[run.status]}
        </p>
      ) : null}
      {run?.error ? (
        <p className={styles.composerError} role="alert">
          <span>
            {runLabels[run.status]}. {run.error.message}
          </span>
          {run.error.retryable ? (
            <Button onClick={onRetry} size={32} view="outlined">
              Повторить
            </Button>
          ) : null}
        </p>
      ) : null}
    </>
  );
}

function composerStatus(state: PublicAgentState, isRunning: boolean): ComposerStatus {
  const status = state.run?.status;
  if (status === 'failed') return 'error';
  if (status === 'cancelling') return 'cancelling';
  if (status === 'running') return 'running';
  if (isRunning) return 'sending';
  return 'idle';
}

/**
 * Sending stays the library's own composer command.
 *
 * `lastSentRef` is what a retry re-sends: the same text, so a failed delivery is
 * repeated rather than rewritten by the user.
 */
function useSendMessage(
  lastSentRef: RefObject<string>,
  onSent: () => void,
): (text: string) => void {
  const aui = useAui();
  return (text: string) => {
    if (text.trim().length === 0) return;
    lastSentRef.current = text;
    aui.thread.composer().setText(text);
    aui.thread.composer().send();
    onSent();
  };
}

function AgentComposer({
  fallback,
  draft,
  lastSentRef,
  onDraftChange,
  inputRef,
}: {
  fallback: PublicAgentState;
  draft: string;
  lastSentRef: RefObject<string>;
  onDraftChange: (value: string) => void;
  inputRef?: RefObject<HTMLTextAreaElement | null>;
}) {
  const aui = useAui();
  const state = useAgentProjection(fallback);
  const isRunning = useAuiState((value) => value.thread.isRunning);
  const send = useSendMessage(lastSentRef, () => onDraftChange(''));

  return (
    <Composer
      inputRef={inputRef}
      onChange={onDraftChange}
      onSend={send}
      onStop={() => aui.thread.composer().cancel()}
      status={composerStatus(state, isRunning)}
      value={draft}
    />
  );
}

export interface AgentChatProps extends AgentRuntimeOptions {
  /** Saved blocks rendered above the live thread. */
  readonly history?: ReactNode;
  readonly draft?: string;
  readonly onDraftChange?: (value: string) => void;
  readonly inputRef?: RefObject<HTMLTextAreaElement | null>;
  /** Places the feed and the composer into the screen layout. */
  readonly layout?: (feed: ReactNode, composer: ReactNode) => ReactNode;
}

export function AgentChat({
  history,
  draft,
  onDraftChange,
  inputRef,
  layout,
  ...options
}: AgentChatProps) {
  const runtime = useAgentRuntime(options);
  const fallback = useMemo(
    () => emptyAgentState(options.projectId, options.threadId),
    [options.projectId, options.threadId],
  );
  // A chat rendered without an owner of the draft keeps it locally.
  const [localDraft, setLocalDraft] = useState('');
  const lastSentRef = useRef('');
  const value = draft ?? localDraft;
  const change = onDraftChange ?? setLocalDraft;

  const feed = (
    <>
      {history}
      <LiveMessages />
      <LiveTrail fallback={fallback} lastSentRef={lastSentRef} />
    </>
  );
  const composer = (
    <AgentComposer
      draft={value}
      fallback={fallback}
      inputRef={inputRef}
      lastSentRef={lastSentRef}
      onDraftChange={change}
    />
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className={styles.feed}>
        {layout ? layout(feed, composer) : (
          <>
            {feed}
            {composer}
          </>
        )}
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

function LiveTrail({
  fallback,
  lastSentRef,
}: {
  fallback: PublicAgentState;
  lastSentRef: RefObject<string>;
}) {
  const state = useAgentProjection(fallback);
  const send = useSendMessage(lastSentRef, () => undefined);
  // Reading the ref inside the handler keeps render free of ref access.
  const retry = () => send(lastSentRef.current);
  return (
    <>
      <LiveActivity state={state} />
      <RunState onRetry={retry} state={state} />
    </>
  );
}
