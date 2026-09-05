/**
 * P1 — one panel with the four groups of 07 §6 and one level of detail.
 *
 * The panel never invents data: a group that has nothing says so, «Не указано»
 * is not zero, and a basis shows the value with its company, period, source
 * and snapshot date. Company report and evidence source detail grow here in
 * WEB-06; this task owns the navigation, the states and their persistence.
 */

import { useEffect, useRef } from 'react';
import { Button } from '@alfalab/core-components/button';
import type { CompanyRef, ProjectDetail } from '../../mocks/types';
import { documentStateLabels } from '../../mocks/types';
import { findEvidence, getMaterials } from '../../mocks/workspace';
import type { MaterialsGroup, MaterialsState, MaterialsView } from './materialsView';
import { currentView, groupTitles } from './materialsView';
import styles from './S2.module.css';

interface Props {
  readonly project: ProjectDetail;
  readonly state: MaterialsState;
  readonly onChange: (state: MaterialsState) => void;
  readonly onClose: () => void;
  /** Puts a removable context chip into the composer (07 S2-08). */
  readonly onDiscuss: (text: string) => void;
}

function Group({
  group,
  count,
  expanded,
  onToggle,
  children,
}: {
  group: MaterialsGroup;
  count: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  const bodyId = `materials-${group}`;
  return (
    <section className={styles.group}>
      <h3>
        <button
          aria-controls={bodyId}
          aria-expanded={expanded}
          className={styles.groupHeader}
          onClick={onToggle}
          type="button"
        >
          <span className={styles.groupTitle}>{groupTitles[group]}</span>
          <span className={styles.groupCount}>{count}</span>
        </button>
      </h3>
      <div className={styles.groupBody} hidden={!expanded} id={bodyId}>
        {children}
      </div>
    </section>
  );
}

function CompanyRow({ company, current, onOpen }: { company: CompanyRef; current: boolean; onOpen: () => void }) {
  return (
    <button className={`${styles.row} ${styles.rowButton}`} onClick={onOpen} type="button">
      <span className={styles.rowMain}>
        <span className={styles.rowName}>{company.name}</span>
        <span className={styles.rowMeta}>ИНН {company.inn}</span>
      </span>
      {current ? <span className={styles.rowSide}>Текущая</span> : null}
    </button>
  );
}

export function MaterialsPanel({ project, state, onChange, onClose, onDiscuss }: Props) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const view = currentView(state);
  const materials = getMaterials(project.id);

  useEffect(() => {
    headingRef.current?.focus();
  }, [view.kind]);

  const push = (next: MaterialsView) => onChange({ ...state, stack: [...state.stack, next] });
  const back = () => onChange({ ...state, stack: state.stack.slice(0, -1) });
  const toggle = (group: MaterialsGroup) =>
    onChange({
      ...state,
      expanded: state.expanded.includes(group)
        ? state.expanded.filter((item) => item !== group)
        : [...state.expanded, group],
    });

  const evidence = view.kind === 'evidence' ? findEvidence(view.evidenceId) : undefined;
  const company =
    view.kind === 'company'
      ? project.companies.find((item) => item.id === view.companyId)
      : undefined;
  const document =
    view.kind === 'document'
      ? materials.documents.find((item) => item.id === view.documentId)
      : undefined;

  const titles: Record<MaterialsView['kind'], string> = {
    list: 'Материалы',
    company: company?.name ?? 'Компания',
    evidence: evidence ? `Основание ${evidence.number}` : 'Основание',
    document: document?.name ?? 'Документ',
    summary: 'Итог проверки',
  };

  return (
    <aside aria-label="Материалы проверки" className={styles.panel}>
      <div className={styles.panelHeader}>
        {state.stack.length > 1 ? (
          <span className={styles.panelBack}>
            <Button onClick={back} size={32} view="text">
              К материалам
            </Button>
          </span>
        ) : null}
        <h2 className={styles.panelTitle} ref={headingRef} tabIndex={-1}>
          {titles[view.kind]}
        </h2>
        <span className={styles.panelClose}>
          <Button onClick={onClose} size={40} view="secondary">
            Закрыть
          </Button>
        </span>
      </div>

      <div className={styles.panelBody}>
        {view.kind === 'list' ? (
          <div className={styles.panelGroups}>
            <Group
              count={String(project.companies.length)}
              expanded={state.expanded.includes('companies')}
              group="companies"
              onToggle={() => toggle('companies')}
            >
              {project.companies.map((item) => (
                <CompanyRow
                  company={item}
                  current={item.id === project.companies[0]?.id}
                  key={item.id}
                  onOpen={() => push({ kind: 'company', companyId: item.id })}
                />
              ))}
              <p className={styles.muted}>
                Добавление компаний появится вместе с поиском по демонстрационной базе.
              </p>
            </Group>

            <Group
              count={String(materials.terms.length)}
              expanded={state.expanded.includes('terms')}
              group="terms"
              onToggle={() => toggle('terms')}
            >
              {materials.terms.length === 0 ? (
                <p className={styles.muted}>Условия сделки ещё не записаны.</p>
              ) : (
                materials.terms.map((term) => (
                  <div className={styles.row} key={term.id}>
                    <span className={styles.termLabel}>{term.label}</span>
                    <span className={styles.rowMain}>
                      <span className={term.value === null ? styles.unknown : styles.rowName}>
                        {term.value ?? 'Не указано'}
                      </span>
                      <span className={styles.rowMeta}>{term.source}</span>
                    </span>
                  </div>
                ))
              )}
            </Group>

            <Group
              count={String(materials.documents.length)}
              expanded={state.expanded.includes('documents')}
              group="documents"
              onToggle={() => toggle('documents')}
            >
              {materials.documents.length === 0 ? (
                <p className={styles.muted}>
                  Файлы не загружены. Проверку можно закончить без них.
                </p>
              ) : (
                materials.documents.map((item) => (
                  <button
                    className={`${styles.row} ${styles.rowButton}`}
                    key={item.id}
                    onClick={() => push({ kind: 'document', documentId: item.id })}
                    type="button"
                  >
                    <span className={styles.rowMain}>
                      <span className={styles.rowName}>{item.name}</span>
                      <span className={styles.rowMeta}>{item.meta}</span>
                    </span>
                    <span className={styles.rowSide}>{documentStateLabels[item.state]}</span>
                  </button>
                ))
              )}
            </Group>

            <Group
              count={materials.summary.short}
              expanded={state.expanded.includes('summary')}
              group="summary"
              onToggle={() => toggle('summary')}
            >
              <button
                className={`${styles.row} ${styles.rowButton}`}
                onClick={() => push({ kind: 'summary' })}
                type="button"
              >
                <span className={styles.rowMain}>
                  <span className={styles.rowName}>{materials.summary.line}</span>
                </span>
              </button>
            </Group>
          </div>
        ) : null}

        {view.kind === 'company' ? (
          <div className={styles.detail}>
            {company === undefined ? (
              <p className={styles.muted}>Компания удалена из проверки.</p>
            ) : (
              <>
                <p className={styles.rowMeta}>ИНН {company.inn}</p>
                <p className={styles.muted}>
                  Сведения отчёта, оценка банка и ЗСК появятся здесь вместе с отчётом компании.
                </p>
              </>
            )}
          </div>
        ) : null}

        {view.kind === 'evidence' ? (
          <div className={styles.detail}>
            {evidence === undefined ? (
              <p className={styles.muted}>Основание недоступно: сведения не загружены.</p>
            ) : (
              <>
                <p className={styles.rowMeta}>{evidence.title}</p>
                <p className={styles.detailValue}>{evidence.value}</p>
                <dl className={styles.detailList}>
                  <dt>Компания</dt>
                  <dd>{evidence.companyName}</dd>
                  <dt>Период</dt>
                  <dd>{evidence.period}</dd>
                  <dt>Откуда</dt>
                  <dd>{evidence.source}</dd>
                  <dt>Дата среза</dt>
                  <dd>{evidence.asOf}</dd>
                </dl>
                <span>
                  <Button
                    onClick={() =>
                      onDiscuss(`${evidence.title} · ${evidence.companyName} · ${evidence.period}`)
                    }
                    size={40}
                    view="outlined"
                  >
                    Обсудить
                  </Button>
                </span>
              </>
            )}
          </div>
        ) : null}

        {view.kind === 'document' ? (
          <div className={styles.detail}>
            {document === undefined ? (
              <p className={styles.muted}>Документ удалён из проверки.</p>
            ) : (
              <>
                <p className={styles.rowMeta}>{document.meta}</p>
                <p className={styles.rowName}>{documentStateLabels[document.state]}</p>
                <p className={styles.muted}>
                  Просмотр файла появится вместе с загрузкой документов проверки.
                </p>
              </>
            )}
          </div>
        ) : null}

        {view.kind === 'summary' ? (
          <div className={styles.detail}>
            <p className={materials.summary.recorded ? styles.recorded : styles.proposal}>
              {materials.summary.recorded ? 'Записано вами' : 'Предложение помощника'}
            </p>
            <p className={styles.detailValue}>{materials.summary.line}</p>
            <p className={styles.muted}>
              Запись и изменение решения появятся вместе с экраном решения.
            </p>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
