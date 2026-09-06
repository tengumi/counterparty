/** Сохраняемая история в боковой навигации. Поиск доступен от шести проверок. */

import { useMemo, useState } from 'react';
import { Input } from '@alfalab/core-components/input';
import { Link } from 'react-router-dom';
import { ProjectStatusMark } from '../../components/StatusMark';
import type { ProjectSummary } from '../../mocks/types';
import { SEARCH_THRESHOLD } from '../../mocks/types';
import styles from './S1.module.css';

function matches(project: ProjectSummary, query: string) {
  return project.title.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru').trim());
}

export function SavedChecksList({ projects, activeProjectId, onNavigate }: {
  projects: readonly ProjectSummary[];
  activeProjectId?: string;
  onNavigate?: () => void;
}) {
  const [query, setQuery] = useState('');
  const searchable = projects.length >= SEARCH_THRESHOLD;
  const visible = useMemo(
    () => (searchable && query.trim() ? projects.filter((p) => matches(p, query)) : projects),
    [projects, query, searchable],
  );

  return (
    <section aria-labelledby="saved-checks" className={styles.history}>
      <h2 className={styles.listLabel} id="saved-checks">История проверок</h2>
      {searchable ? (
        <div className={styles.search}>
          <Input
            block={true}
            clear={true}
            label="Поиск по проверкам"
            labelView="outer"
            onChange={(_event, { value }) => setQuery(value)}
            onClear={() => setQuery('')}
            placeholder="Название проверки"
            size={40}
            value={query}
          />
        </div>
      ) : null}
      {projects.length === 0 ? (
        <p className={styles.empty}>Здесь появятся ваши проверки</p>
      ) : null}
      {projects.length > 0 && visible.length === 0 ? (
        <p className={styles.empty}>Ничего не найдено. Измените запрос</p>
      ) : null}
      <ul className={styles.list}>
        {visible.map((project) => (
          <li key={project.id}>
            <Link
              aria-current={activeProjectId === project.id ? 'page' : undefined}
              className={styles.row}
              onClick={onNavigate}
              to={`/checks/${project.id}/chats/${project.lastThreadId}`}
            >
              <span className={styles.historyTitle} title={project.title}>{project.title}</span>
              {project.continuation ? <span className={styles.continuation} title={project.continuation}>{project.continuation}</span> : null}
              <span className={styles.meta}>
                <span className={styles.date}>{project.lastActivityLabel}</span>
                <ProjectStatusMark status={project.status} />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
