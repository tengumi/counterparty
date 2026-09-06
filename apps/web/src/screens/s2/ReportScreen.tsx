/**
 * Full-screen report view (mockup `pReport`).
 *
 * The company report and the comparison are the two heavy reads of a check, so
 * they get the whole surface instead of the 400 px materials panel: a top bar
 * with «← К разговору», the «Отчёт» title and a Компания / Сравнение switch,
 * then a centred column. A basis opened from inside slides in as a drawer over
 * the report — the panel stays reserved for the lighter materials.
 *
 * Behaviour and REST are untouched: this only re-hosts `LiveCompanyReport` and
 * `Comparison`, which keep their own queries, evidence and discuss callbacks.
 */

import { useState } from 'react';
import { Button } from '@alfalab/core-components/button';
import type { ApiProject } from '../../api/contracts';
import type { DiscussionContext } from '../../api/reportContracts';
import type { ProjectDetail } from '../../mocks/types';
import { LiveCompanyReport } from './LiveCompanyReport';
import { LiveEvidence } from './LiveEvidence';
import { Comparison } from './Comparison';
import styles from './S2.module.css';

type Mode = 'company' | 'comparison';

interface Props {
  readonly project: ProjectDetail;
  readonly apiProject: ApiProject;
  readonly initialMode: Mode;
  readonly initialCompanyId?: string;
  readonly onClose: () => void;
  /** Closes the report and drops a context chip into the composer. */
  readonly onDiscuss: (context: string | DiscussionContext) => void;
}

export function ReportScreen({
  project,
  apiProject,
  initialMode,
  initialCompanyId,
  onClose,
  onDiscuss,
}: Props) {
  const withReport = project.companies.filter((company) => company.reportId);
  const canCompare = project.companies.length >= 2;
  const [mode, setMode] = useState<Mode>(
    initialMode === 'comparison' && canCompare ? 'comparison' : 'company',
  );
  const [companyId, setCompanyId] = useState<string>(
    initialCompanyId ?? withReport[0]?.id ?? project.companies[0]?.id ?? '',
  );
  const [evidenceRef, setEvidenceRef] = useState<string | null>(null);

  const company = project.companies.find((item) => item.id === companyId) ?? withReport[0];
  const discuss = (context: string | DiscussionContext) => {
    setEvidenceRef(null);
    onDiscuss(context);
  };

  return (
    <section aria-label="Отчёт" className={styles.reportScreen}>
      <div className={styles.reportBar}>
        <Button className={styles.reportBack} onClick={onClose} size={32} view="text">
          ← К разговору
        </Button>
        <span className={styles.divider} />
        <span className={styles.reportBarTitle}>Отчёт</span>
        {canCompare ? (
          <div className={styles.reportModes} role="group" aria-label="Что показать">
            <button
              aria-pressed={mode === 'company'}
              className={styles.reportMode}
              onClick={() => setMode('company')}
              type="button"
            >
              Компания
            </button>
            <button
              aria-pressed={mode === 'comparison'}
              className={styles.reportMode}
              onClick={() => setMode('comparison')}
              type="button"
            >
              Сравнение · {project.companies.length}
            </button>
          </div>
        ) : null}
        {mode === 'company' && withReport.length > 1 ? (
          <label className={styles.reportPick}>
            <span className={styles.visuallyHidden}>Компания отчёта</span>
            <select value={companyId} onChange={(event) => setCompanyId(event.target.value)}>
              {withReport.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <span className={styles.reportBarNote}>Из закреплённого отчёта</span>
      </div>

      <div className={styles.reportBody}>
        <div className={styles.reportColumn}>
          {mode === 'comparison' ? (
            <Comparison
              onDiscuss={discuss}
              onEvidence={(ref) => setEvidenceRef(ref)}
              project={apiProject}
            />
          ) : company?.reportId ? (
            <LiveCompanyReport
              key={company.reportId}
              onDiscuss={discuss}
              onEvidence={(ref) => setEvidenceRef(ref)}
              projectId={project.id}
              reportId={company.reportId}
            />
          ) : (
            <p className={styles.muted}>
              У этой компании нет закреплённого отчёта в демонстрационной базе. Это не проверка без
              замечаний — сведений просто нет.
            </p>
          )}
        </div>
      </div>

      {evidenceRef ? (
        <>
          <button
            aria-label="Закрыть основание"
            className={styles.reportDrawerBackdrop}
            onClick={() => setEvidenceRef(null)}
            tabIndex={-1}
            type="button"
          />
          <aside aria-label="Основание" className={`${styles.panel} ${styles.reportDrawer}`}>
            <div className={styles.panelHeader}>
              <span className={styles.panelBack}>
                <Button onClick={() => setEvidenceRef(null)} size={32} view="text">
                  К отчёту
                </Button>
              </span>
              <h2 className={styles.panelTitle}>Основание</h2>
              <span className={styles.panelClose}>
                <Button
                  aria-label="Закрыть основание — вернуться к отчёту"
                  onClick={() => setEvidenceRef(null)}
                  size={40}
                  view="text"
                >
                  Закрыть
                </Button>
              </span>
            </div>
            <div className={styles.panelBody}>
              <LiveEvidence
                evidenceRef={evidenceRef}
                key={evidenceRef}
                onDiscuss={discuss}
                projectId={project.id}
              />
            </div>
          </aside>
        </>
      ) : null}
    </section>
  );
}
