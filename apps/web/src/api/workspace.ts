import type { ApiProject, ApiProjectCompany, ProjectCompaniesResponse } from './contracts';
import type { ChatSummary, CompanyRef, ProjectDetail, ProjectStatus, ProjectSummary } from '../mocks/types';
import { findProject } from '../mocks/workspace';

const statusMap: Readonly<Record<ApiProject['workflow_status'], ProjectStatus>> = {
  in_progress: 'in_progress',
  needs_information: 'needs_input',
  decision_recorded: 'decision_recorded',
};

function companyView(company: ApiProjectCompany): CompanyRef {
  return { id: company.company_id, name: company.short_name, inn: company.inn };
}

function activityLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return 'Дата недоступна';
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' }).format(date);
}

export function projectSummary(project: ApiProject): ProjectSummary {
  return {
    id: project.id,
    title: project.title,
    status: statusMap[project.workflow_status],
    continuation: project.last_open_question,
    lastActivityLabel: activityLabel(project.updated_at),
    lastActivityAt: project.updated_at,
    lastThreadId: project.default_thread_id,
  };
}

export function projectDetail(project: ApiProject): ProjectDetail {
  const mock = findProject(project.id);
  const defaultChat: ChatSummary = {
    id: project.default_thread_id,
    title: project.title,
    hint: 'Сообщения загрузятся после подключения API чатов',
    status: 'ready',
  };
  return {
    ...projectSummary(project),
    companies: project.companies.map(companyView),
    chats: mock?.chats ?? [defaultChat],
    saveState: 'saved',
    isDemo: mock?.isDemo ?? false,
  };
}

export function withCompanies(project: ApiProject, response: ProjectCompaniesResponse): ApiProject {
  return { ...project, companies: response.companies, context_version: response.context_version };
}

export const workspaceKeys = {
  all: ['workspace', 'projects'] as const,
  project: (projectId: string) => ['workspace', 'projects', projectId] as const,
};
