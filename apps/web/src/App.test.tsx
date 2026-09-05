import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { apiProjects } from './test/setup';

function openRoute(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><App fixtureMode initialProjects={apiProjects} /></MemoryRouter>);
}

describe('check routes', () => {
  it('opens a saved check at its stored place and returns to the list', async () => {
    const user = userEvent.setup();
    openRoute('/checks');
    expect(screen.getByRole('heading', { name: 'Проверка контрагентов' })).toBeVisible();

    await user.click(screen.getByRole('link', { name: /Поставка оборудования к 20 сентября/ }));
    expect(screen.getByTitle('Поставка оборудования к 20 сентября')).toBeVisible();
    expect(screen.getByRole('button', { name: /Чат: Поставка/ })).toBeVisible();
    expect(screen.getByText('Остановились на…')).toBeVisible();

    await user.click(screen.getByRole('link', { name: '← Все проверки' }));
    expect(screen.getByRole('heading', { name: 'Проверка контрагентов' })).toBeVisible();
  });

  it('keeps the demo agent chat available on its own route', () => {
    openRoute('/checks/demo-project/chats/demo-thread');
    expect(screen.getByLabelText('Сообщение помощнику')).toBeVisible();
    expect(screen.getByText('Учебный пример')).toBeVisible();
  });

  it('does not present an unknown project as loaded data', async () => {
    openRoute('/checks/other/chats/thread-2');
    expect(await screen.findByRole('heading', { name: 'Проверка не найдена' })).toBeVisible();
    expect(screen.queryByText('Поставка оборудования к 20 сентября')).not.toBeInTheDocument();
  });

  it('says so when the chat of a real project is unknown', () => {
    openRoute('/checks/demo-project/chats/missing-thread');
    expect(screen.getByRole('heading', { name: 'Чат не найден' })).toBeVisible();
    expect(screen.getByTitle('Поставка оборудования к 20 сентября')).toBeVisible();
  });

  it('redirects the root to checks', () => {
    openRoute('/');
    expect(screen.getByRole('heading', { name: 'Проверка контрагентов' })).toBeVisible();
  });

  it('provides a recovery link for unknown URLs', () => {
    openRoute('/missing');
    expect(screen.getByRole('heading', { name: 'Страница не найдена' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Все проверки' })).toHaveAttribute('href', '/checks');
  });

  it('shows an unavailable state on a network failure without claiming there are no checks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    render(<MemoryRouter initialEntries={['/checks']}><App /></MemoryRouter>);

    expect(await screen.findByRole('alert')).toHaveTextContent('Сведения не загружены');
    expect(screen.getByRole('alert')).toHaveTextContent('Это не означает, что сохранённых проверок нет');
    expect(screen.queryByText('Здесь появятся ваши проверки')).not.toBeInTheDocument();
  });
});
