/**
 * Wiring between assistant-ui's Assistant Transport runtime and our RPC.
 *
 * Everything protocol-shaped is the library's: this module only translates the
 * library request body into the domain command from Specs 10 §6, reflects a
 * cancel back into the published projection and keeps one honest client-side
 * fact the projection cannot carry — whether this browser is still connected.
 *
 * The hook deliberately holds no React state. `useAssistantTransportRuntime`
 * builds a fresh thread-list adapter on every render of its caller and reloads
 * the thread list from it, so a re-render of this hook's component discards the
 * live thread. Everything mutable is a ref or a `ValueStore`, and the changing
 * `resumeApi` is exposed as a getter the library reads at request time.
 */

import { useCallback, useMemo, useRef } from 'react';
import { useAssistantTransportRuntime } from '@assistant-ui/react';
import type {
  AssistantRuntime,
  AssistantTransportCommand,
  SendCommandsRequestBody,
} from '@assistant-ui/react';
import { convertAgentState } from './converter';
import { createValueStore } from './connectionStore';
import type { ValueStore } from './connectionStore';
import type { PublicAgentState, PublicMessage, PublicRun } from './publicAgentState';
import { TERMINAL_RUN_STATUSES, emptyAgentState } from './publicAgentState';

/**
 * Connection to the Agent Service, as this browser observes it.
 *
 * It is deliberately not part of `PublicAgentState`: a dropped stream says
 * nothing about the run, which may well be still working on the server
 * (Specs 04 §7, 06 §3). Keeping the two apart is what stops the UI from
 * announcing a finished or cancelled run when only the connection died.
 */
export type AgentConnection =
  | { readonly kind: 'online' }
  /** The stream broke while a non-terminal run was in flight. */
  | { readonly kind: 'lost'; readonly runId: string }
  /** The service did not accept the command; nothing was started. */
  | { readonly kind: 'unavailable'; readonly message: string };

const ONLINE: AgentConnection = { kind: 'online' };

export type AgentRuntimeOptions = {
  projectId: string;
  threadId: string;
  /** Origin of the Agent Service; empty string uses the dev-server proxy. */
  apiBase?: string;
  newId?: () => string;
  /** Stored projection restored over REST before any subscription. */
  initialState?: PublicAgentState;
  /** Run still active on the server when the thread was opened. */
  activeRunId?: string | null;
};

export interface AgentTransport {
  readonly runtime: AssistantRuntime;
  /** Read with `useStoreValue`; writing it never re-renders the host. */
  readonly connection: ValueStore<AgentConnection>;
  /** Re-subscribes to the active run; never re-sends the original message. */
  readonly reconnect: () => void;
  /** Clears a connection failure the user is about to retry. */
  readonly dismissConnection: () => void;
}

type DomainMessage = {
  id: string;
  text: string;
  document_ids: string[];
  evidence_refs: string[];
  company_ids: string[];
};

function toDomainCommands(
  commands: readonly AssistantTransportCommand[],
  newId: () => string,
): { type: 'add-message'; message: DomainMessage }[] {
  return commands.flatMap((command) => {
    if (command.type !== 'add-message' || command.message.role !== 'user') return [];
    const text = command.message.parts
      .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
      .map((part) => part.text)
      .join('');
    return [
      {
        type: 'add-message' as const,
        message: {
          id: newId(),
          text,
          document_ids: [],
          evidence_refs: [],
          company_ids: [],
        },
      },
    ];
  });
}

function cancelled(state: PublicAgentState, messageStatus: PublicMessage['status']): PublicAgentState {
  if (state.run === null) return state;
  return {
    ...state,
    run: { ...state.run, status: 'cancelled' },
    messages: state.messages.map((message) =>
      message.role === 'assistant' && (message.status === 'streaming' || message.status === 'pending')
        ? { ...message, status: messageStatus }
        : message,
    ),
  };
}

