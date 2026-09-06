import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ProjectHeader } from './ProjectHeader';
import type { ComponentProps } from 'react';

const longTitle = 'Мне прислали три новых поставщика: 1684017097, 9714038662 и 9727128465. Посмотри, что важно для аванса.';

function headerProps(): ComponentProps<typeof ProjectHeader> {
  return {
    title: longTitle,
    saveState: 'saved',
    onRename: vi.fn(),
    onRetryRename: vi.fn(),
  };
}

describe('Шапка проверки', () => {
  it('показывает название без переключателя чатов и подписи о сохранении', () => {
    render(<MemoryRouter><ProjectHeader {...headerProps()} /></MemoryRouter>);

    expect(screen.getByRole('button', { name: 'Переименовать проверку' })).toHaveAttribute('title', longTitle);
    expect(screen.queryByRole('button', { name: /Чат проверки|Чат:/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Сохранено')).not.toBeInTheDocument();
    expect(screen.getByText(longTitle)).toBeVisible();
    expect(screen.queryByRole('link', { name: /Все проверки/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Материалы' })).not.toBeInTheDocument();
  });

  it('показывает процесс сохранения и убирает подпись после завершения', () => {
    const props = headerProps();
    const view = render(<ProjectHeader {...props} saveState="saving" />);
    expect(screen.getByText('Сохраняем…')).toBeVisible();
    view.rerender(<ProjectHeader {...props} saveState="saved" />);
    expect(screen.queryByText('Сохраняем…')).not.toBeInTheDocument();
    expect(screen.queryByText('Сохранено')).not.toBeInTheDocument();
  });

  it('показывает ошибку и повтор вместо ложного подтверждения сохранения', async () => {
    const user = userEvent.setup();
    const props = { ...headerProps(), saveState: 'error' as const, saveError: 'Нет соединения' };
    render(<MemoryRouter><ProjectHeader {...props} /></MemoryRouter>);

    expect(screen.queryByText('Сохранено')).not.toBeInTheDocument();
    expect(screen.getByText('Не удалось сохранить')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(props.onRetryRename).toHaveBeenCalledOnce();
  });

  it('редактирует актуальное название после обновления проекта', async () => {
    const user = userEvent.setup();
    const props = headerProps();
    const view = render(<MemoryRouter><ProjectHeader {...props} /></MemoryRouter>);

    view.rerender(<MemoryRouter><ProjectHeader {...props} title="Проверка поставщиков" /></MemoryRouter>);
    await user.click(screen.getByRole('button', { name: 'Переименовать проверку' }));
    const input = screen.getByRole('textbox', { name: 'Название проверки' });
    expect(input).toHaveValue('Проверка поставщиков');
    await user.clear(input);
    await user.type(input, 'Поставка оборудования{Enter}');
    expect(props.onRename).toHaveBeenCalledWith('Поставка оборудования');
  });
});
