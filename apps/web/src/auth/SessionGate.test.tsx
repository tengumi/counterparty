import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkspaceApiError } from '../api/client';
import { SessionGate } from './SessionGate';

afterEach(() => vi.unstubAllGlobals());
const user = { login: 'demo-analyst', display_name: 'Демо-аналитик' };
const denied = () => new Response(JSON.stringify({ code: 'unauthorized' }), { status: 401 });
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><SessionGate><input aria-label="Черновик" /></SessionGate></QueryClientProvider>);
  return client;
}

it('requires explicit demo login and retries a failed login without opening the workspace', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(denied())
    .mockResolvedValueOnce(new Response('{}', { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(user)));
  vi.stubGlobal('fetch', fetcher);
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Войти в демо' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось открыть сессию');
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Войти в демо' }));
  expect(await screen.findByRole('textbox')).toBeVisible();
  expect(fetcher.mock.calls[2]?.[1]).toMatchObject({ credentials: 'include', method: 'POST', body: JSON.stringify({ login: 'demo-analyst' }) });
});

it('restores an existing session and preserves an unsent draft across expiry and reauthentication', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(user)))));
  const client = mount();
  const input = await screen.findByRole('textbox');
  fireEvent.change(input, { target: { value: 'Несохранённый вопрос' } });
  await act(async () => {
    await client.fetchQuery({ queryKey: ['protected'], queryFn: () => { throw new WorkspaceApiError(401, 'unauthorized', 'expired', false, null); } }).catch(() => undefined);
  });
  expect(await screen.findByRole('button', { name: 'Войти в демо' })).toBeVisible();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Войти в демо' }));
  await waitFor(() => expect(screen.getByRole('textbox')).toHaveValue('Несохранённый вопрос'));
});
