import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ChecksSidebar } from './ChecksSidebar';
import { WorkspaceQueryProvider } from '../api/QueryProvider';
import { apiProjects } from '../test/setup';
import { ChecksPage } from '../pages/ChecksPage';
import { CompanyContextStrip } from '../screens/s2/CompanyContextStrip';

function open(path: string) {
  return render(<MemoryRouter initialEntries={[path]}>
    <WorkspaceQueryProvider initialProjects={apiProjects}>
      <ChecksSidebar />
      <main><Routes>
        <Route path="/checks" element={<ChecksPage />} />
        <Route path="/checks/:projectId/chats/:threadId" element={<p>Сохранённый разговор</p>} />
      </Routes></main>
    </WorkspaceQueryProvider>
  </MemoryRouter>);
}

describe('Общая навигация проверок', () => {
  it('показывает историю только слева, а новую задачу — в основной области', () => {
    open('/checks');
    const nav = screen.getByRole('complementary', { name: 'Навигация проверок' });
    expect(within(nav).getByRole('heading', { name: 'История проверок' })).toBeVisible();
    expect(within(nav).getAllByRole('link')).toHaveLength(apiProjects.length + 3);
    expect(screen.queryByText('Демонстрационная версия')).not.toBeInTheDocument();
    expect(within(screen.getByRole('main')).queryByRole('heading', { name: 'История проверок' })).not.toBeInTheDocument();
    expect(within(screen.getByRole('main')).getByLabelText('Задача проверки')).toBeVisible();
  });

  it('сохраняет историю при переходе в проект и отмечает текущую проверку', async () => {
    const user = userEvent.setup();
    open('/checks');
    const nav = screen.getByRole('complementary', { name: 'Навигация проверок' });
    const saved = within(nav).getByRole('link', { name: /Поставка оборудования к 20 сентября/ });
    await user.click(saved);
    expect(screen.getByText('Сохранённый разговор')).toBeVisible();
    expect(saved).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: /Логистика на Урал/ })).toBeVisible();
    await user.click(within(nav).getByRole('link', { name: 'Новая проверка' }));
    expect(screen.getByLabelText('Задача проверки')).toBeVisible();
    expect(saved).not.toHaveAttribute('aria-current');
  });

  it('возвращает на главную по логотипу', async () => {
    const user = userEvent.setup();
    open('/checks/demo-project/chats/demo-thread');
    const logo = screen.getByRole('link', { name: 'Альфа-Бизнес — на главную' });
    expect(logo).toHaveAttribute('href', '/checks');
    await user.click(logo);
    expect(screen.getByLabelText('Задача проверки')).toBeVisible();
    expect(screen.queryByText('Сохранённый разговор')).not.toBeInTheDocument();
  });

  it('оставляет управление компаниями доступным при лимите 20 без кнопки «Материалы»', async () => {
    const user = userEvent.setup();
    const openCompanies = vi.fn();
    render(<CompanyContextStrip companies={Array.from({ length: 20 }, (_, i) => ({
      id: String(i), name: `Компания ${i + 1}`, inn: '7449088645',
    }))} status="in_progress" isDemo={false} onOpenCompany={vi.fn()} onAddCompany={openCompanies} onCompare={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled();
    expect(screen.queryByText('В работе')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Все компании проверки: 20' }));
    expect(openCompanies).toHaveBeenCalledOnce();
  });

  it('сохраняет значимые статусы в строке компаний', () => {
    render(<CompanyContextStrip companies={[]} status="needs_input" isDemo={false}
      onOpenCompany={vi.fn()} onAddCompany={vi.fn()} onCompare={vi.fn()} />);
    expect(screen.getByText('Нужны сведения')).toBeVisible();
  });

  it('сохраняет действия и полное имя компании в новых плашках', async () => {
    const user = userEvent.setup();
    const openCompany = vi.fn();
    const addCompany = vi.fn();
    const compare = vi.fn();
    const name = 'ООО «Специализированная транспортно-логистическая компания»';
    render(<CompanyContextStrip companies={[
      { id: 'first', name, inn: '7449088645' },
      { id: 'second', name: 'Вторая компания', inn: '1684017097' },
    ]} status="in_progress" isDemo={false} onOpenCompany={openCompany}
      onAddCompany={addCompany} onCompare={compare} />);

    const company = screen.getByRole('button', { name });
    expect(company).toHaveAttribute('title', name);
    await user.click(company);
    expect(openCompany).toHaveBeenCalledWith('first');
    await user.click(screen.getByRole('button', { name: 'Все компании проверки: 2' }));
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    expect(addCompany).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: 'Сравнить' }));
    expect(compare).toHaveBeenCalledOnce();
  });
});
