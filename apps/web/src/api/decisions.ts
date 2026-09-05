/**
 * The AI conclusion and the user's own decision (Specs 10 §4, §5).
 *
 * They are two separate versioned entities and never overwrite each other: the
 * artifact is what the assistant drafted for a given context version, the
 * decision is what the person recorded. Only the server writes a decision —
 * the browser sends the request and shows what came back.
 */

import { requestJson, WorkspaceApiError } from './client';

export type DecisionOutcome = 'ready' | 'ready_with_conditions' | 'not_ready' | 'need_more_info';

export type ArtifactFreshness = 'current' | 'outdated' | 'source_removed';

export interface ApiArtifactGround {
  readonly text: string;
  readonly refs: readonly string[];
}

export interface ApiAnalysisArtifact {
  readonly id: string;
  readonly version: number;
  readonly project_id: string;
  /** Project context the conclusion was drawn from; never rewritten later. */
  readonly based_on_context_version: number;
  readonly report_ids: readonly string[];
  readonly question: string;
  readonly summary: string;
  readonly grounds: readonly ApiArtifactGround[];
  readonly unknowns: readonly string[];
  readonly next_actions: readonly string[];
  readonly evidence_refs: readonly string[];
  readonly freshness: ArtifactFreshness;
  readonly created_by_run_id: string | null;
  readonly source_thread_id: string | null;
  readonly created_at: string;
}

export interface ApiUserDecision {
  readonly id: string;
  readonly project_id: string;
  readonly outcome: DecisionOutcome;
  readonly company_ids: readonly string[];
  readonly rationale: string;
  readonly conditions: readonly string[];
  readonly based_on_artifact_id: string | null;
  readonly based_on_artifact_version: number | null;
  readonly context_version: number;
  readonly evidence_refs: readonly string[];
  readonly author_user_id: string;
  readonly created_at: string;
  readonly supersedes_id: string | null;
}

export interface CreateDecisionRequest {
  readonly outcome: DecisionOutcome;
  readonly rationale: string;
  readonly conditions: readonly string[];
  readonly company_ids: readonly string[];
  readonly based_on_artifact_id?: string;
  readonly based_on_artifact_version?: number;
  readonly context_version: number;
  readonly evidence_refs?: readonly string[];
  readonly supersedes_id?: string;
}

export const decisionKeys = {
  decisions: (projectId: string) => ['workspace', 'projects', projectId, 'decisions'] as const,
  artifacts: (projectId: string) => ['workspace', 'projects', projectId, 'artifacts'] as const,
};

function items<T>(data: unknown): readonly T[] {
  if (Array.isArray(data)) return data as T[];
  if (typeof data === 'object' && data !== null && Array.isArray((data as { items?: unknown }).items)) {
    return (data as { items: T[] }).items;
  }
  throw new WorkspaceApiError(200, 'invalid_response', 'Сервис вернул данные в неизвестном формате.', true, null);
}

export async function listDecisions(projectId: string): Promise<readonly ApiUserDecision[]> {
  const { data } = await requestJson<unknown>(
    `/projects/${encodeURIComponent(projectId)}/decisions`,
  );
  return items<ApiUserDecision>(data);
}

export async function listLatestArtifacts(
  projectId: string,
): Promise<readonly ApiAnalysisArtifact[]> {
  const { data } = await requestJson<unknown>(
    `/projects/${encodeURIComponent(projectId)}/artifacts?latest=true`,
  );
  return items<ApiAnalysisArtifact>(data);
}

/** Record the decision. The server is the only writer; it returns the truth. */
export async function createDecision(
  projectId: string,
  body: CreateDecisionRequest,
): Promise<ApiUserDecision> {
  return (
    await requestJson<ApiUserDecision>(`/projects/${encodeURIComponent(projectId)}/decisions`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  ).data;
}
