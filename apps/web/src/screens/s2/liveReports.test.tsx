import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { CheckPage } from '../../pages/CheckPage';
import { WorkspaceQueryProvider } from '../../api/QueryProvider';
import { reportKeys } from '../../api/reports';
import {
  liveProject,
  PROJECT_ID,
  REPORT_ID,
  REF,
  overview,
  financeSection,
  zeroFact,
} from '../../test/reportFixtures';
import { LiveCompanyReport } from './LiveCompanyReport';
import { LiveEvidence } from './LiveEvidence';
import { factText, formatDecimal, fragmentRows } from './liveReportView';

function notImplemented() {
  return Response.json(
    { code: 'not_found', message: 'not implemented', retryable: false, request_id: 'test', details: null },
    { status: 404 },
  );
}
function errorResponse() {
  return Response.json(
    {
      code: 'dependency_unavailable',
      message: 'Источник временно недоступен',
      retryable: true,
      request_id: 'test',
      details: null,
    },
    { status: 503 },
  );
}
function sourceFetch(input: RequestInfo | URL): Promise<Response> {
  const url = new URL(String(input), 'http://localhost');
  // The stored conversation endpoint is not implemented yet; the chat degrades.
  if (url.pathname.endsWith('/conversation')) return Promise.resolve(notImplemented());
  if (url.pathname.endsWith('/overview')) return Promise.resolve(Response.json(overview));
  if (url.pathname.includes('/evidence/'))
    return Promise.resolve(
      Response.json({
        schema_version: '0.1',
        evidence: {
          id: REF,
          kind: 'report_field',
          report_id: REPORT_ID,
          company_id: overview.company.id,
          source_path: '/finReports/0/common/proceeds',
          period: null,
        },
        report: overview.report,
        availability: 'available',
        value: 0,
        warnings: [],
      }),
    );
  const section = url.pathname.split('/').at(-1);
  if (section === 'financials')
    return Promise.resolve(
      Response.json(
        url.searchParams.has('cursor')
          ? {
              ...financeSection,
              records: [],
              facts: [
                {
                  ...zeroFact,
                  key: 'more',
                  label: 'Дополнительный показатель',
                  value: '9007199254740993.25',
                },
              ],
              page: { limit: 20, next_cursor: null, has_more: false },
            }
          : financeSection,
      ),
    );
  return Promise.resolve(
    Response.json({
      ...financeSection,
      section,
      availability: 'missing',
      records: [],
      facts: [],
      total_records: null,
      page: { limit: 20, next_cursor: null, has_more: false },
    }),
  );
}
function openLiveProject() {
  return render(
    <MemoryRouter initialEntries={[`/checks/${PROJECT_ID}`]}>
      <WorkspaceQueryProvider initialProjects={[liveProject]}>
        <Routes>
          <Route path="/checks/:projectId" element={<CheckPage />} />
        </Routes>
      </WorkspaceQueryProvider>
    </MemoryRouter>,
  );
}
function panel() {
  return screen.getByRole('complementary', { name: 'Материалы проверки' });
}