/** Product wording for a delivery that never reached a run. */
export function unavailableMessage(error: Error): string {
  if (/Status [45]\d\d/.test(error.message)) {
    return 'Помощник сейчас не отвечает. Сообщение не отправлено.';
  }
  return 'Не удалось связаться с помощником. Сообщение не отправлено.';
}

/**
 * Create the chat runtime for one project thread.
 *
 * The `/chat` response streams the public projection; `Stop` additionally
 * sends the separate cancel command, because aborting the subscription must
 * not be the only thing that stops a run (Specs 04 §7). Reconnect uses the
 * library's own resume path against `/runs/{id}/subscribe`, so re-attaching
 * replays the run instead of sending the message a second time.
 */
export function useAgentTransport(options: AgentRuntimeOptions): AgentTransport {
  const {
    projectId,
    threadId,
    apiBase = '',
    newId = () => crypto.randomUUID(),
    initialState,
    activeRunId = null,
  } = options;
  const emptyState = useMemo(() => emptyAgentState(projectId, threadId), [projectId, threadId]);
  const connection = useMemo(() => createValueStore<AgentConnection>(ONLINE), []);
  // The run this browser may re-attach to: the one restored on open, then
  // whichever run a broken stream left behind.
  const resumableRef = useRef<string | null>(activeRunId);

  const runtime = useAssistantTransportRuntime<PublicAgentState>({
    api: `${apiBase}/rpc/agent/chat`,
    // Read by the library when a resume actually runs, so the target follows
    // the current run without re-rendering this component.
    get resumeApi(): string | undefined {
      const runId = resumableRef.current;
      return runId === null
        ? undefined
        : `${apiBase}/rpc/agent/runs/${encodeURIComponent(runId)}/subscribe`;
    },
    protocol: 'assistant-transport',
    initialState: initialState ?? emptyState,
    headers: {},
    converter: convertAgentState,
    prepareSendCommandsRequest: (body: SendCommandsRequestBody) => ({
      project_id: projectId,
      thread_id: threadId,
      client_request_id: newId(),
      stream: true,
      commands: toDomainCommands(body.commands, newId),
    }),
    onError: (error, { updateState }) => {
      // The projection is the only place that knows whether a run exists; the
      // updater reads it and never writes an outcome the server did not send.
      const seen: { run: PublicRun | null } = { run: null };
      updateState((state) => {
        seen.run = state.run;
        return state;
      });
      const run = seen.run;
      if (run === null) {
        // Nothing was accepted, so the message was not delivered.
        connection.set({ kind: 'unavailable', message: unavailableMessage(error) });
        return;
      }
      if (!TERMINAL_RUN_STATUSES.includes(run.status)) {
        // The stream broke; the run itself may still be working (04 §7).
        resumableRef.current = run.id;
        connection.set({ kind: 'lost', runId: run.id });
        return;
      }
      // A run that already settled carries its own error in the projection.
      resumableRef.current = null;
      connection.set(ONLINE);
    },
    onCancel: ({ updateState, error }) => {
      // After a failure the runtime also cancels queued commands; the run is
      // already terminal then and must not be relabelled as cancelled.
      if (error !== undefined) return;
      updateState((state) => {
        if (state.run === null || TERMINAL_RUN_STATUSES.includes(state.run.status)) return state;
        // The updater is the only place the current run id is readable here.
        void fetch(`${apiBase}/rpc/agent/runs/${state.run.id}/cancel`, { method: 'POST' });
        resumableRef.current = null;
        return cancelled(state, 'partial');
      });
    },
  });

  const dismissConnection = useCallback(() => connection.set(ONLINE), [connection]);

  const reconnect = useCallback(() => {
    if (resumableRef.current === null) return;
    connection.set(ONLINE);
    runtime.thread.resumeRun({ parentId: null });
  }, [connection, runtime]);

  return { runtime, connection, reconnect, dismissConnection };
}
