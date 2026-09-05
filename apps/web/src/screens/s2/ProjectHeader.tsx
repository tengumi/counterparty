/**
 * S2-01 header: back to S1, project name, save state, chats and materials.
 *
 * «Сохранено» only appears for a state the server confirmed; a failed save
 * offers a retry instead and never hides the draft.
 */

import { Button } from '@alfalab/core-components/button';
import { Link } from 'react-router-dom';
import { ChatSwitcher } from './ChatSwitcher';
import type { ChatSummary, SaveState } from '../../mocks/types';
import styles from './S2.module.css';

interface Props {
  readonly title: string;
  readonly saveState: SaveState;
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
  return (
    <header className={styles.header}>
      <Link className={styles.back} to="/checks">← Все проверки</Link>
      <span aria-hidden="true" className={styles.divider} />
      <span className={styles.projectTitle} title={props.title}>{props.title}</span>
      <SaveIndicator state={props.saveState} />
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
