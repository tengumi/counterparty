/**
 * S2-13/S2-14 chat switcher.
 *
 * Chats are sessions of one project: switching only changes the thread of the
 * same S2 surface, and a chat that is running keeps its own status.
 */

import { useEffect, useId, useRef, useState } from 'react';
import { Button } from '@alfalab/core-components/button';
import { ChatStatusMark } from '../../components/StatusMark';
import type { ChatSummary } from '../../mocks/types';
import styles from './S2.module.css';

interface Props {
  readonly chats: readonly ChatSummary[];
  readonly activeChatId: string | undefined;
  readonly onSelect: (chatId: string) => void;
  readonly onCreate?: () => void;
}

export function ChatSwitcher({ chats, activeChatId, onSelect, onCreate }: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const active = chats.find((chat) => chat.id === activeChatId);

  useEffect(() => {
    if (!open) return;
    popoverRef.current?.querySelector<HTMLButtonElement>('button[aria-current="true"]')?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onPointerDown);
    };
  }, [open]);

  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div className={styles.switcherWrap} ref={containerRef}>
      <button
        aria-controls={open ? listId : undefined}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={styles.switcher}
        onClick={() => setOpen((value) => !value)}
        ref={triggerRef}
        type="button"
      >
        <span className={styles.switcherLabel}>Чат: {active?.title ?? 'не выбран'}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {open ? (
        <div
          aria-label="Чаты проверки"
          className={styles.popover}
          id={listId}
          ref={popoverRef}
          role="dialog"
          onKeyDown={(event) => {
            if (event.key !== 'Tab') return;
            const buttons = popoverRef.current?.querySelectorAll<HTMLButtonElement>('button');
            const first = buttons?.[0];
            const last = buttons?.[buttons.length - 1];
            if (event.shiftKey && event.target === first) {
              event.preventDefault();
              last?.focus();
            } else if (!event.shiftKey && event.target === last) {
              event.preventDefault();
              first?.focus();
            }
          }}
        >
          <p className={styles.popoverTitle}>Чаты проверки</p>
          <ul className={styles.chatList}>
            {chats.map((chat) => (
              <li key={chat.id}>
                <button
                  aria-current={chat.id === activeChatId}
                  className={styles.chatItem}
                  onClick={() => {
                    onSelect(chat.id);
                    close();
                  }}
                  type="button"
                >
                  <span className={styles.chatName}>{chat.title}</span>
                  <span className={styles.chatHint}>{chat.hint}</span>
                  <ChatStatusMark status={chat.status} />
                </button>
              </li>
            ))}
          </ul>
          <button
            className={styles.newChat}
            disabled={!onCreate}
            onClick={() => {
              onCreate?.();
              close();
            }}
            type="button"
          >
            Новый чат
          </button>
          {!onCreate ? <p className={styles.muted}>Создание новых чатов пока недоступно.</p> : null}
          <Button block={true} onClick={close} size={40} view="secondary">
            Закрыть
          </Button>
        </div>
      ) : null}
    </div>
  );
}
