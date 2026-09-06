import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { apiProjects } from '../test/setup';

const demo = apiProjects[0];

/**
 * Route the mutation answer, but not the chat restore.
 *
 * S2 now also reads the stored conversation of the open thread; that endpoint
 * is not implemented yet, and answering it with a project body would be a lie
 * the screen would then have to render.
 */
function stubApi(answer: () => Response) {
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname.endsWith('/conversation')) {
      return Promise.resolve(
        Response.json(
          { code: 'not_found', message: 'not implemented', retryable: false, request_id: 'test', details: null },
          { status: 404 },
        ),
      );
    }
    void init;
    return Promise.resolve(answer());
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

/** Body of the first request that changed something. */
function mutationBody(mock: ReturnType<typeof stubApi>): unknown {
  const call = mock.mock.calls.find(([, init]) => init?.method !== undefined && init.method !== 'GET');
  return JSON.parse(String(call?.[1]?.body));
}

function openDemo() {
  return render(
    <MemoryRouter initialEntries={['/checks/demo-project/chats/demo-thread']}>
      <App initialProjects={apiProjects} />
    </MemoryRouter>,
  );
}

describe('live workspace mutations', () => {
  it('renames the project only after the server confirms it', async () => {
    const user = userEvent.setup();
    const mock = stubApi(() => Response.json({ ...demo, title: 'Новый заголовок' }));
    openDemo();

    await user.click(screen.getByRole('button', { name: 'Переименовать проверку' }));
    const input = screen.getByRole('textbox', { name: 'Название проверки' });
    await user.clear(input);
    await user.type(input, 'Новый заголовок{Enter}');

    expect(await within(screen.getByRole('main')).findByTitle('Новый заголовок')).toBeVisible();
    expect(mutationBody(mock)).toEqual({ title: 'Новый заголовок' });
  });

  it('shows added and unavailable rows from one partial batch', async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json({
      schema_version: '0.1', project_id: demo.id, context_version: 1,
      companies: [...demo.companies, { ...demo.companies[0], company_id: 'company-b', report_id: 'report-b', inn: '7702070139', short_name: 'Компания Б' }],
      results: [
        { requested: { inn: '7702070139' }, outcome: 'added', company_id: 'company-b', report_id: 'report-b', error_code: null, message: null },
        { requested: { inn: '0000000000' }, outcome: 'not_found', company_id: null, report_id: null, error_code: 'not_found', message: 'not held' },
      ],
    }));
    openDemo();
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    const panel = screen.getByRole('complementary', { name: 'Материалы проверки' });
    await user.type(within(panel).getByRole('textbox', { name: 'ИНН компаний' }), '7702070139, 0000000000');
    await user.click(within(panel).getByRole('button', { name: 'Добавить компании' }));

    const outcomes = await screen.findByRole('list', { name: 'Результат добавления' });
    expect(outcomes).toHaveTextContent('7702070139: добавлена');
    expect(outcomes).toHaveTextContent('0000000000: нет в доступной базе');
    expect(screen.getByRole('button', { name: 'Сравнить' })).toBeVisible();
  });

  it('keeps the current composition visible after an atomic company-limit refusal', async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json({
      code: 'limit_exceeded', message: 'too many', retryable: false, request_id: 'request',
      details: { limit: 20, in_project: 19, requested_new: 2 },
    }, { status: 409 }));
    openDemo();
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    const panel = screen.getByRole('complementary', { name: 'Материалы проверки' });
    await user.type(within(panel).getByRole('textbox', { name: 'ИНН компаний' }), '7702070139, 0000000000');
    await user.click(within(panel).getByRole('button', { name: 'Добавить компании' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Ни одна компания из этого списка не добавлена');
    expect(within(panel).getByRole('button', { name: /Компания А/ })).toBeVisible();
    expect(screen.queryByText('рисков нет')).not.toBeInTheDocument();
  });

  it('removes a company using the context version that was loaded', async () => {
    const user = userEvent.setup();
    const mock = stubApi(() => Response.json({
      schema_version: '0.1', project_id: demo.id, companies: [], context_version: 1,
    }));
    openDemo();
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    await user.click(screen.getByRole('button', { name: 'Удалить' }));

    expect(await screen.findByText('Компании не добавлены')).toBeVisible();
    expect(mutationBody(mock)).toEqual({ expected_context_version: 0 });
  });
});
