import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ProjectHeader } from './ProjectHeader';
import type { ComponentProps } from 'react';

const longTitle = 'Мне прислали три новых поставщика: 1684017097, 9714038662 и 9727128465. Посмотри, что важно для аванса.';
const chatLabel = `Чат проверки. Чат: ${longTitle}`;

function headerProps(): ComponentProps<typeof ProjectHeader> {
  return {
    title: longTitle,
    saveState: 'saved',
    chats: [{ id: 'first', title: longTitle, hint: '', status: 'ready' }],
    activeChatId: 'first',
    onSelectChat: vi.fn(),
    onRename: vi.fn(),
    onRetryRename: vi.fn(),
  };
}

describe('Шапка проверки', () => {
  it('не дублирует длинный заголовок в кнопке чата и сохраняет полное доступное имя', () => {
    render(<MemoryRouter><ProjectHeader {...headerProps()} /></MemoryRouter>);

    expect(screen.getByRole('button', { name: 'Переименовать проверку' })).toHaveAttribute('title', longTitle);
    expect(screen.getByRole('button', { name: chatLabel })).toHaveTextContent('Чат проверки');
    expect(screen.getByText(longTitle)).toBeVisible();
    expect(screen.queryByRole('link', { name: /Все проверки/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Материалы' })).not.toBeInTheDocument();
  });

  it('сохраняет выбор отдельного чата и возвращает фокус после Escape', async () => {
    const user = userEvent.setup();
    const props = headerProps();
    render(<MemoryRouter><ProjectHeader {...props} chats={[
      ...props.chats,
      { id: 'second', title: 'Условия оплаты', hint: 'Обсуждаем аванс', status: 'ready' },
    ]} /></MemoryRouter>);

    const trigger = screen.getByRole('button', { name: chatLabel });
    await user.click(trigger);
    await user.keyboard('{Escape}');
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: /Условия оплаты/ }));
    expect(props.onSelectChat).toHaveBeenCalledWith('second');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
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
