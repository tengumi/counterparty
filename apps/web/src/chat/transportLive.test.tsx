/**
 * WEB-09: what the chat does when the agent is not simply answering.
 *
 * The three honest outcomes are checked separately — a service that never
 * accepted the message, a stream that broke over a run that may still be
 * working, and a stored conversation restored on open — together with the
 * regression that used to discard the live thread whenever the screen around
 * it re-rendered.
 */

import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentChat } from './AgentChat';
import { ProjectChat } from './ProjectChat';
import answerSse from './__fixtures__/answer.sse?raw';

const PROJECT_ID = '00000000-0000-4000-8000-000000000001';
const THREAD_ID = '00000000-0000-4000-8000-000000000002';
const RUN_ID = '00000000-0000-4000-8000-000000000004';

type Recorded = { url: string; body: Record<string, unknown> };

function sseStream(frames: readonly string[], { fail = false } = {}) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) {
        if (frame.trim() !== '') controller.enqueue(encoder.encode(`${frame}\n\n`));
      }
      if (fail) {
        // The drop has to arrive after the first frames were consumed, the way
        // a connection dies mid-run rather than before it started.
        setTimeout(() => controller.error(new TypeError('network error')), 20);
        return;
      }
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } });
}

const answerFrames = answerSse.split('\n\n');

function record(requests: Recorded[], url: RequestInfo | URL, init: RequestInit): Recorded {
  const entry: Recorded = { url: String(url), body: init.body ? JSON.parse(String(init.body)) : {} };
  requests.push(entry);
  return entry;
}

async function typeAndSend(text: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Сообщение помощнику'), text);
  await user.click(screen.getByRole('button', { name: 'Отправить' }));
  return user;
}

beforeEach(() => {
  vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => THREAD_ID });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('WEB-09 degradation of the live chat', () => {
  it('says the message was not delivered when the service refuses it', async () => {
    vi.stubGlobal('fetch', async () => new Response('no agent here', { status: 404 }));
    render(<AgentChat apiBase="http://agent.test" projectId={PROJECT_ID} threadId={THREAD_ID} />);
    await typeAndSend('Можно ли перечислять аванс?');

    const alert = await screen.findByTestId('connection-state');
    expect(alert).toHaveTextContent('Помощник сейчас не отвечает. Сообщение не отправлено.');
    expect(alert).toHaveTextContent('сведения компаний и сравнение открываются в материалах');
    // Nothing was invented in place of an answer, and no run is claimed.
    expect(screen.getByTestId('run-status')).toHaveTextContent('нет запуска');
  });

  it('offers a reconnect after a broken stream and never re-sends the message', async () => {
    const requests: Recorded[] = [];
    vi.stubGlobal('fetch', async (url: RequestInfo | URL, init: RequestInit = {}) => {
      const entry = record(requests, url, init);
      // The first two frames start the run; then the connection dies.
      if (entry.url.endsWith('/chat')) return sseStream(answerFrames.slice(0, 2), { fail: true });
      return sseStream(answerFrames);
    });
    render(<AgentChat apiBase="http://agent.test" projectId={PROJECT_ID} threadId={THREAD_ID} />);
    const user = await typeAndSend('Проверь отчёт');

    const notice = await screen.findByText(/Связь с помощником прервана/);
    expect(notice).toBeVisible();
    // The run is not relabelled as finished, failed or cancelled.
    expect(screen.queryByText('Ответ готов')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Подключиться заново' }));

    await waitFor(() =>
      expect(requests.map((request) => request.url)).toContain(
        `http://agent.test/rpc/agent/runs/${RUN_ID}/subscribe`,
      ),
    );
    const sends = requests.filter((request) => request.url.endsWith('/chat'));
    expect(sends).toHaveLength(1);
    const resume = requests.find((request) => request.url.endsWith('/subscribe'));
    expect(resume?.body.commands).toEqual([]);
  });

  it('keeps the live thread when the surface around it re-renders', async () => {
    vi.stubGlobal('fetch', async () => sseStream(answerFrames));
    function Surface() {
      const [draft, setDraft] = useState('');
      return (
        <AgentChat
          apiBase="http://agent.test"
          draft={draft}
          onDraftChange={setDraft}
          projectId={PROJECT_ID}
          threadId={THREAD_ID}
        />
      );
    }
    render(<Surface />);
    const user = await typeAndSend('Проверь отчёт');
    await waitFor(() => expect(screen.getByTestId('run-status')).toHaveTextContent('completed'));

    await user.type(screen.getByLabelText('Сообщение помощнику'), 'ещё вопрос');

    expect(screen.getByTestId('run-status')).toHaveTextContent('completed');
    expect(screen.getByText(/Аванс 80% от 2,4 млн ₽/)).toBeVisible();
  });
});

function renderProjectChat() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProjectChat
        draft=""
        layout={(feed, composer) => (
          <>
            {feed}
            {composer}
          </>
        )}
        onDraftChange={() => undefined}
        projectId={PROJECT_ID}
        threadId={THREAD_ID}
      />
    </QueryClientProvider>,
  );
}

describe('WEB-09 restore of a stored conversation', () => {
  it('re-attaches to an active run instead of sending the message again', async () => {
    const requests: Recorded[] = [];
    vi.stubGlobal('fetch', async (url: RequestInfo | URL, init: RequestInit = {}) => {
      const entry = record(requests, url, init);
      if (entry.url.includes('/conversation')) {
        return Response.json({
          schema_version: '0.1',
          project_id: PROJECT_ID,
          thread_id: THREAD_ID,
          run: null,
          revision: 3,
          messages: [
            {
              id: 'saved-1',
              role: 'user',
              blocks: [{ type: 'text', text: 'Что с капиталом?' }],
              status: 'complete',
              created_at: '2026-09-05T09:00:00Z',
            },
          ],
          activities: [],
          pending_commands: [],
          pending_questions: [],
          artifact_refs: [],
          context_version: 2,
          save_status: 'saved',
          active_run_id: RUN_ID,
        });
      }
      return sseStream(answerFrames);
    });

    renderProjectChat();

    expect(await screen.findByText('Что с капиталом?')).toBeVisible();
    await waitFor(() =>
      expect(requests.map((request) => request.url)).toContain(
        `/rpc/agent/runs/${RUN_ID}/subscribe`,
      ),
    );
    expect(requests.filter((request) => request.url.endsWith('/chat'))).toHaveLength(0);
  });

  it('does not turn a service that cannot restore into an empty conversation', async () => {
    vi.stubGlobal('fetch', async (url: RequestInfo | URL) =>
      String(url).includes('/conversation')
        ? Response.json(
            { code: 'not_found', message: 'нет такого', retryable: false, request_id: 'r', details: null },
            { status: 404 },
          )
        : sseStream(answerFrames),
    );

    renderProjectChat();

    const notice = await screen.findByText(/Сохранённая история этого чата пока недоступна/);
    expect(notice).toBeVisible();
    expect(screen.queryByText('Сообщений пока нет.')).not.toBeInTheDocument();
    // The chat still accepts a new message.
    expect(screen.getByLabelText('Сообщение помощнику')).toBeEnabled();
  });
});
