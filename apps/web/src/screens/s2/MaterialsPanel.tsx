/**
 * P1 shell: one panel with the four groups of 07 §6.
 *
 * D2 only owns the layout — 400 px beside the conversation and an overlay
 * below 1000 px. Group contents stay empty because no materials are loaded.
 */

import { useEffect, useRef } from 'react';
import { Button } from '@alfalab/core-components/button';
import styles from './S2.module.css';

export type MaterialsSection = 'companies' | 'terms' | 'documents' | 'summary';

const groups: readonly { id: MaterialsSection; title: string }[] = [
  { id: 'companies', title: 'Компании' },
  { id: 'terms', title: 'Условия' },
  { id: 'documents', title: 'Документы' },
  { id: 'summary', title: 'Итог' },
];

interface Props {
  readonly section: MaterialsSection;
  readonly onClose: () => void;
}

export function MaterialsPanel({ section, onClose }: Props) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <aside aria-label="Материалы проверки" className={styles.panel}>
      <div className={styles.panelHeader}>
        <h2 className={styles.panelTitle} ref={headingRef} tabIndex={-1}>Материалы</h2>
        <span className={styles.panelClose}>
          <Button onClick={onClose} size={40} view="secondary">Закрыть</Button>
        </span>
      </div>
      <div className={styles.panelBody}>
        {groups.map((group) => (
          <section
            aria-current={group.id === section ? 'true' : undefined}
            className={styles.panelGroup}
            key={group.id}
          >
            <h3 className={styles.panelTitle}>{group.title}</h3>
            <p className={styles.muted}>Материалы проверки не загружены</p>
          </section>
        ))}
      </div>
    </aside>
  );
}