describe('live report material binding', () => {
  it('keeps exact decimals, null and unavailable states distinct', () => {
    expect(formatDecimal('9007199254740993.25', 'RUB')).toBe('9 007 199 254 740 993,25 ₽');
    expect(factText(zeroFact)).toBe('0 ₽');
    expect(factText({ ...zeroFact, availability: 'missing', value: null })).toBe(
      'В отчёте нет этих сведений',
    );
    expect(factText({ ...zeroFact, availability: 'present_empty', value: null })).toBe(
      'Источник содержит пустое значение',
    );
    expect(factText({ ...zeroFact, availability: 'invalid', value: null })).toBe(
      'Сведения не удалось прочитать',
    );
    expect(factText({ ...zeroFact, availability: 'restricted', value: null })).toBe(
      'Эти сведения недоступны',
    );
    expect(factText({ ...zeroFact, evidence_refs: [] })).toContain('основание недоступно');
    expect(fragmentRows({ issueDate: { $date: '2026-01-01T21:00:00Z' } }, 'Лицензия')).toEqual([
      { label: 'Лицензия · Дата выдачи', value: '2026-01-01T21:00:00Z' },
    ]);
  });
  it('scopes immutable reports, evidence and comparison by project and snapshot', () => {
    expect(reportKeys.overview('one', REPORT_ID)).not.toEqual(
      reportKeys.overview('two', REPORT_ID),
    );
    expect(reportKeys.section('one', REPORT_ID, 'financials')).not.toEqual(
      reportKeys.section('one', 'other-report', 'financials'),
    );
    expect(reportKeys.evidence('one', REF)).not.toEqual(reportKeys.evidence('two', REF));
    const selection = {
      report_ids: [REPORT_ID],
      criteria: ['financials'] as const,
      year_policy: 'latest_available' as const,
    };
    expect(reportKeys.comparison('one', 1, selection)).not.toEqual(
      reportKeys.comparison('one', 2, selection),
    );
  });
  it('loads pinned report pages and returns from authorized evidence without losing draft', async () => {
    const fetch = vi.fn(sourceFetch);
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    openLiveProject();
    const draft = screen.getByLabelText('Сообщение помощнику');
    await user.type(draft, 'Проверить аванс');
    expect(screen.queryByText('Остановились на…')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Поставщик из REST' }));
    await user.click(await within(panel()).findByRole('button', { name: /Финансы/ }));
    expect(await within(panel()).findByText('0 ₽')).toBeVisible();
    expect(within(panel()).getAllByText(/В отчёте нет этих сведений/).length).toBeGreaterThan(0);
    await user.click(within(panel()).getByRole('button', { name: 'Показать ещё записи' }));
    expect(await within(panel()).findByText('9 007 199 254 740 993,25 ₽')).toBeVisible();
    await user.click(within(panel()).getByRole('button', { name: 'Основание: Выручка' }));
    expect(await within(panel()).findByText('2025')).toBeVisible();
    expect(within(panel()).getByLabelText('Исходный фрагмент')).toHaveTextContent('0');
    expect(fetch.mock.calls.some(([url]) => String(url).includes(encodeURIComponent(REF)))).toBe(
      true,
    );
    await user.click(within(panel()).getByRole('button', { name: 'К отчёту' }));
    expect(await within(panel()).findByText('0 ₽')).toBeVisible();
    expect(draft).toHaveValue('Проверить аванс');
    await user.click(within(panel()).getByRole('button', { name: 'Обсудить: Выручка' }));
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Материалы в черновике')).toHaveTextContent('Выручка');
    expect(draft).toHaveValue('Проверить аванс');
    // The composer is live now: a non-empty draft can be sent to the agent.
    expect(screen.getByRole('button', { name: 'Отправить' })).toBeEnabled();
    expect(Object.values(localStorage).join('')).toContain(REF);
  });
  it('shows loading, retains honest errors, and retries without a mock fallback', async () => {
    let answer: ((response: Response) => void) | undefined;
    const fetch = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            answer = resolve;
          }),
      )
      .mockImplementation(sourceFetch);
    vi.stubGlobal('fetch', fetch);
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <LiveCompanyReport
          projectId={PROJECT_ID}
          reportId={REPORT_ID}
          onEvidence={vi.fn()}
          onDiscuss={vi.fn()}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Загружаем сведения');
    answer?.(errorResponse());
    expect(await screen.findByRole('alert')).toHaveTextContent('не означает отсутствие риска');
    expect(screen.queryByText('0 ₽')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }));
    await waitFor(() => expect(screen.getByText(/Риск по оценке банка — LOW/)).toBeVisible());
    expect(screen.getByText(/ЗСК — YELLOW/)).toBeVisible();
  });
  it('does not invent documents, deal terms or saved conclusions for UUID projects', async () => {
    vi.stubGlobal('fetch', vi.fn(sourceFetch));
    const user = userEvent.setup();
    openLiveProject();
    await user.click(screen.getByRole('button', { name: 'Материалы' }));
    await user.click(within(panel()).getByRole('button', { name: /Условия/ }));
    expect(
      within(panel()).getByText('Запись и загрузка условий сделки пока недоступны.'),
    ).toBeVisible();
    await user.click(within(panel()).getByRole('button', { name: /Документы/ }));
    expect(
      within(panel()).getByText('Загрузка и просмотр документов пока недоступны.'),
    ).toBeVisible();
    expect(screen.queryByText('Предложение-А.pdf')).not.toBeInTheDocument();
  });
  it('retains the first page when the next page fails and retries the same cursor', async () => {
    let failed = false;
    const fetch = vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes('cursor=next-finance') && !failed) {
        failed = true;
        return Promise.resolve(errorResponse());
      }
      return sourceFetch(input);
    });
    vi.stubGlobal('fetch', fetch);
    openLiveProject();
    await userEvent.click(screen.getByRole('button', { name: 'Поставщик из REST' }));
    await userEvent.click(await within(panel()).findByRole('button', { name: /Финансы/ }));
    expect(await within(panel()).findByText('0 ₽')).toBeVisible();
    await userEvent.click(within(panel()).getByRole('button', { name: 'Показать ещё записи' }));
    expect(await within(panel()).findByRole('alert')).toBeVisible();
    expect(within(panel()).getByText('0 ₽')).toBeVisible();
    await userEvent.click(within(panel()).getByRole('button', { name: 'Повторить загрузку' }));
    expect(await within(panel()).findByText('9 007 199 254 740 993,25 ₽')).toBeVisible();
    expect(
      fetch.mock.calls.filter(([url]) => String(url).includes('cursor=next-finance')),
    ).toHaveLength(2);
  });
  it('does not turn a missing source or unknown fact period into an empty value or snapshot year', async () => {
    const ref = `report:${REPORT_ID}:/finReports/7/common/profit`;
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        String(input).includes('/evidence/')
          ? Promise.resolve(
              Response.json({
                schema_version: '0.1',
                evidence: {
                  id: ref,
                  kind: 'report_field',
                  report_id: REPORT_ID,
                  company_id: overview.company.id,
                  source_path: '/finReports/7/common/profit',
                  period: null,
                },
                report: overview.report,
                availability: 'missing',
                value: null,
                warnings: [],
              }),
            )
          : sourceFetch(input),
      ),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <LiveEvidence projectId={PROJECT_ID} evidenceRef={ref} onDiscuss={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Не указан в основании')).toBeVisible();
    expect(screen.getByText(/В отчёте нет этих сведений/)).toBeVisible();
    expect(screen.queryByText('Пустое значение в источнике')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Исходный фрагмент')).toBeEmptyDOMElement();
  });
  it('prefers the period supplied by the evidence resolver over overview metadata', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        String(input).includes('/evidence/')
          ? Promise.resolve(
              Response.json({
                schema_version: '0.1',
                evidence: {
                  id: REF,
                  kind: 'report_field',
                  report_id: REPORT_ID,
                  company_id: overview.company.id,
                  source_path: '/finReports/0/common/proceeds',
                  period: 2021,
                },
                report: overview.report,
                availability: 'available',
                value: 0,
                warnings: [],
              }),
            )
          : sourceFetch(input),
      ),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <LiveEvidence projectId={PROJECT_ID} evidenceRef={REF} onDiscuss={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('2021')).toBeVisible();
    expect(screen.queryByText('2025')).not.toBeInTheDocument();
  });
});
