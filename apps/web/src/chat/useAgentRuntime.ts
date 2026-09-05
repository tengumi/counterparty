/**
 * Wiring between assistant-ui's Assistant Transport runtime and our RPC.
 *
 * Everything protocol-shaped is the library's: this module only translates the
 * library request body into the domain command from Specs 10 §6 and reflects
 * terminal outcomes back into the published projection.
 */

import { useMemo } from 'react';
import { useAssistantTransportRuntime } from '@assistant-ui/react';
import type {
  AssistantRuntime,
  AssistantTransportCommand,
  SendCommandsRequestBody,
} from '@assistant-ui/react';
import { convertAgentState } from './converter';
import type { PublicAgentState, PublicError, PublicMessage } from './publicAgentState';
import { TERMINAL_RUN_STATUSES, emptyAgentState } from './publicAgentState';

export type AgentRuntimeOptions = {
  projectId: string;
  threadId: string;
  /** Origin of the Agent Service; empty string uses the dev-server proxy. */
  apiBase?: string;
  newId?: () => string;
};

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

function settle(
  state: PublicAgentState,
  status: 'failed' | 'cancelled',
  messageStatus: PublicMessage['status'],
  error: PublicError | null,
): PublicAgentState {
  if (state.run === null) return state;
  return {
    ...state,
    run: { ...state.run, status, error: error ?? state.run.error },
    messages: state.messages.map((message) =>
      message.role === 'assistant' && (message.status === 'streaming' || message.status === 'pending')
        ? { ...message, status: messageStatus }
        : message,
    ),
  };
}

/**
 * Create the chat runtime for one project thread.
 *
 * The `/chat` response streams the public projection; `Stop` additionally
 * sends the separate cancel command, because aborting the subscription must
 * not be the only thing that stops a run (Specs 04 §7).
 */
export function useAgentRuntime(options: AgentRuntimeOptions): AssistantRuntime {
  const { projectId, threadId, apiBase = '', newId = () => crypto.randomUUID() } = options;
  const initialState = useMemo(
    () => emptyAgentState(projectId, threadId),
    [projectId, threadId],
  );

  return useAssistantTransportRuntime<PublicAgentState>({
    api: `${apiBase}/rpc/agent/chat`,
    protocol: 'assistant-transport',
    initialState,
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
      updateState((state) =>
        settle(state, 'failed', 'error', {
          code: 'internal_error',
          message: error.message,
          retryable: true,
          request_id: state.run?.id ?? threadId,
        }),
      );
    },
    onCancel: ({ updateState, error }) => {
      // After a failure the runtime also cancels queued commands; the run is
      // already terminal then and must not be relabelled as cancelled.
      if (error !== undefined) return;
      updateState((state) => {
        if (state.run === null || TERMINAL_RUN_STATUSES.includes(state.run.status)) return state;
        // The updater is the only place the current run id is readable here.
        void fetch(`${apiBase}/rpc/agent/runs/${state.run.id}/cancel`, { method: 'POST' });
        return settle(state, 'cancelled', 'partial', null);
      });
    },
  });
}
