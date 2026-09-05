/**
 * State converter for the assistant-ui Assistant Transport runtime.
 *
 * The runtime keeps our `PublicAgentState` as its opaque external state; this
 * converter is the only place that turns it into assistant-ui messages.
 */

import { fromThreadMessageLike } from '@assistant-ui/react';
import type {
  AssistantTransportCommand,
  AssistantTransportConnectionMetadata,
  ThreadMessage,
} from '@assistant-ui/react';
import type { MessageStatus, PublicAgentState, PublicMessage } from './publicAgentState';

const ASSISTANT_STATUS: Record<MessageStatus, ThreadMessage['status']> = {
  pending: { type: 'running' },
  streaming: { type: 'running' },
  complete: { type: 'complete', reason: 'stop' },
  partial: { type: 'incomplete', reason: 'cancelled' },
  error: { type: 'incomplete', reason: 'error' },
};

function textOf(message: PublicMessage): string {
  return message.blocks.map((block) => block.text).join('');
}

function toThreadMessage(message: PublicMessage): ThreadMessage {
  const isAssistant = message.role === 'assistant';
  return fromThreadMessageLike(
    {
      id: message.id,
      role: isAssistant ? 'assistant' : 'user',
      content: [{ type: 'text', text: textOf(message) }],
      createdAt: new Date(message.created_at),
      // The library rejects a status on non-assistant messages.
      ...(isAssistant ? { status: ASSISTANT_STATUS[message.status] } : {}),
    },
    message.id,
    { type: 'complete', reason: 'stop' },
  );
}

function optimisticText(commands: readonly AssistantTransportCommand[]): string[] {
  return commands.flatMap((command) =>
    command.type === 'add-message' && command.message.role === 'user'
      ? command.message.parts
          .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
          .map((part) => part.text)
      : [],
  );
}

/**
 * Convert the published projection plus in-flight commands into thread state.
 *
 * Commands the server has not echoed back yet are rendered optimistically so
 * the composer clears immediately, as the runtime contract expects.
 */
export function convertAgentState(
  state: PublicAgentState,
  metadata: AssistantTransportConnectionMetadata,
): { messages: ThreadMessage[]; isRunning: boolean } {
  const messages = state.messages.map(toThreadMessage);
  const pending = optimisticText(metadata.pendingCommands).map((text, index) =>
    fromThreadMessageLike(
      { role: 'user', content: [{ type: 'text', text }] },
      `pending-${index}`,
      { type: 'complete', reason: 'stop' },
    ),
  );

  return {
    messages: [...messages, ...pending],
    isRunning: metadata.isSending || state.run?.status === 'running',
  };
}
