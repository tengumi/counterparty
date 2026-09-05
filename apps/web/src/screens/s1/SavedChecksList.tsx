/**
 * S1-04/S1-05 saved checks.
 *
 * Every row shows a title, the last activity and exactly one project status.
 * Company risk never appears here. Search shows up from six saved checks.
 */

import { useMemo, useState } from 'react';
import { Input } from '@alfalab/core-components/input';
import { PureCell } from '@alfalab/core-components/pure-cell';
import { Link } from 'react-router-dom';
import { ProjectStatusMark } from '../../components/StatusMark';
import type { ProjectSummary } from '../../mocks/types';
import { SEARCH_THRESHOLD } from '../../mocks/types';
import styles from './S1.module.css';

function matches(project: ProjectSummary, query: string) {
  return project.title.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru').trim());
}

export function SavedChecksList({ projects }: { projects: readonly ProjectSummary[] }) {
  const [query, setQuery] = useState('');
  const searchable = projects.length >= SEARCH_THRESHOLD;
  const visible = useMemo(
    () => (searchable && query.trim() ? projects.filter((p) => matches(p, query)) : projects),
    [projects, query, searchable],
  );

  return (
    <section aria-labelledby="saved-checks">
      <h2 className={styles.listLabel} id="saved-checks">Проверки</h2>
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
              className={styles.row}
              to={`/checks/${project.id}/chats/${project.lastThreadId}`}
            >
              <PureCell horizontalPadding="none" verticalPadding="default">
                <PureCell.Content>
                  <PureCell.Main>
                    <PureCell.Text rowLimit={2} titleColor="primary" view="primary-medium">
                      {project.title}
                    </PureCell.Text>
                    {project.continuation ? (
                      <PureCell.Text rowLimit={1} titleColor="secondary" view="primary-small">
                        {project.continuation}
                      </PureCell.Text>
                    ) : null}
                  </PureCell.Main>
                  <PureCell.Addon verticalAlign="center">
                    <span className={styles.meta}>
                      <span className={styles.date}>{project.lastActivityLabel}</span>
                      <ProjectStatusMark status={project.status} />
                    </span>
                  </PureCell.Addon>
                </PureCell.Content>
              </PureCell>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
