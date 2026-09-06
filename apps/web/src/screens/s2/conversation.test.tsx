/**
 * WEB-04: what breaks first in the conversation — an empty chat, a long answer
 * with its bases, the composer states and a draft that survives a remount.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { CheckPage } from '../../pages/CheckPage';
import { WorkspaceQueryProvider } from '../../api/QueryProvider';
import { apiProjects } from '../../test/setup';

function openChat(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <WorkspaceQueryProvider initialProjects={apiProjects}>
        <Routes>
          <Route element={<CheckPage fixtureMode />} path="/checks/:projectId" />
          <Route element={<CheckPage fixtureMode />} path="/checks/:projectId/chats/:threadId" />
        </Routes>
      </WorkspaceQueryProvider>
    </MemoryRouter>,
  );
}

const DEMO = '/checks/demo-project/chats/demo-thread';
const EMPTY = '/checks/inn-project/chats/inn-thread';

describe('S2 conversation', () => {
  it('says a chat is empty instead of pretending it has history', () => {
    openChat(EMPTY);

    expect(screen.getByText('Сообщений пока нет.')).toBeVisible();
    expect(screen.getByLabelText('Сообщение помощнику')).toBeVisible();
    expect(screen.getByText(/Помощник пока недоступен/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Отправить' })).toBeDisabled();
  });

  it('shows a long answer with its numbered bases and opens one in the panel', async () => {
    const user = userEvent.setup();
    openChat(DEMO);

    expect(screen.getByText(/Аванс 80% от 2 400 000 ₽/)).toBeVisible();
    expect(screen.getByText(/Капитал и резервы за 2025 год — −300 000 ₽/)).toBeVisible();

    await user.click(
      screen.getByRole('button', { name: 'Основание 1: Капитал и резервы, 2025' }),
    );

    const panel = screen.getByRole('complementary', { name: 'Материалы проверки' });
    expect(panel).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Основание 1' })).toBeVisible();
    expect(screen.getByText('−300 000 ₽')).toBeVisible();
    expect(screen.getByText('Предоставленный отчёт, раздел «Финансы»')).toBeVisible();
    expect(screen.getByText('5 августа 2026')).toBeVisible();
  });

  it('opens the completed steps on request and never shows them by default', async () => {
    const user = userEvent.setup();
    openChat(DEMO);

    const toggle = screen.getAllByRole('button', { name: 'Что проверено' })[0]!;
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('Прочитал финансовые сведения')).not.toBeVisible();

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    // Assert inside the list this very button owns, not anywhere on the screen.
    const listId = toggle.getAttribute('aria-controls')!;
    const steps = within(document.getElementById(listId)!).getAllByRole('listitem');
    expect(steps).toHaveLength(3);
    expect(steps[0]!).toBeVisible();
    expect(steps[0]!).toHaveTextContent('Прочитал финансовые сведения');
    // Every step names where it looked; a step without a source is a bug.
    expect(steps[0]!).toHaveTextContent('Отчёт · срез 5 августа 2026');
    expect(steps[1]!).toHaveTextContent('Сопоставил аванс с капиталом компании');
    expect(steps[1]!).toHaveTextContent('Условия проверки');
    expect(steps[2]!).toHaveTextContent('Проверил исполнительные производства');
    expect(steps[2]!).toHaveTextContent('Отчёт · срез 5 августа 2026');
  });

  it('shows the running check building its step list in place', () => {
    openChat('/checks/demo-project/chats/terms-thread');

    // While it works the current line is shown and the steps are visible
    // without a toggle, so the user watches the trail grow.
    expect(screen.getByText('Сопоставляю условия оплаты и финансовые сведения')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Что проверено' })).not.toBeInTheDocument();

    const trail = screen.getByRole('region', { name: 'Ход проверки' });
    const steps = within(trail).getAllByRole('listitem');
    expect(steps.map((step) => step.textContent)).toEqual(
      expect.arrayContaining([
        expect.stringContaining('Прочитал условия проверки'),
        expect.stringContaining('Читаю финансовые сведения'),
      ]),
    );
  });

  it('offers a short answer as an editable draft and never sends it by itself', async () => {
    const user = userEvent.setup();
    openChat(DEMO);

    await user.click(screen.getByRole('button', { name: 'Аванс' }));

    expect(screen.getByLabelText('Сообщение помощнику')).toHaveValue('Оплата авансом');
    expect(screen.getByRole('button', { name: 'Отправить' })).toBeEnabled();
    // Nothing left the screen: the answer options only fill the composer.
    expect(screen.queryByRole('button', { name: 'Остановить' })).not.toBeInTheDocument();
  });

  it('keeps a typed draft after the chat is remounted', async () => {
    const user = userEvent.setup();
    const first = openChat(DEMO);

    await user.type(screen.getByLabelText('Сообщение помощнику'), 'Уточню срок поставки');
    first.unmount();

    openChat(DEMO);
    expect(screen.getByLabelText('Сообщение помощнику')).toHaveValue('Уточню срок поставки');
  });

  it('keeps the drafts of two chats apart', async () => {
    const user = userEvent.setup();
    const first = openChat(DEMO);
    await user.type(screen.getByLabelText('Сообщение помощнику'), 'Черновик первого чата');
    first.unmount();

    openChat('/checks/demo-project/chats/terms-thread');
    expect(screen.getByLabelText('Сообщение помощнику')).toHaveValue('');
  });

  it('keeps the draft while a basis is opened in the panel', async () => {
    const user = userEvent.setup();
    openChat(DEMO);

    await user.type(screen.getByLabelText('Сообщение помощнику'), 'Черновик');
    await user.click(screen.getByRole('button', { name: 'Основание 2: Действующие исполнительные производства' }));

    expect(screen.getByLabelText('Сообщение помощнику')).toHaveValue('Черновик');
  });
});
