/**
 * The live conversation of one chat, on the Agent Service transport.
 *
 * The transport itself is the library's and is not re-implemented here: this
 * module turns the published projection into the S2 blocks (07 §5) and drives
 * the composer through the library's composer methods, so «Отправить» and
 * «Остановить» stay the runtime's own send and cancel commands.
 *
 * Three outcomes are kept apart on purpose (06 §3/§5): the agent finished or
 * was cancelled, the connection to it broke while it kept working, and the
 * service never accepted the message at all. Only the last one means the text
 * was not delivered, and none of them is ever rendered as an answer.
 *
 * Layout: `AgentRuntimeHost` owns the runtime and must not re-render, because
 * `useAssistantTransportRuntime` reloads its thread list from a new adapter on
 * every render of its caller and drops the live thread with it. Everything that
 * changes while the user works — draft, saved blocks, layout — reaches the
 * subtree through `ChatViewContext` instead of through the host's props.
 */

import {
  createContext,
  memo,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Button } from '@alfalab/core-components/button';
import type { ReactNode, RefObject } from 'react';
import { AssistantRuntimeProvider, ThreadPrimitive, useAui, useAuiState } from '@assistant-ui/react';
import { useAgentTransport } from './useAgentTransport';
import type { AgentConnection, AgentRuntimeOptions } from './useAgentTransport';
import { useStoreValue } from './connectionStore';
import type { ValueStore } from './connectionStore';
import type { PublicActivity, PublicAgentState, RunStatus } from './publicAgentState';
import { emptyAgentState, TERMINAL_RUN_STATUSES } from './publicAgentState';
import { useAgentProjection } from './useAgentProjection';
import { EvidenceRefContext } from './evidenceContext';
import { MarkdownContent } from './MarkdownText';
import { Composer } from '../screens/s2/conversation/Composer';
import type { ComposerStatus } from '../screens/s2/conversation/Composer';
import styles from '../screens/s2/conversation/Conversation.module.css';

/** Run states that still tell the user something they should act on. */
const NOTICE_STATUSES: ReadonlySet<RunStatus> = new Set([
  'cancelling',
  'awaiting_input',
  'cancelled',
  'interrupted',
]);

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

interface ChatView {
  readonly history?: ReactNode;
  readonly emptyState?: ReactNode;
  readonly draft: string;
  readonly onDraftChange: (value: string) => void;
  readonly inputRef?: RefObject<HTMLTextAreaElement | null>;
  /** A task carried from S1: sent once, automatically, on the first mount. */
  readonly autoSend?: string;
  /** Called right after the auto-sent task is dispatched. */
  readonly onAutoSent?: () => void;
  /** Called once when a run reaches a terminal status — the agent may have
      changed the check's composition (e.g. pinned a company by INN). */
  readonly onRunSettled?: () => void;
  readonly layout?: (feed: ReactNode, composer: ReactNode) => ReactNode;
}

const ChatViewContext = createContext<ChatView>({
  draft: '',
  onDraftChange: () => undefined,
});

const RUN_IN_FLIGHT: ReadonlySet<RunStatus> = new Set(['accepted', 'running', 'cancelling']);

/**
 * What the assistant did for one answer.
 *
 * While that run works it is a single live line — the current action, with a
 * pulsing dot — never a growing list and never a trailing «Проверка завершена».
 * Once the answer is in, it collapses to «Что было сделано», above the answer,
 * as a record of which parts of the report were read.
 */
