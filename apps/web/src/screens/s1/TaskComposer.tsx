/**
 * S1-02 task field and S1-03 example prompts.
 *
 * Examples insert editable text and never send by themselves; an empty draft
 * cannot be sent. Attachments belong to the composer work of WEB-04.
 */

import { useId, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Button } from '@alfalab/core-components/button';
import { Textarea } from '@alfalab/core-components/textarea';
import { examplePrompts } from '../../mocks/workspace';
import styles from './S1.module.css';

export function TaskComposer({ onSubmit }: { onSubmit: (task: string) => void }) {
  const [draft, setDraft] = useState('');
  const fieldId = useId();
  const canSend = draft.trim().length > 0;

  const send = () => {
    if (canSend) onSubmit(draft.trim());
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  };

  return (
    <>
      <div className={styles.composer}>
        <Textarea
          autosize={true}
          block={true}
          fieldClassName={styles.field}
          textareaClassName={styles.fieldText}
          aria-label="Задача проверки"
          id={fieldId}
          maxRows={8}
          minRows={2}
          onChange={(_event, { value }) => setDraft(value)}
          onKeyDown={onKeyDown}
          placeholder="Напишите вопрос или вставьте ИНН"
          value={draft}
        />
        <div className={styles.composerActions}>
          <p className={styles.hint}>Enter отправляет, Shift+Enter переносит строку</p>
          <Button disabled={!canSend} onClick={send} size={40} view="primary">
            Отправить
          </Button>
        </div>
      </div>
      <div className={styles.examples}>
        {examplePrompts.map((example) => (
          <Button
            className={styles.example}
            key={example.id}
            onClick={() => setDraft(example.text)}
            size={40}
            view="outlined"
          >
            {example.label}
          </Button>
        ))}
      </div>
    </>
  );
}
