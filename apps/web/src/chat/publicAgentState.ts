/**
 * Mirror of `PublicAgentState` (Specs 10 §7) as the Agent Service publishes it.
 *
 * The service streams this object through assistant-stream `update-state`
 * operations; nothing here is an assistant-ui type.
 */

export type RunStatus =
  | 'accepted'
  | 'running'
  | 'cancelling'
  | 'completed'
  | 'awaiting_input'
  | 'failed'
  | 'cancelled'
  | 'interrupted';

export type MessageStatus = 'pending' | 'streaming' | 'complete' | 'partial' | 'error';

export type ActivityKind =
  | 'reading_report'
  | 'reading_document'
  | 'comparing'
  | 'calculating'
  | 'updating_analysis'
  | 'skill_invocation';

export type PublicError = {
  code: string;
  message: string;
  retryable: boolean;
  request_id: string;
};

export type PublicRun = {
  id: string;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  error: PublicError | null;
};

export type PublicMessage = {
  id: string;
  role: 'user' | 'assistant' | 'system_notice';
  blocks: { type: 'text'; text: string }[];
  status: MessageStatus;
  created_at: string;
};

export type PublicActivity = {
  id: string;
  kind: ActivityKind;
  label: string;
  status: 'running' | 'completed' | 'failed';
  evidence_refs: string[];
  started_at: string | null;
  finished_at: string | null;
};

export type PublicAgentState = {
  schema_version: '0.1';
  project_id: string;
  thread_id: string;
  run: PublicRun | null;
  revision: number;
  messages: PublicMessage[];
  activities: PublicActivity[];
  pending_commands: string[];
  pending_questions: string[];
  artifact_refs: string[];
  context_version: number;
  save_status: 'unsaved' | 'saving' | 'saved';
};

export const TERMINAL_RUN_STATUSES: readonly RunStatus[] = [
  'completed',
  'failed',
  'cancelled',
  'interrupted',
  'awaiting_input',
];

export function emptyAgentState(projectId: string, threadId: string): PublicAgentState {
  return {
    schema_version: '0.1',
    project_id: projectId,
    thread_id: threadId,
    run: null,
    revision: 0,
    messages: [],
    activities: [],
    pending_commands: [],
    pending_questions: [],
    artifact_refs: [],
    context_version: 0,
    save_status: 'unsaved',
  };
}
