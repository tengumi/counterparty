/**
 * S2-10 composer: one field, one primary action and its states.
 *
 * States: empty, typing, sending, a run in progress, a delivery error and the
 * moment after a cancel. «Отправить» is the single primary CTA; «Остановить»
 * is a separate secondary command (07 S2-17), never a second red button.
 */

import type { KeyboardEvent, RefObject } from 'react';
import { ArrowUpMIcon } from '@alfalab/icons-glyph/ArrowUpMIcon';
import { Button } from '@alfalab/core-components/button';
import styles from './Conversation.module.css';

export type ComposerStatus =
  | 'idle'
  | 'sending'
  | 'running'
  | 'cancelling'
  | 'error'
  | 'unavailable';

interface Props {
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly onSend: (text: string) => void;
  readonly onStop: () => void;
  readonly status: ComposerStatus;
  /** Why sending is impossible in this chat; shown instead of a dead button. */
  readonly unavailableReason?: string | null;
  readonly inputRef?: RefObject<HTMLTextAreaElement | null>;
}

const hints: Readonly<Record<ComposerStatus, string>> = {
  idle: 'Enter отправляет, Shift+Enter переносит строку',
  sending: 'Отправляем сообщение…',
  running: 'Помощник работает. Уточнение можно отправить сейчас',
  cancelling: 'Останавливаем проверку…',
  error: 'Сообщение не отправлено. Текст сохранён — попробуйте ещё раз',
  unavailable: '',
};

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  status,
  unavailableReason = null,
  inputRef,
}: Props) {
  const busy = status === 'running' || status === 'cancelling';
  const disabled = status === 'unavailable';
  const canSend = value.trim().length > 0 && !disabled && status !== 'sending';

  const placeholder = busy
    ? 'Добавьте уточнение — учту после текущего действия'
    : 'Напишите вопрос или вставьте ИНН';

  const send = () => {
    if (canSend) onSend(value.trim());
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !window.matchMedia('(max-width: 640px)').matches) {
      event.preventDefault();
      send();
    }
  };

  return (
    <div className={styles.composer} data-status={status}>
      <textarea
        aria-label="Сообщение помощнику"
        className={styles.input}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        ref={inputRef}
        rows={2}
        value={value}
      />
      <div className={styles.composerRow}>
        <p className={styles.composerHint} role="status">
          {disabled ? unavailableReason : hints[status]}
        </p>
        <div className={styles.composerActions}>
          {busy ? (
            <Button
              disabled={status === 'cancelling'}
              onClick={onStop}
              size={40}
              view="secondary"
            >
              Остановить
            </Button>
          ) : null}
          <Button
            aria-label="Отправить"
            className={styles.send}
            disabled={!canSend}
            loading={status === 'sending'}
            onClick={send}
            size={40}
            view="primary"
          >
            <ArrowUpMIcon aria-hidden={true} />
          </Button>
        </div>
      </div>
    </div>
  );
}

/** S2-12: one permanent boundary note under the composer. */
export function AssistantBoundary() {
  return (
    <div className={styles.disclaimer}>
      <p>AI может ошибаться. Проверяйте основания; решение принимаете вы</p>
      <details>
        <summary>Как работает помощник</summary>
        <p className={styles.disclaimerText}>
          Помощник отвечает по сведениям отчёта, вашим условиям и загруженным документам. Он не
          видит других данных банка и не принимает решение за вас: каждое утверждение можно открыть
          и проверить в материалах проверки.
        </p>
      </details>
    </div>
  );
}
