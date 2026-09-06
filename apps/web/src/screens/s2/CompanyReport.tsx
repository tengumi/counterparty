/**
 * P1-02 — the provided report of one company inside the materials panel.
 *
 * The screen shows the sections of the report with their availability, and
 * every factual row opens the basis behind it in the same panel. Four kinds of
 * «no number» stay distinct — a missing block, a checked-and-empty list, a
 * restricted block and a confirmed zero — and none of them is drawn as a clean
 * result. The two external signals are shown with their raw values.
 */

import { Button } from '@alfalab/core-components/button';
import type { CompanyReport as Report, ReportSection } from '../../mocks/types';
import { sectionAvailabilityLabels } from '../../mocks/types';
import { findEvidence } from '../../mocks/workspace';
import type { SignalView } from './reportView';
import {
  WITHHELD_VALUE_TEXT,
  describeBankRisk,
  describeZsk,
  resolveFact,
} from './reportView';
import { usePersistentState } from './persisted';
import styles from './S2.module.css';

interface Props {
  readonly report: Report;
  readonly projectId: string;
  /** Opens the basis of a row; the panel keeps its own navigation stack. */
  readonly onOpenEvidence: (evidenceId: string) => void;
  /** Puts a removable context chip into the composer (07 S2-08). */
  readonly onDiscuss: (text: string) => void;
}

const sectionNotes: Readonly<Record<'missing' | 'unavailable', string>> = {
  missing: 'Раздел не предоставлен в этом отчёте. Это не подтверждение, что событий не было.',
  unavailable: 'Доступ к разделу ограничен. Отсутствие сведений не означает отсутствие риска.',
};

function Signal({
  signal,
  onOpenEvidence,
}: {
  signal: SignalView;
  onOpenEvidence: (evidenceId: string) => void;
}) {
  return (
    <div className={styles.signal}>
      <span className={`${styles.signalDot} ${styles[`tone_${signal.tone}`]}`} />
      <span className={styles.signalBody}>
        <span className={styles.signalValue}>
          {signal.label} — {signal.valueLabel}
        </span>
        <span className={styles.signalNote}>{signal.note}</span>
        <span className={styles.signalRaw}>Исходное значение: {signal.raw}</span>
      </span>
      <Button
        className={styles.signalAction}
        onClick={() => onOpenEvidence(signal.evidenceId)}
        size={32}
        view="text"
      >
        Основание
      </Button>
    </div>
  );
}

function Section({
  section,
  report,
  expanded,
  onToggle,
  onOpenEvidence,
  onDiscuss,
}: {
  section: ReportSection;
  report: Report;
  expanded: boolean;
  onToggle: () => void;
  onOpenEvidence: (evidenceId: string) => void;
  onDiscuss: (text: string) => void;
}) {
  const bodyId = `report-${report.companyId}-${section.id}`;
  const hint =
    section.availability === 'available'
      ? (section.hint ?? sectionAvailabilityLabels.available)
      : sectionAvailabilityLabels[section.availability];

  return (
    <section className={styles.group}>
      <h4 className={styles.sectionHeading}>
        <button
          aria-controls={bodyId}
          aria-expanded={expanded}
          className={styles.groupHeader}
          onClick={onToggle}
          type="button"
        >
          <span className={styles.groupTitle}>{section.title}</span>
          <span
            className={
              section.availability === 'available' ? styles.groupCount : styles.unknown
            }
          >
            {hint}
          </span>
        </button>
      </h4>
      <div className={styles.groupBody} hidden={!expanded} id={bodyId}>
        {section.availability !== 'available' ? (
          <p className={styles.muted}>{sectionNotes[section.availability]}</p>
        ) : (
          section.facts.map((fact) => {
            const resolved = resolveFact(fact, findEvidence);
            if (resolved.kind === 'withheld') {
              return (
                <div className={styles.factRow} key={fact.id}>
                  <span className={styles.factLabel}>{fact.label}</span>
                  <span className={styles.rowMain}>
                    <span className={styles.unknown}>{WITHHELD_VALUE_TEXT}</span>
                  </span>
                </div>
              );
            }
            return (
              <div className={styles.factRow} key={fact.id}>
                <span className={styles.factLabel}>{fact.label}</span>
                <span className={styles.rowMain}>
                  <span
                    className={resolved.tone === 'known' ? styles.rowName : styles.unknown}
                  >
                    {resolved.display}
                  </span>
                  {resolved.note === null ? null : (
                    <span className={styles.rowMeta}>{resolved.note}</span>
                  )}
                </span>
                <span className={styles.factActions}>
                  <Button
                    onClick={() => onOpenEvidence(resolved.evidence.id)}
                    size={32}
                    view="text"
                  >
                    <span className={styles.visuallyHidden}>Основание: {fact.label}</span>
                    <span aria-hidden="true">Основание</span>
                  </Button>
                  <Button
                    onClick={() =>
                      onDiscuss(
                        `${fact.label} · ${report.companyName} · ${resolved.evidence.period}`,
                      )
                    }
                    size={32}
                    view="text"
                  >
                    <span className={styles.visuallyHidden}>Обсудить: {fact.label}</span>
                    <span aria-hidden="true">Обсудить</span>
                  </Button>
                </span>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

export function CompanyReport({ report, projectId, onOpenEvidence, onDiscuss }: Props) {
  const [expanded, setExpanded] = usePersistentState<readonly string[]>(
    `report-sections:${projectId}:${report.companyId}`,
    [],
    (value) => Array.isArray(value) && value.every((item) => typeof item === 'string') ? value as string[] : null,
  );

  const toggle = (id: string) =>
    setExpanded((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );

  return (
    <div className={styles.detail}>
      <p className={styles.rowMeta}>
        ИНН {report.inn} · сведения на {report.asOf}
      </p>
      {report.educational ? (
        <p className={styles.muted}>
          Учебный пример. Отчёт не является актуальной оценкой реальной компании.
        </p>
      ) : null}
      {report.asOfStale ? (
        <p className={styles.unknown}>
          Срез старше 30 дней. Изменения после {report.asOf} в отчёт не попали.
        </p>
      ) : null}

      <div className={styles.signals}>
        <Signal
          onOpenEvidence={onOpenEvidence}
          signal={describeBankRisk(report.bankRiskRaw, report.bankRiskEvidenceId)}
        />
        <Signal
          onOpenEvidence={onOpenEvidence}
          signal={describeZsk(report.zskRaw, report.zskEvidenceId)}
        />
      </div>

      <div className={styles.panelGroups}>
        {report.sections.map((section) => (
          <Section
            expanded={expanded.includes(section.id)}
            key={section.id}
            onDiscuss={onDiscuss}
            onOpenEvidence={onOpenEvidence}
            onToggle={() => toggle(section.id)}
            report={report}
            section={section}
          />
        ))}
      </div>
    </div>
  );
}
