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
          <Route element={<CheckPage />} path="/checks/:projectId" />
          <Route element={<CheckPage />} path="/checks/:projectId/chats/:threadId" />
        </Routes>
      </WorkspaceQueryProvider>
    </MemoryRouter>,
  );
}

function path() {
  return screen.getByTestId('path').textContent;
}

describe('S2 header and chat switcher', () => {
  it('switches chats inside the same project without mixing their history', async () => {
    const user = userEvent.setup();
    openCheck('/checks/demo-project/chats/demo-thread');

    expect(screen.getByText('Остановились на…')).toBeVisible();
    expect(screen.getByLabelText('Сообщение помощнику')).toBeVisible();

    await user.click(screen.getByRole('button', { name: /Чат: Поставка/ }));
    expect(screen.getByText('Работает')).toBeVisible();
    await user.click(screen.getByRole('button', { name: /Условия оплаты/ }));

    expect(path()).toBe('/checks/demo-project/chats/terms-thread');
    expect(screen.getByText('Сопоставляю условия оплаты и финансовые сведения')).toBeVisible();
    // The other chat's saved conversation must not bleed into this one.
    expect(screen.queryByText('Остановились на…')).not.toBeInTheDocument();
  });

  it('creates a new chat inside the same project, not a new check', async () => {
    const user = userEvent.setup();
    openCheck('/checks/demo-project/chats/demo-thread');

    await user.click(screen.getByRole('button', { name: /Чат: Поставка/ }));
    await user.click(screen.getByRole('button', { name: 'Новый чат' }));

    expect(path()).toBe('/checks/demo-project/chats/local-chat-1');
    expect(screen.getByText('Сообщений пока нет.')).toBeVisible();
    expect(screen.getByTitle('Поставка оборудования к 20 сентября')).toBeVisible();

    await user.click(screen.getByRole('button', { name: /Чат: Новый чат 1/ }));
    expect(screen.getByRole('button', { name: /Поставка/ })).toBeVisible();
  });

  it('closes the chat list on Escape and returns focus to its trigger', async () => {
    const user = userEvent.setup();
    openCheck('/checks/demo-project/chats/demo-thread');

    const trigger = screen.getByRole('button', { name: /Чат: Поставка/ });
    await user.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await user.keyboard('{Escape}');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();
  });

  it('shows the confirmed save state only', () => {
    openCheck('/checks/demo-project/chats/demo-thread');
    expect(screen.getByText('Сохранено')).toBeVisible();
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
