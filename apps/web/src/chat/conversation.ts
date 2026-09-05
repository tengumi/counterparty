/**
 * Saved public conversation projection of one thread (Specs 06 §3, 10 §5).
 *
 * Opening a project reads the stored projection over REST first and only then
 * subscribes to a run that is still active. This module is the REST half: it
 * never invents messages, so a service that cannot answer yields an explicit
 * failure instead of an empty-but-confident history.
 */

import { WorkspaceApiError, requestJson } from '../api/client';
import type { PublicAgentState } from './publicAgentState';
import { emptyAgentState } from './publicAgentState';

export interface ThreadConversation {
  /** The projection as the server stored it. */
  readonly state: PublicAgentState;
  /** The run still executing on the server, if any; a reconnect target. */
  readonly activeRunId: string | null;
}

type ConversationBody = Partial<PublicAgentState> & { readonly active_run_id?: unknown };

export const conversationKeys = {
  thread: (projectId: string, threadId: string) =>
    ['workspace', 'projects', projectId, 'threads', threadId, 'conversation'] as const,
};

function isConversationBody(value: unknown): value is ConversationBody {
  if (typeof value !== 'object' || value === null) return false;
  const body = value as ConversationBody;
  return Array.isArray(body.messages) && Array.isArray(body.activities);
}

/**
 * Read the stored conversation of one thread.
 *
 * Unknown fields are filled from the empty projection so a partial answer stays
 * renderable; a body that is not a projection at all is an error, not a blank
 * conversation.
 */
export async function getThreadConversation(
  projectId: string,
  threadId: string,
): Promise<ThreadConversation> {
  const { data } = await requestJson<unknown>(
    `/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}/conversation`,
  );
  if (!isConversationBody(data)) {
    throw new WorkspaceApiError(
      200,
      'invalid_response',
      'Сервис вернул разговор в неизвестном формате. История не загружена.',
      true,
      null,
    );
  }
  const activeRunId = typeof data.active_run_id === 'string' ? data.active_run_id : null;
  return {
    state: { ...emptyAgentState(projectId, threadId), ...data, project_id: projectId, thread_id: threadId },
    activeRunId,
  };
}
