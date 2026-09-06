import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { CheckPage } from '../../pages/CheckPage';
import { ChecksPage } from '../../pages/ChecksPage';
import { WorkspaceQueryProvider } from '../../api/QueryProvider';
import { apiProjects } from '../../test/setup';

function CurrentPath() {
  const location = useLocation();
  return <span data-testid="path">{location.pathname}</span>;
}

function openCheck(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <WorkspaceQueryProvider initialProjects={apiProjects}>
        <CurrentPath />
        <Routes>
          <Route element={<ChecksPage />} path="/checks" />
          <Route element={<CheckPage fixtureMode />} path="/checks/:projectId" />
          <Route element={<CheckPage fixtureMode />} path="/checks/:projectId/chats/:threadId" />
        </Routes>
      </WorkspaceQueryProvider>
    </MemoryRouter>,
  );
}

function path() {
  return screen.getByTestId('path').textContent;
}

describe('Шапка S2', () => {
  it('оставляет название без переключателя и служебных подписей', () => {
    openCheck('/checks/demo-project/chats/demo-thread');
    expect(screen.getByRole('button', { name: 'Переименовать проверку' })).toBeVisible();
    expect(screen.queryByRole('button', { name: /Чат проверки|Чат:/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Сохранено')).not.toBeInTheDocument();
    expect(screen.queryByText('В работе')).not.toBeInTheDocument();
    expect(screen.queryByText('Не удалось сохранить')).not.toBeInTheDocument();
  });
});

describe('S2 company context strip', () => {
  it('keeps a long company name on one line and offers comparison from two companies', () => {
    openCheck('/checks/logistics-project');
    const longName =
      'Общество с ограниченной ответственностью «Специализированная транспортно-логистическая компания Урал-Восток-Транзит»';

    expect(screen.getByRole('button', { name: longName })).toHaveAttribute('title', longName);
    expect(screen.getByText('ещё 1')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Сравнить' })).toBeVisible();
    expect(screen.getByText('Решение записано')).toBeVisible();
  });

  it('hides comparison for a single company and marks only the demo project', () => {
    openCheck('/checks/inn-project');
    expect(screen.queryByRole('button', { name: 'Сравнить' })).not.toBeInTheDocument();
    expect(screen.queryByText('Учебный пример')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeEnabled();
  });

  it('opens the materials panel from the company line and closes it again', async () => {
    const user = userEvent.setup();
    openCheck('/checks/demo-project/chats/demo-thread');

    expect(screen.queryByRole('complementary', { name: 'Материалы проверки' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    const panel = screen.getByRole('complementary', { name: 'Материалы проверки' });
    expect(panel).toBeVisible();
    expect(screen.getByRole('heading', { name: /Условия/ })).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Назад к разговору — закрыть материалы' }));
    expect(screen.queryByRole('complementary', { name: 'Материалы проверки' })).not.toBeInTheDocument();
  });
});

describe('S1 to S2 handoff', () => {
  it('carries the typed task into S2 as an unsent draft', async () => {
    const user = userEvent.setup();
    openCheck('/checks');

    await user.type(screen.getByLabelText('Задача проверки'), 'Проверьте ИНН 7714497158');
    await user.click(screen.getByRole('button', { name: 'Отправить' }));

    await waitFor(() => expect(path()).toBe('/checks/demo-project/chats/demo-thread'));
    expect(screen.getByLabelText('Сообщение помощнику')).toHaveValue('Проверьте ИНН 7714497158');
    expect(screen.getByText(/ещё не отправлен и не сохранён/)).toBeVisible();
  });
});
