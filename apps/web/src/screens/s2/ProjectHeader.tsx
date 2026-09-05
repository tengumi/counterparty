/**
 * S2-01 header: back to S1, project name, save state, chats and materials.
 *
 * «Сохранено» only appears for a state the server confirmed; a failed save
 * offers a retry instead and never hides the draft.
 */

import { useState } from 'react';
import { Button } from '@alfalab/core-components/button';
import { Input } from '@alfalab/core-components/input';
import { Link } from 'react-router-dom';
import { ChatSwitcher } from './ChatSwitcher';
import type { ChatSummary, SaveState } from '../../mocks/types';
import styles from './S2.module.css';

interface Props {
  readonly title: string;
  readonly saveState: SaveState;
  readonly saveError?: string | null;
  readonly onRename?: (title: string) => void;
  readonly onRetryRename?: () => void;
  readonly chats: readonly ChatSummary[];
  readonly activeChatId: string | undefined;
  readonly onSelectChat: (chatId: string) => void;
  readonly onCreateChat: () => void;
  readonly materialsOpen: boolean;
  readonly onToggleMaterials: () => void;
}

function SaveIndicator({ state }: { state: SaveState }) {
  if (state === 'saving') return <span className={styles.saveState}>Сохраняем…</span>;
  if (state === 'error') {
    return (
      <span className={styles.saveError} role="status">
        Не удалось сохранить
      </span>
    );
  }
  return <span className={styles.saveState}>Сохранено</span>;
}

export function ProjectHeader(props: Props) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(props.title);

  const saveTitle = () => {
    const next = title.trim();
    if (!next || next === props.title) {
      setTitle(props.title);
      setEditing(false);
      return;
    }
    props.onRename?.(next);
    setEditing(false);
  };

  return (
    <header className={styles.header}>
      <Link className={styles.back} to="/checks">← Все проверки</Link>
      <span aria-hidden="true" className={styles.divider} />
      {editing ? (
        <Input
          block={true}
          label="Название проверки"
          labelView="outer"
          onChange={(_event, payload) => setTitle(payload.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') saveTitle();
            if (event.key === 'Escape') { setTitle(props.title); setEditing(false); }
          }}
          onBlur={saveTitle}
          size={40}
          value={title}
        />
      ) : (
        <button
          aria-label="Переименовать проверку"
          className={styles.projectTitleButton}
          onClick={() => setEditing(true)}
          title={props.title}
          type="button"
        >
          {props.title}
        </button>
      )}
      <SaveIndicator state={props.saveState} />
      {props.saveError ? (
        <span className={styles.saveError} role="alert">
          {props.saveError}
          {props.onRetryRename ? (
            <button className={styles.retryLink} onClick={props.onRetryRename} type="button">Повторить</button>
          ) : null}
        </span>
      ) : null}
      <div className={styles.headerActions}>
        <ChatSwitcher
          activeChatId={props.activeChatId}
          chats={props.chats}
          onCreate={props.onCreateChat}
          onSelect={props.onSelectChat}
        />
        <Button
          aria-expanded={props.materialsOpen}
          onClick={props.onToggleMaterials}
          size={40}
          view="secondary"
        >
          Материалы
        </Button>
      </div>
    </header>
  );
}
