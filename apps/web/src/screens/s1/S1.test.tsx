import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SavedChecksList } from './SavedChecksList';
import { TaskComposer } from './TaskComposer';
import type { ProjectSummary } from '../../mocks/types';

function project(overrides: Partial<ProjectSummary> & { id: string }): ProjectSummary {
  return {
    title: `Проверка ${overrides.id}`,
    status: 'in_progress',
    continuation: null,
    lastActivityLabel: '14 августа',
    lastActivityAt: '2026-08-14T09:40:00+03:00',
    lastThreadId: 'thread',
    ...overrides,
  };
}

function renderList(projects: readonly ProjectSummary[]) {
  return render(<MemoryRouter><SavedChecksList projects={projects} /></MemoryRouter>);
}

describe('saved checks list', () => {
  it('shows the empty state and no search when nothing is saved', () => {
    renderList([]);
    expect(screen.getByText('Здесь появятся ваши проверки')).toBeVisible();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
    expect(screen.queryByLabelText('Поиск по проверкам')).not.toBeInTheDocument();
  });

  it('keeps search hidden below six saved checks', () => {
    renderList([project({ id: 'a' }), project({ id: 'b' }), project({ id: 'c' })]);
    expect(screen.queryByLabelText('Поиск по проверкам')).not.toBeInTheDocument();
    expect(screen.getAllByRole('link')).toHaveLength(3);
  });

  it('filters from six saved checks and explains an empty result', async () => {
    const user = userEvent.setup();
    const many = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => project({ id }));
    renderList([project({ id: 'ural', title: 'Логистика на Урал' }), ...many]);

    const search = screen.getByLabelText('Поиск по проверкам');
    await user.type(search, 'логистика');
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(screen.getByRole('link', { name: /Логистика на Урал/ })).toBeVisible();

    await user.clear(search);
    await user.type(search, 'нет такой');
    expect(screen.getByText('Ничего не найдено. Измените запрос')).toBeVisible();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
  });

  it('keeps a long check title readable and linked to its stored place', () => {
    const long = 'Проверка поставщика специализированного холодильного оборудования для складского комплекса в Екатеринбурге до 20 сентября';
    renderList([project({ id: 'long', title: long, lastThreadId: 'saved-thread' })]);
    expect(screen.getByRole('link', { name: new RegExp(long) })).toHaveAttribute(
      'href',
      '/checks/long/chats/saved-thread',
    );
  });

  it('shows one project status and the continuation reason', () => {
    renderList([
      project({ id: 'a', status: 'needs_input', continuation: 'Ждём подтверждение наличия товара' }),
    ]);
    expect(screen.getByText('Нужны сведения')).toBeVisible();
    expect(screen.getByText('Ждём подтверждение наличия товара')).toBeVisible();
    expect(screen.queryByText('В работе')).not.toBeInTheDocument();
  });
});

describe('task composer', () => {
  it('refuses an empty send and sends trimmed text on Enter', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<TaskComposer onSubmit={onSubmit} />);

    const send = screen.getByRole('button', { name: 'Отправить' });
    expect(send).toBeDisabled();

    const field = screen.getByLabelText('Задача проверки');
    await user.type(field, '  Проверьте ИНН 7714497158  ');
    expect(send).toBeEnabled();
    await user.type(field, '{Enter}');
    expect(onSubmit).toHaveBeenCalledWith('Проверьте ИНН 7714497158');
  });

  it('inserts an example as editable text without sending it', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<TaskComposer onSubmit={onSubmit} />);

    await user.click(screen.getByRole('button', { name: 'Хочу сравнить компании' }));
    expect(screen.getByLabelText('Задача проверки')).toHaveValue('Хочу сравнить компании ');
    expect(onSubmit).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText('Задача проверки'), 'А и Б{Shift>}{Enter}{/Shift}');
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
