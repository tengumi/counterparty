import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { apiProjects } from '../test/setup';

const demo = apiProjects[0];

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
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ ...demo, title: 'Новый заголовок' })));
    openDemo();

    await user.click(screen.getByRole('button', { name: 'Переименовать проверку' }));
    const input = screen.getByRole('textbox', { name: 'Название проверки' });
    await user.clear(input);
    await user.type(input, 'Новый заголовок{Enter}');

    expect(await screen.findByTitle('Новый заголовок')).toBeVisible();
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0]?.[1]?.body))).toEqual({ title: 'Новый заголовок' });
  });

  it('shows added and unavailable rows from one partial batch', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
      schema_version: '0.1', project_id: demo.id, context_version: 1,
      companies: [...demo.companies, { ...demo.companies[0], company_id: 'company-b', report_id: 'report-b', inn: '7702070139', short_name: 'Компания Б' }],
      results: [
        { requested: { inn: '7702070139' }, outcome: 'added', company_id: 'company-b', report_id: 'report-b', error_code: null, message: null },
        { requested: { inn: '0000000000' }, outcome: 'not_found', company_id: null, report_id: null, error_code: 'not_found', message: 'not held' },
      ],
    })));
    openDemo();
    await user.click(screen.getByRole('button', { name: 'Материалы' }));
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
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
      code: 'limit_exceeded', message: 'too many', retryable: false, request_id: 'request',
      details: { limit: 20, in_project: 19, requested_new: 2 },
    }, { status: 409 })));
    openDemo();
    await user.click(screen.getByRole('button', { name: 'Материалы' }));
    const panel = screen.getByRole('complementary', { name: 'Материалы проверки' });
    await user.type(within(panel).getByRole('textbox', { name: 'ИНН компаний' }), '7702070139, 0000000000');
    await user.click(within(panel).getByRole('button', { name: 'Добавить компании' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Ни одна компания из этого списка не добавлена');
    expect(within(panel).getByRole('button', { name: /Компания А/ })).toBeVisible();
    expect(screen.queryByText('рисков нет')).not.toBeInTheDocument();
  });

  it('removes a company using the context version that was loaded', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
      schema_version: '0.1', project_id: demo.id, companies: [], context_version: 1,
    })));
    openDemo();
    await user.click(screen.getByRole('button', { name: 'Материалы' }));
    await user.click(screen.getByRole('button', { name: 'Удалить' }));

    expect(await screen.findByText('Компании не добавлены')).toBeVisible();
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0]?.[1]?.body))).toEqual({ expected_context_version: 0 });
  });
});