function MessageTrail({
  activities,
  inFlight,
}: {
  activities: readonly PublicActivity[];
  inFlight: boolean;
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();

  // A tool call runs in a fraction of a second; the model then thinks for
  // several before the next one. Hold the last action on screen through that
  // gap so it's clear what just happened, then fall back to a neutral line.
  const running = activities.filter((activity) => activity.status === 'running');
  const liveLabel =
    running.length > 1 ? 'Собираю сведения' : running.length === 1 ? running[0]!.label : null;
  const [held, setHeld] = useState('Изучаю отчёт');
  useEffect(() => {
    if (!inFlight) return;
    if (liveLabel !== null) {
      setHeld(liveLabel);
      return;
    }
    const timer = setTimeout(() => setHeld('Формулирую ответ'), 4000);
    return () => clearTimeout(timer);
  }, [inFlight, liveLabel]);

  if (inFlight) {
    return (
      <p className={styles.activityLine} data-status="running">
        <span aria-hidden="true" className={styles.dot} data-status="running" />
        <span>{held}…</span>
      </p>
    );
  }

  if (activities.length === 0) return null;

  const failed = activities.some((activity) => activity.status === 'failed');
  return (
    <section aria-label="Что было сделано для ответа" className={styles.trailDone}>
      <button
        aria-controls={listId}
        aria-expanded={open}
        className={styles.trailToggle}
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span aria-hidden="true" className={styles.dot} data-status={failed ? 'failed' : 'completed'} />
        <span>{failed ? 'Часть сведений прочитать не удалось' : 'Что было сделано'}</span>
        <span className={styles.trailCount}>{activities.length}</span>
      </button>
      <ul className={styles.steps} hidden={!open} id={listId}>
        {activities.map((activity) => (
          <li className={styles.step} key={activity.id}>
            <span
              className={styles.stepLabel}
              data-kind={activity.kind}
              data-status={activity.status}
            >
              {activity.label}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The live thread, rendered straight from the projection so each answer can
 *  carry its own trail above it. */
function LiveConversation({ fallback }: { fallback: PublicAgentState }) {
  const state = useAgentProjection(fallback);
  const activeRunId =
    state.run !== null && RUN_IN_FLIGHT.has(state.run.status) ? state.run.id : null;
  // Rendering straight from the projection means we also own keeping the newest
  // message in view — a fresh answer must not land below the fold.
  const endRef = useRef<HTMLDivElement>(null);
  const tail = state.messages[state.messages.length - 1]?.blocks.map((b) => b.text).join('') ?? '';
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' });
  }, [state.messages.length, state.activities.length, tail, state.run?.status]);
  // Legacy / spike projections don't tag activities with a run; attribute the
  // whole list to the last assistant message so its trail still shows.
  const untagged = state.activities.every((activity) => activity.run_id == null);
  const lastAssistantId = [...state.messages].reverse().find((m) => m.role === 'assistant')?.id;

  return (
    <>
      {state.messages.map((message) => {
        if (message.role === 'user') {
          return (
            <div className={styles.user} key={message.id}>
              <div className={styles.bubble}>
                {message.blocks.map((block) => block.text).join('')}
              </div>
            </div>
          );
        }
        if (message.role !== 'assistant') return null;
        const runId = message.id.startsWith('assistant-')
          ? message.id.slice('assistant-'.length)
          : null;
        const activities =
          untagged && message.id === lastAssistantId
            ? state.activities
            : runId
              ? state.activities.filter((activity) => activity.run_id === runId)
              : [];
        return (
          <div className={styles.answer} key={message.id}>
            <MessageTrail activities={activities} inFlight={runId !== null && runId === activeRunId} />
            <div className={styles.answerText}>
              <MarkdownContent text={message.blocks.map((block) => block.text).join('')} />
            </div>
          </div>
        );
      })}
      <div aria-hidden="true" ref={endRef} />
    </>
  );
}

/**
 * A broken connection, told apart from a finished run.
 *
 * Re-attaching replays the run the server already owns; it never repeats the
 * user's message, which is why this is a separate control from «Повторить».
 */
function ConnectionState({
  connection,
  onReconnect,
}: {
  connection: AgentConnection;
  onReconnect: () => void;
}) {
  if (connection.kind === 'online') return null;
  if (connection.kind === 'lost') {
    return (
      <p className={styles.notice} data-testid="connection-state" role="status">
        <span>
          Связь с помощником прервана. Проверка могла продолжиться на сервере — отправлять
          сообщение заново не нужно.
        </span>
        <Button onClick={onReconnect} size={32} view="outlined">
          Подключиться заново
        </Button>
      </p>
    );
  }
  return (
    <p className={styles.composerError} data-testid="connection-state" role="alert">
      <span>
        {connection.message} Черновик сохранён; сведения компаний и сравнение открываются в
        материалах.
      </span>
    </p>
  );
}

/**
 * The single place a failed run is announced (07 E04/E05).
 *
 * One alert with one retry: the composer only keeps the draft, so the user is
 * never offered two competing ways to recover from the same failure.
 */
function RunState({
  state,
  connection,
  onRetry,
}: {
  state: PublicAgentState;
  connection: AgentConnection;
  onRetry: () => void;
}) {
  const run = state.run;
  // While the connection is down the published run status is stale by
  // definition, so it is not repeated next to the connection notice.
  const showsRun = connection.kind === 'online';
  return (
    <>
      {/* The raw status stays in the DOM for tests and assistive tooling. */}
      <span data-testid="run-status" hidden={true}>
        {run?.status ?? 'нет запуска'}
      </span>
      {/* A working or finished run is already shown — the activity dot while it
          runs, the answer once it is done. Only the states that change what the
          user should do get a line: needs input, stopping, stopped, broke. */}
      {showsRun && run !== null && !run.error && NOTICE_STATUSES.has(run.status) ? (
        <p className={styles.notice} role="status">
          {runLabels[run.status]}
        </p>
      ) : null}
      {showsRun && run?.error ? (
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

function composerStatus(
  state: PublicAgentState,
  isRunning: boolean,
  connection: AgentConnection,
): ComposerStatus {
  if (connection.kind === 'unavailable') return 'error';
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
  connection,
  lastSentRef,
  onSend,
}: {
  fallback: PublicAgentState;
  connection: AgentConnection;
  lastSentRef: RefObject<string>;
  onSend: () => void;
}) {
  const aui = useAui();
  const view = useContext(ChatViewContext);
  const state = useAgentProjection(fallback);
  const isRunning = useAuiState((value) => value.thread.isRunning);
  const send = useSendMessage(lastSentRef, () => view.onDraftChange(''));

  return (
    <Composer
      inputRef={view.inputRef}
      onChange={view.onDraftChange}
      onSend={(text) => {
        onSend();
        send(text);
      }}
      onStop={() => aui.thread.composer().cancel()}
      status={composerStatus(state, isRunning, connection)}
      value={view.draft}
    />
  );
}

function LiveTrail({
  fallback,
  connection,
  lastSentRef,
  onReconnect,
  onRetry,
}: {
  fallback: PublicAgentState;
  connection: AgentConnection;
  lastSentRef: RefObject<string>;
  onReconnect: () => void;
  onRetry: () => void;
}) {
  const view = useContext(ChatViewContext);
  const state = useAgentProjection(fallback);
  const send = useSendMessage(lastSentRef, () => undefined);
  // Reading the ref inside the handler keeps render free of ref access.
  const retry = () => {
    onRetry();
    send(lastSentRef.current);
  };
  return (
    <>
      {state.messages.length === 0 && state.run === null ? view.emptyState : null}
      <RunSettledSignal state={state} />
      <ConnectionState connection={connection} onReconnect={onReconnect} />
      <RunState connection={connection} onRetry={retry} state={state} />
    </>
  );
}

/** Fires `onRunSettled` once per run once it reaches a terminal status. */
function RunSettledSignal({ state }: { state: PublicAgentState }) {
  const view = useContext(ChatViewContext);
  const settled = useRef<string | null>(null);
  const run = state.run;
  useEffect(() => {
    if (run === null || settled.current === run.id) return;
    if (!TERMINAL_RUN_STATUSES.includes(run.status)) return;
    settled.current = run.id;
    view.onRunSettled?.();
  }, [run, view]);
  return null;
}

/**
 * Sends the task carried from S1 once, so arriving in the chat does not leave
 * an unsent draft the user has to submit a second time.
 */
function AutoSend({ lastSentRef }: { lastSentRef: RefObject<string> }) {
  const view = useContext(ChatViewContext);
  const send = useSendMessage(lastSentRef, () => view.onDraftChange(''));
  const done = useRef(false);
  useEffect(() => {
    const text = view.autoSend?.trim();
    if (done.current || !text) return;
    done.current = true;
    send(text);
    view.onAutoSent?.();
  }, [send, view]);
  return null;
}

/** The whole chat body; everything that changes lives below the runtime host. */
function ChatBody({
  fallback,
  connectionStore,
  lastSentRef,
  onReconnect,
  onRetry,
}: {
  fallback: PublicAgentState;
  connectionStore: ValueStore<AgentConnection>;
  lastSentRef: RefObject<string>;
  onReconnect: () => void;
  onRetry: () => void;
}) {
  const view = useContext(ChatViewContext);
  const connection = useStoreValue(connectionStore);

  const feed = (
    <>
      {view.history}
      <AutoSend lastSentRef={lastSentRef} />
      <LiveConversation fallback={fallback} />
      <LiveTrail
        connection={connection}
        fallback={fallback}
        lastSentRef={lastSentRef}
        onReconnect={onReconnect}
        onRetry={onRetry}
      />
    </>
  );
  const composer = (
    <AgentComposer
      connection={connection}
      fallback={fallback}
      lastSentRef={lastSentRef}
      onSend={onRetry}
    />
  );

  return (
    <ThreadPrimitive.Root className={view.layout ? styles.threadRoot : styles.feed}>
      {view.layout ? view.layout(feed, composer) : (
        <>
          {feed}
          {composer}
        </>
      )}
    </ThreadPrimitive.Root>
  );
}

/**
 * Owns the runtime for one thread and never re-renders on view changes.
 *
 * Its props are the transport options only, so `memo` keeps the live thread
 * alive while the user types, opens the panel or scrolls.
 */
const AgentRuntimeHost = memo(function AgentRuntimeHost(options: AgentRuntimeOptions) {
  const { runtime, connection, reconnect, dismissConnection } = useAgentTransport(options);
  const fallback = useMemo(
    () => options.initialState ?? emptyAgentState(options.projectId, options.threadId),
    [options.initialState, options.projectId, options.threadId],
  );
  const lastSentRef = useRef('');

  // A run that was still active when the thread was opened is re-attached once;
  // Specs 04 §7 forbids re-sending the message that started it.
  const attached = useRef(false);
  useEffect(() => {
    if (attached.current || options.activeRunId == null) return;
    attached.current = true;
    reconnect();
  }, [options.activeRunId, reconnect]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ChatBody
        connectionStore={connection}
        fallback={fallback}
        lastSentRef={lastSentRef}
        onReconnect={reconnect}
        onRetry={dismissConnection}
      />
    </AssistantRuntimeProvider>
  );
});

export interface AgentChatProps extends AgentRuntimeOptions {
  /** Saved blocks rendered above the live thread. */
  readonly history?: ReactNode;
  /** Shown while the thread genuinely has no messages of its own. */
  readonly emptyState?: ReactNode;
  readonly draft?: string;
  readonly onDraftChange?: (value: string) => void;
  readonly inputRef?: RefObject<HTMLTextAreaElement | null>;
  /** Opens a numbered basis cited in an answer (07 P1-03). */
  readonly onOpenEvidence?: (evidenceRef: string) => void;
  /** A task carried from S1, sent once on the first mount. */
  readonly autoSend?: string;
  /** Called right after the auto-sent task is dispatched. */
  readonly onAutoSent?: () => void;
  /** Called once a run settles; the check's composition may have changed. */
  readonly onRunSettled?: () => void;
  /** Places the feed and the composer into the screen layout. */
  readonly layout?: (feed: ReactNode, composer: ReactNode) => ReactNode;
}

export function AgentChat({
  history,
  emptyState,
  draft,
  onDraftChange,
  inputRef,
  onOpenEvidence,
  autoSend,
  onAutoSent,
  onRunSettled,
  layout,
  ...options
}: AgentChatProps) {
  // A chat rendered without an owner of the draft keeps it locally.
  const [localDraft, setLocalDraft] = useState('');
  const view: ChatView = {
    history,
    emptyState,
    draft: draft ?? localDraft,
    onDraftChange: onDraftChange ?? setLocalDraft,
    inputRef,
    autoSend,
    onAutoSent,
    onRunSettled,
    layout,
  };

  return (
    <EvidenceRefContext.Provider value={onOpenEvidence ?? null}>
      <ChatViewContext.Provider value={view}>
        <AgentRuntimeHost
          activeRunId={options.activeRunId}
          apiBase={options.apiBase}
          initialState={options.initialState}
          newId={options.newId}
          projectId={options.projectId}
          threadId={options.threadId}
        />
      </ChatViewContext.Provider>
    </EvidenceRefContext.Provider>
  );
}
