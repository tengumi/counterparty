/** Шапка проверки: название и сообщения о сохранении, требующие внимания. */

import { useState } from 'react';
import { Input } from '@alfalab/core-components/input';
import { PencilSIcon } from '@alfalab/icons-glyph/PencilSIcon';
import type { SaveState } from '../../mocks/types';
import styles from './S2.module.css';

interface Props {
  readonly title: string;
  readonly saveState: SaveState;
  readonly saveError?: string | null;
  readonly onRename?: (title: string) => void;
  readonly onRetryRename?: () => void;
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
  return null;
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
      <div className={styles.projectIdentity}>
        {editing ? (
          <Input
            className={styles.titleEditor}
            autoFocus={true}
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
            onClick={() => { setTitle(props.title); setEditing(true); }}
            title={props.title}
            type="button"
          >
            <span className={styles.projectTitleText}>{props.title}</span>
            <PencilSIcon aria-hidden="true" className={styles.renameIcon} />
          </button>
        )}
        <div aria-live="polite">
          <SaveIndicator state={props.saveState} />
        </div>
        {props.saveError ? (
          <span className={styles.saveError} role="alert">
            {props.saveError}
            {props.onRetryRename ? (
              <button className={styles.retryLink} onClick={props.onRetryRename} type="button">Повторить</button>
            ) : null}
          </span>
        ) : null}
      </div>
    </header>
  );
}
