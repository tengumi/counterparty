import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DecisionPanel } from './DecisionPanel';
import { ReturningState } from './ReturningState';
import { apiProjects } from '../../test/apiProjects';
import type { ApiUserDecision } from '../../api/decisions';

const project = apiProjects[0];
const saved: ApiUserDecision = {
  id: 'decision-1', project_id: project.id, outcome: 'ready_with_conditions',
  company_ids: ['company-a'], rationale: 'Подтверждение поставки получено',
  conditions: ['Аванс 30%'], based_on_artifact_id: null, based_on_artifact_version: null,
  context_version: 0, evidence_refs: [], author_user_id: 'user-1',
  created_at: '2026-09-05T10:00:00Z', supersedes_id: null,
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><DecisionPanel project={project} onOpenEvidence={vi.fn()} /></QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe('decision recording', () => {
  it('requires the user to select an outcome and conditions, then displays only the confirmed record', async () => {
    let records: ApiUserDecision[] = [];
    let submitted: unknown;
    vi.stubGlobal('fetch', async (url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        submitted = JSON.parse(String(init.body));
        records = [saved];
        return Response.json(saved, { status: 201 });
      }
      return Response.json(String(url).includes('/decisions') ? records : []);
    });
    const user = userEvent.setup();
    mount();
    await screen.findByText('Решение ещё не записано.');
    expect(screen.getAllByRole('radio').every((radio) => !(radio as HTMLInputElement).checked)).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Записать решение' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Выберите своё решение');
    await user.click(screen.getByRole('radio', { name: 'Готов при условиях' }));
    await user.type(screen.getByLabelText('Основание решения'), saved.rationale);
    await user.click(screen.getByRole('button', { name: 'Записать решение' }));
    expect(screen.getByRole('alert')).toHaveTextContent('хотя бы одно конкретное условие');
    expect(submitted).toBeUndefined();
    await user.type(screen.getByLabelText('Условия решения'), 'Аванс 30%');
    await user.click(screen.getByRole('button', { name: 'Записать решение' }));
    await screen.findByText(/Записано вами/);
    expect(submitted).toMatchObject({ outcome: 'ready_with_conditions', context_version: 0, conditions: ['Аванс 30%'] });
    expect(submitted).not.toHaveProperty('author_user_id');
  });

  it('preserves the form and never claims success after a server failure', async () => {
    vi.stubGlobal('fetch', async (_url: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST'
      ? Response.json({ code: 'conflict', message: 'Сведения изменились', retryable: false, request_id: 'r' }, { status: 409 })
      : Response.json([]));
    const user = userEvent.setup();
    mount();
    await screen.findByText('Решение ещё не записано.');
    await user.click(screen.getByRole('radio', { name: 'Готов работать' }));
    await user.type(screen.getByLabelText('Основание решения'), 'Моё основание');
    await user.click(screen.getByRole('button', { name: 'Записать решение' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Решение не записано'));
    expect(screen.getByLabelText('Основание решения')).toHaveValue('Моё основание');
    expect(screen.queryByText(/Записано вами/)).not.toBeInTheDocument();
  });

  it('retains an old decision and offers review when project context changes', () => {
    render(<ReturningState project={{ ...project, context_version: 2, latest_decision: saved }} onOpenSummary={vi.fn()} onContinue={vi.fn()} />);
    expect(screen.getByText(/Решение записано по сведениям версии 0; сейчас версия 2/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Пересмотреть решение' })).toBeVisible();
  });
});
