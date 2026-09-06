import type { ApiUserDecision, ArtifactFreshness } from './decisions';

export type WorkflowStatus = 'in_progress' | 'needs_information' | 'decision_recorded';

export interface ApiProjectCompany {
  readonly company_id: string;
  readonly report_id: string;
  readonly inn: string;
  readonly short_name: string;
  readonly role: 'supplier' | 'buyer' | 'contractor' | 'other' | 'unknown';
  readonly shortlisted: boolean;
  readonly added_at: string;
}

/** Compact reference to the latest AI conclusion of a project (Specs 10 §4). */
export interface ApiArtifactPreview {
  readonly artifact_id: string;
  readonly version: number;
  readonly title: string;
  readonly source_thread_id: string;
  readonly created_at: string;
  readonly freshness: ArtifactFreshness;
  readonly available: boolean;
}

export interface ApiProject {
  readonly schema_version: string;
  readonly id: string;
  readonly title: string;
  readonly default_thread_id: string;
  readonly threads_count: number;
  readonly context_version: number;
  readonly workflow_status: WorkflowStatus;
  readonly companies: readonly ApiProjectCompany[];
  readonly last_open_question: string | null;
  /** The AI conclusion and the recorded decision are separate entities. */
  readonly latest_artifact?: ApiArtifactPreview | null;
  readonly latest_decision?: ApiUserDecision | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface Page<T> {
  readonly schema_version: string;
  readonly items: readonly T[];
  readonly page: {
    readonly limit: number;
    readonly next_cursor: string | null;
    readonly has_more: boolean;
  };
}

export type CompanyAddOutcome = 'added' | 'already_present' | 'not_found' | 'invalid';

export interface AddCompanyResult {
  readonly requested: { readonly inn?: string; readonly company_id?: string };
  readonly outcome: CompanyAddOutcome;
  readonly company_id: string | null;
  readonly report_id: string | null;
  readonly error_code: string | null;
  readonly message: string | null;
}

export interface ProjectCompaniesResponse {
  readonly schema_version: string;
  readonly project_id: string;
  readonly companies: readonly ApiProjectCompany[];
  readonly context_version: number;
}

export interface AddCompaniesResponse extends ProjectCompaniesResponse {
  readonly results: readonly AddCompanyResult[];
}

export interface ApiErrorBody {
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly request_id: string;
  readonly details: Readonly<Record<string, unknown>> | null;
}

export interface CreateProjectResult {
  readonly project: ApiProject;
  readonly replayed: boolean;
}
