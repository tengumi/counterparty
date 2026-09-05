import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import type { ApiProject } from '../../api/contracts';
import type { ComparisonInput, ProjectComparison } from '../../api/reportContracts';
import { liveProject, overview, zeroFact, missingFact, REF } from '../../test/reportFixtures';
import { Comparison } from './Comparison';

function projectWith(count: number): ApiProject {
  return {
    ...liveProject,
    companies: Array.from({ length: count }, (_, index) => ({
      ...liveProject.companies[0]!,
      company_id: `company-${index}`,
      report_id: `report-${index}`,
      short_name: `Участник ${index + 1}`,
    })),
  };
}
function responseFor(project: ApiProject, input: ComparisonInput): ProjectComparison {
  return {
    ...input,
    year: input.year ?? null,
    schema_version: '0.1',
    id: null,
    project_id: project.id,
    rows: input.report_ids.map((id, index) => ({
      company: {
        ...overview.company,
        id: project.companies[index]!.company_id,
        short_name: project.companies[index]!.short_name,
      },
      report: { ...overview.report, id },
      cells: [index === 0 ? { ...zeroFact, value: '91.25', period: 2023 } : missingFact],
      status: index === 0 ? 'complete' : 'partial',
      warnings: [],
    })),
    proposal_facts: [],
    warnings: [{ code: 'not_comparable', message: 'No common year' }],
    rule_version: 'comparison/1',
  };
}
function mount(project = liveProject) {
  const onEvidence = vi.fn();
  const onDiscuss = vi.fn();
  const view = render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <Comparison project={project} onEvidence={onEvidence} onDiscuss={onDiscuss} />
    </QueryClientProvider>,
  );
  return { ...view, onEvidence, onDiscuss };
}

describe('server comparison', () => {
  it('sends pinned reports, criteria and explicit year; displays server values and keeps discussion selection', async () => {
    let input: ComparisonInput | undefined;
    const fetch = vi.fn((_url: string, init: RequestInit) => {
      input = JSON.parse(String(init.body)) as ComparisonInput;
      return Promise.resolve(Response.json(responseFor(liveProject, input)));
    });
    vi.stubGlobal('fetch', fetch);
    const { onEvidence, onDiscuss } = mount();
    const user = userEvent.setup();
    expect(fetch).not.toHaveBeenCalled();
    for (const label of ['Риск банка', 'Статус', 'Взыскания'])
      await user.click(screen.getByRole('checkbox', { name: label }));
    await user.selectOptions(screen.getByLabelText('Финансовый период'), 'explicit');
    expect(screen.getByRole('button', { name: 'Сравнить выбранные (2)' })).toBeDisabled();
    await user.type(screen.getByLabelText('Год сравнения'), '2024');
    await user.click(screen.getByRole('button', { name: 'Сравнить выбранные (2)' }));
    expect(await screen.findByText('91,25 ₽')).toBeVisible();
    expect(screen.getByText('2023 год')).toBeVisible();
    expect(screen.getByText('В отчёте нет этих сведений')).toBeVisible();
    expect(
      screen.getByText('Сопоставимого финансового периода для всех компаний нет.'),
    ).toBeVisible();
    expect(input).toEqual({
      report_ids: liveProject.companies.map((company) => company.report_id),
      criteria: ['financials'],
      year_policy: 'explicit',
      year: 2024,
    });
    expect(fetch.mock.calls[0]?.[0]).toBe(`/api/v1/projects/${liveProject.id}/comparisons`);
    await user.click(screen.getByRole('button', { name: 'Основание: Поставщик из REST, Выручка' }));
    expect(onEvidence).toHaveBeenCalledWith(REF);
    await user.click(screen.getByRole('button', { name: 'Обсудить сравнение' }));
    expect(onDiscuss).toHaveBeenCalledWith({
      kind: 'comparison',
      label: 'Сравнение 2 компаний',
      selection: input,
    });
    expect(
      localStorage.getItem(`counterparty:comparison-result:${liveProject.id}`) ??
        Object.values(localStorage).join(''),
    ).toContain('financials');
  });
  it.each([2, 5, 20])(
    'keeps all %i selected reports and all server rows without clipping',
    async (count) => {
      const project = projectWith(count);
      const fetch = vi.fn((_url: string, init: RequestInit) =>
        Promise.resolve(
          Response.json(responseFor(project, JSON.parse(String(init.body)) as ComparisonInput)),
        ),
      );
      vi.stubGlobal('fetch', fetch);
      mount(project);
      await userEvent.click(screen.getByRole('button', { name: `Сравнить выбранные (${count})` }));
      const table = await screen.findByRole('table');
      expect(within(table).getAllByRole('row')).toHaveLength(count + 1);
      expect(JSON.parse(String(fetch.mock.calls[0]?.[1].body)).report_ids).toHaveLength(count);
    },
  );
  it.each([1, 21])('prevents submission outside the range: %i companies', (count) => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    mount(projectWith(count));
    expect(screen.getByRole('button', { name: `Сравнить выбранные (${count})` })).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('retries server errors and restores submitted settings on reload', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json(
          {
            code: 'dependency_unavailable',
            message: 'Unavailable',
            retryable: true,
            request_id: 'test',
            details: null,
          },
          { status: 503 },
        ),
      )
      .mockImplementation((_url: string, init: RequestInit) =>
        Promise.resolve(
          Response.json(responseFor(liveProject, JSON.parse(String(init.body)) as ComparisonInput)),
        ),
      );
    vi.stubGlobal('fetch', fetch);
    const first = mount();
    await userEvent.selectOptions(screen.getByLabelText('Финансовый период'), 'common_latest');
    await userEvent.click(screen.getByRole('button', { name: 'Сравнить выбранные (2)' }));
    expect(await screen.findByRole('alert')).toBeVisible();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }));
    expect(await screen.findByRole('table')).toBeVisible();
    first.unmount();
    mount();
    expect(screen.getByLabelText('Финансовый период')).toHaveValue('common_latest');
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
    expect(await screen.findByRole('table')).toBeVisible();
  });
});
