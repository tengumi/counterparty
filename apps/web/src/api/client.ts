import type {
  AddCompaniesResponse,
  ApiErrorBody,
  ApiProject,
  CreateProjectResult,
  Page,
  ProjectCompaniesResponse,
} from './contracts';
import { uiApiConfig } from './config';

export class WorkspaceApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryable: boolean,
    readonly details: Readonly<Record<string, unknown>> | null,
  ) {
    super(message);
    this.name = 'WorkspaceApiError';
  }
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${uiApiConfig.baseUrl}/api/v1${path}`, {
      ...init,
      credentials: 'include',
      headers: { 'content-type': 'application/json', ...init?.headers },
    });
  } catch {
    throw new WorkspaceApiError(
      0,
      'network_error',
      'Не удалось связаться с сервисом проверок. Сведения не загружены.',
      true,
      null,
    );
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<{ data: T; response: Response }> {
  const response = await request(path, init);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new WorkspaceApiError(
      response.status,
      'invalid_response',
      'Сервис вернул ответ в неизвестном формате. Сведения не загружены.',
      true,
      null,
    );
  }
  if (!response.ok) {
    const error = body as Partial<ApiErrorBody>;
    throw new WorkspaceApiError(
      response.status,
      typeof error.code === 'string' ? error.code : 'unknown_error',
      typeof error.message === 'string' ? error.message : 'Запрос не выполнен.',
      error.retryable === true,
      error.details && typeof error.details === 'object' ? error.details : null,
    );
  }
  return { data: body as T, response };
}

export async function listProjects(): Promise<readonly ApiProject[]> {
  const { data } = await json<Page<ApiProject>>('/projects?limit=100');
  return data.items;
}

export async function getProject(projectId: string): Promise<ApiProject> {
  return (await json<ApiProject>(`/projects/${encodeURIComponent(projectId)}`)).data;
}

export async function createProject(
  initialQuestion: string,
  clientRequestId: string,
): Promise<CreateProjectResult> {
  const { data, response } = await json<ApiProject>('/projects', {
    method: 'POST',
    body: JSON.stringify({ initial_question: initialQuestion, client_request_id: clientRequestId }),
  });
  return { project: data, replayed: response.headers.get('idempotent-replay') === 'true' };
}

export async function renameProject(projectId: string, title: string): Promise<ApiProject> {
  return (
    await json<ApiProject>(`/projects/${encodeURIComponent(projectId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    })
  ).data;
}

export async function addCompanies(
  projectId: string,
  inns: readonly string[],
  expectedContextVersion: number,
): Promise<AddCompaniesResponse> {
  return (
    await json<AddCompaniesResponse>(`/projects/${encodeURIComponent(projectId)}/companies`, {
      method: 'POST',
      body: JSON.stringify({
        items: inns.map((inn) => ({ inn })),
        expected_context_version: expectedContextVersion,
      }),
    })
  ).data;
}

export async function removeCompany(
  projectId: string,
  companyId: string,
  expectedContextVersion: number,
): Promise<ProjectCompaniesResponse> {
  return (
    await json<ProjectCompaniesResponse>(
      `/projects/${encodeURIComponent(projectId)}/companies/${encodeURIComponent(companyId)}`,
      { method: 'DELETE', body: JSON.stringify({ expected_context_version: expectedContextVersion }) },
    )
  ).data;
}
