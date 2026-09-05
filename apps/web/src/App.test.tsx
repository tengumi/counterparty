import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { App } from './App';

function openRoute(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

describe('app foundation routes', () => {
  it('opens a demo chat and returns to checks using actual navigation', async () => {
    const user = userEvent.setup();
    openRoute('/checks');
    expect(screen.getByRole('heading', { name: 'Проверка контрагентов' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Открыть пример проверки' }));
    expect(screen.getByRole('heading', { name: 'Разговор о поставке' })).toBeVisible();
    expect(screen.queryByText('Сохранено')).not.toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: '← Все проверки' }));
    expect(screen.getByRole('heading', { name: 'Мои проверки' })).toBeVisible();
  });

  it.each(['/checks/other/chats/thread-2', '/checks/other'])('opens %s without presenting demo as loaded project data', (path) => {
    openRoute(path);
    expect(screen.getByRole('heading', { name: 'Разговор' })).toBeVisible();
    expect(screen.getByText('Разговор пока недоступен. Данные проверки не загружены.')).toBeVisible();
    expect(screen.queryByText('Поставка оборудования к 20 сентября')).not.toBeInTheDocument();
  });

  it('redirects the root to checks', () => {
    openRoute('/');
    expect(screen.getByRole('heading', { name: 'Мои проверки' })).toBeVisible();
  });

  it('provides a recovery link for unknown URLs', () => {
    openRoute('/missing');
    expect(screen.getByRole('heading', { name: 'Страница не найдена' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Все проверки' })).toHaveAttribute('href', '/checks');
  });
});
