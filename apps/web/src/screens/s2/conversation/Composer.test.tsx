/**
 * WEB-04: the composer states of 07 S2-10/S2-17.
 *
 * The transport cases behind these states (a terminal error, a cancel of a
 * live run) are decoded end to end in `src/chat/transport.test.tsx`; here the
 * contract under test is what the user is offered in each state — one primary
 * action, a separate «Остановить», and text that is never lost.
 */

import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AssistantBoundary, Composer } from './Composer';
import type { ComposerStatus } from './Composer';

function show(status: ComposerStatus, value = 'Проверьте аванс', extra: Partial<{
  onSend: (text: string) => void;
  onStop: () => void;
  unavailableReason: string;
}> = {}) {
  return render(
    <Composer
      onChange={() => undefined}
      onSend={extra.onSend ?? (() => undefined)}
      onStop={extra.onStop ?? (() => undefined)}
      status={status}
      unavailableReason={extra.unavailableReason ?? null}
      value={value}
    />,
  );
}

describe('S2 composer states', () => {
  it('refuses to send an empty message', () => {
    show('idle', '   ');
    expect(screen.getByRole('button', { name: 'Отправить' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Остановить' })).not.toBeInTheDocument();
  });

  it('sends on Enter and keeps Shift+Enter for a new line', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    show('idle', 'Можно ли платить авансом?', { onSend });

    expect(screen.queryByText(/Enter отправляет/)).not.toBeInTheDocument();
    await user.click(screen.getByLabelText('Сообщение помощнику'));
    await user.keyboard('{Shift>}{Enter}{/Shift}');
    expect(onSend).not.toHaveBeenCalled();

    await user.keyboard('{Enter}');
    expect(onSend).toHaveBeenCalledWith('Можно ли платить авансом?');
  });

  it('keeps Enter as a newline on mobile and sends with the button', async () => {
    const media = vi.spyOn(window, 'matchMedia');
    media.mockReturnValue({ ...window.matchMedia(''), matches: true });
    try {
      const user = userEvent.setup();
      const onSend = vi.fn();
      show('idle', 'Уточнение', { onSend });
      await user.click(screen.getByLabelText('Сообщение помощнику'));
      await user.keyboard('{Enter}');
      expect(onSend).not.toHaveBeenCalled();
      await user.click(screen.getByRole('button', { name: 'Отправить' }));
      expect(onSend).toHaveBeenCalledWith('Уточнение');
    } finally {
      media.mockRestore();
    }
  });

  it('offers exactly one way to stop a run in progress', async () => {
    const user = userEvent.setup();
    const onStop = vi.fn();
    show('running', 'Уточнение', { onStop });

    const stop = screen.getByRole('button', { name: 'Остановить' });
    expect(stop).toBeEnabled();
    await user.click(stop);
    expect(onStop).toHaveBeenCalledTimes(1);

    // A clarification can still be sent while the assistant works; the running
    // state itself needs no line — the streamed activity already shows it.
    expect(screen.getByRole('button', { name: 'Отправить' })).toBeEnabled();
    expect(screen.getByRole('status')).toHaveTextContent('');
  });

  it('shows only the stop control while a run works and the field is empty', () => {
    show('running', '', { onStop: vi.fn() });
    expect(screen.getByRole('button', { name: 'Остановить' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отправить' })).not.toBeInTheDocument();
  });

  it('does not let a cancel be asked for twice', () => {
    show('cancelling');
    expect(screen.getByRole('button', { name: 'Остановить' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Останавливаем проверку…');
  });

  it('keeps the text after a failed delivery and offers to try again', () => {
    show('error', 'Текст, который не ушёл');

    expect(screen.getByLabelText('Сообщение помощнику')).toHaveValue('Текст, который не ушёл');
    expect(screen.getByRole('button', { name: 'Отправить' })).toBeEnabled();
    expect(screen.getByRole('status')).toHaveTextContent(/Текст сохранён/);
  });

  it('says why a chat cannot send instead of showing a dead button', () => {
    show('unavailable', 'Черновик', { unavailableReason: 'Сервер этой проверки не подключён.' });

    expect(screen.getByLabelText('Сообщение помощнику')).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Отправить' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Сервер этой проверки не подключён.');
  });

  it('never loses what is typed while the state changes under it', async () => {
    const user = userEvent.setup();

    function Host() {
      const [text, setText] = useState('');
      const [status, setStatus] = useState<ComposerStatus>('idle');
      return (
        <>
          <button onClick={() => setStatus('error')} type="button">
            Сломать отправку
          </button>
          <Composer
            onChange={setText}
            onSend={() => undefined}
            onStop={() => undefined}
            status={status}
            value={text}
          />
        </>
      );
    }

    render(<Host />);
    await user.type(screen.getByLabelText('Сообщение помощнику'), 'Уточню срок поставки');
    await user.click(screen.getByRole('button', { name: 'Сломать отправку' }));

    expect(screen.getByLabelText('Сообщение помощнику')).toHaveValue('Уточню срок поставки');
  });
});

describe('S2 assistant boundary', () => {
  it('states the limit of the assistant and keeps the detail on request', async () => {
    const user = userEvent.setup();
    render(<AssistantBoundary />);

    expect(screen.getByText(/AI может ошибаться/)).toBeVisible();
    expect(screen.getByText(/не принимает решение за вас/)).not.toBeVisible();

    await user.click(screen.getByText('Как работает помощник'));
    expect(screen.getByText(/не принимает решение за вас/)).toBeVisible();
  });
});
