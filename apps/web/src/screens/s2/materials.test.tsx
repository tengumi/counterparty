/**
 * WEB-05: the materials panel — its four groups, one level of detail and the
 * way back (07 §6).
 *
 * The panel is checked against the honesty rules of the specs: a group that
 * holds nothing says so, «Не указано» is not a zero, and a basis always names
 * its company, period, source and snapshot date.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { CheckPage } from '../../pages/CheckPage';

function openCheck(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<CheckPage />} path="/checks/:projectId" />
        <Route element={<CheckPage />} path="/checks/:projectId/chats/:threadId" />
      </Routes>
    </MemoryRouter>,
  );
}

const DEMO = '/checks/demo-project/chats/demo-thread';

function panel() {
  return screen.getByRole('complementary', { name: 'Материалы проверки' });
}

async function openPanel(user: ReturnType<typeof userEvent.setup>, path = DEMO) {
  const view = openCheck(path);
  await user.click(screen.getByRole('button', { name: 'Материалы' }));
  expect(panel()).toBeVisible();
  return view;
}

describe('S2 materials panel navigation', () => {
  it('opens a group, then one element of it, and walks back to the list', async () => {
    const user = userEvent.setup();
    await openPanel(user);

    const documents = screen.getByRole('button', { name: /Документы/ });
    expect(documents).toHaveAttribute('aria-expanded', 'false');
    await user.click(documents);
    expect(documents).toHaveAttribute('aria-expanded', 'true');

    await user.click(screen.getByRole('button', { name: /Счёт-оферта\.pdf/ }));

    expect(screen.getByRole('heading', { name: 'Счёт-оферта.pdf' })).toBeVisible();
    expect(screen.getByText('Компания А · добавлен 5 сентября')).toBeVisible();
    // One level deep only: the list is replaced, not stacked on top of itself.
    expect(screen.queryByRole('button', { name: /Документы/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'К материалам' }));
    expect(screen.getByRole('heading', { name: 'Материалы' })).toBeVisible();
    expect(screen.getByRole('button', { name: /Счёт-оферта\.pdf/ })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'К материалам' })).not.toBeInTheDocument();
  });

  it('shows a basis with its company, period, source and snapshot date', async () => {
    const user = userEvent.setup();
    openCheck(DEMO);

    await user.click(screen.getByRole('button', { name: 'Основание 3: Дата регистрации' }));

    const detail = panel();
    expect(within(detail).getByRole('heading', { name: 'Основание 3' })).toBeVisible();
    expect(within(detail).getByText('16 апреля 2009')).toBeVisible();
    expect(within(detail).getByText('Компания А')).toBeVisible();
    expect(
      within(detail).getByText('Предоставленный отчёт, раздел «Другие сведения»'),
    ).toBeVisible();
    expect(within(detail).getByText('5 августа 2026')).toBeVisible();
  });

  it('puts a basis into the composer as a context chip instead of sending it', async () => {
    const user = userEvent.setup();
    openCheck(DEMO);

    await user.click(
      screen.getByRole('button', { name: 'Основание 1: Капитал и резервы, 2025' }),
    );
    await user.click(screen.getByRole('button', { name: 'Обсудить' }));

    expect(screen.getByLabelText('Сообщение помощнику')).toHaveValue(
      'Капитал и резервы, 2025 · Компания А · 2025 год, годовая отчётность',
    );
  });

  it('says a term is not stated rather than showing it as a zero', async () => {
    const user = userEvent.setup();
    await openPanel(user);

    await user.click(screen.getByRole('button', { name: /Условия/ }));
    const row = screen.getByText('Приоритет').closest('div')!;
    // Twice on purpose: the value is unknown, and so is where it would come from.
    expect(within(row).getAllByText('Не указано')).toHaveLength(2);
    expect(row).not.toHaveTextContent('0');
    expect(row).not.toHaveTextContent('—');
  });

  it('admits an empty group instead of showing it as complete', async () => {
    const user = userEvent.setup();
    await openPanel(user, '/checks/inn-project/chats/inn-thread');

    await user.click(screen.getByRole('button', { name: /Условия/ }));
    expect(screen.getByText('Условия сделки ещё не записаны.')).toBeVisible();

    await user.click(screen.getByRole('button', { name: /Документы/ }));
    expect(screen.getByText(/Файлы не загружены/)).toBeVisible();
  });

  it('marks a proposed summary as the assistant’s, not as a recorded decision', async () => {
    const user = userEvent.setup();
    await openPanel(user);

    await user.click(screen.getByRole('button', { name: /Итог/ }));
    await user.click(
      screen.getByRole('button', { name: /аванс не выше 30%/ }),
    );

    expect(screen.getByRole('heading', { name: 'Итог проверки' })).toBeVisible();
    expect(screen.getByText('Предложение помощника')).toBeVisible();
    expect(screen.queryByText('Записано вами')).not.toBeInTheDocument();
  });

  it('remembers the open panel and the expanded groups after a remount', async () => {
    const user = userEvent.setup();
    const first = await openPanel(user);
    await user.click(within(panel()).getByRole('button', { name: /Документы/ }));
    first.unmount();

    openCheck(DEMO);
    expect(panel()).toBeVisible();
    expect(screen.getByRole('button', { name: /Документы/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('returns focus to whatever opened the panel when it is closed', async () => {
    const user = userEvent.setup();
    openCheck(DEMO);

    const trigger = screen.getByRole('button', { name: 'Материалы' });
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Закрыть' }));

    expect(screen.queryByRole('complementary', { name: 'Материалы проверки' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
