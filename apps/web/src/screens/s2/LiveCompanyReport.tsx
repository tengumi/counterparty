import { Button } from '@alfalab/core-components/button';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { getOverview, getSection, reportKeys } from '../../api/reports';
import type {
  Assessment,
  DiscussionContext,
  ReportWarning,
  SectionName,
} from '../../api/reportContracts';
import { requestErrorMessage } from '../../api/messages';
import { usePersistentState } from './persisted';
import { availabilityText, factRow, recordRows, sectionTitles, sourceDate } from './liveReportView';
import type { DisplayRow } from './liveReportView';
import styles from './S2.module.css';

export function ReadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div role="alert">
      <p>{requestErrorMessage(error)}</p>
      <p className={styles.muted}>Сведения не загружены. Это не означает отсутствие риска.</p>
      <Button onClick={onRetry} size={40} view="outlined">
        Повторить загрузку
      </Button>
    </div>
  );
}
const warningMessages: Readonly<Record<string, string>> = {
  partial_data:
    'Некоторые поля не предоставлены или недоступны. Неизвестное значение не считается нулём.',
  not_comparable: 'Сопоставимого финансового периода для всех компаний нет.',
  incomplete_total: 'Показана известная часть суммы; значения с пропусками в неё не входят.',
};
export function Warnings({ warnings }: { warnings: readonly ReportWarning[] }) {
  return (
    <>
      {[
        ...new Set(
          warnings
            .filter((item) => item.code !== 'result_truncated')
            .map((item) => warningMessages[item.code] ?? item.message),
        ),
      ].map((message) => (
        <p className={styles.muted} key={message}>
          {message}
        </p>
      ))}
    </>
  );
}
export function ReportFactRow({
  row,
  companyName,
  onEvidence,
  onDiscuss,
}: {
  row: DisplayRow;
  companyName: string;
  onEvidence: (ref: string) => void;
  onDiscuss: (context: DiscussionContext) => void;
}) {
  const ref = row.refs[0];
  return (
    <div className={styles.factRow}>
      <span className={styles.factLabel}>{row.label}</span>
      <span className={styles.rowMain}>
        <span
          className={
            row.fact && row.fact.availability !== 'available' ? styles.unknown : styles.rowName
          }
        >
          {row.value}
        </span>
        {row.period != null ? <span className={styles.rowMeta}>{row.period} год</span> : null}
      </span>
      {ref ? (
        <span className={styles.factActions}>
          <Button
            aria-label={`Основание: ${row.label}`}
            onClick={() => onEvidence(ref)}
            size={32}
            view="text"
          >
            Основание
          </Button>
          <Button
            aria-label={`Обсудить: ${row.label}`}
            onClick={() =>
              onDiscuss({
                kind: 'evidence',
                evidence_ref: ref,
                label: `${row.label} · ${companyName}${row.period != null ? ` · ${row.period}` : ''}`,
              })
            }
            size={32}
            view="text"
          >
            Обсудить
          </Button>
        </span>
      ) : null}
    </div>
  );
}
function Signal({
  label,
  value,
  onEvidence,
}: {
  label: string;
  value: Assessment;
  onEvidence: (ref: string) => void;
}) {
  return (
    <div className={styles.signal}>
      <span className={`${styles.signalDot} ${styles[`tone_${value.display_level}`]}`} />
      <span className={styles.signalBody}>
        <span className={styles.signalValue}>
          {label} —{' '}
          {value.availability === 'available' && value.evidence_refs.length
            ? value.raw_value
            : availabilityText[value.availability]}
        </span>
        <span className={styles.signalNote}>
          {value.display_note ??
            'Самостоятельный сигнал источника; не заменяет оценку финансового положения.'}
        </span>
      </span>
      {value.evidence_refs[0] ? (
        <Button
          aria-label={`Основание: ${label}`}
          onClick={() => onEvidence(value.evidence_refs[0] as string)}
          size={32}
          view="text"
        >
          Основание
        </Button>
      ) : null}
    </div>
  );
}
function SectionContent({
  projectId,
  reportId,
  section,
  enabled,
  companyName,
  groupTitle,
  onEvidence,
  onDiscuss,
}: {
  projectId: string;
  reportId: string;
  section: SectionName;
  enabled: boolean;
  companyName: string;
  /** The parent group's title; the section heading is dropped when it repeats it. */
  groupTitle: string;
  onEvidence: (ref: string) => void;
  onDiscuss: (context: DiscussionContext) => void;
}) {
  const query = useInfiniteQuery({
    queryKey: reportKeys.section(projectId, reportId, section),
    enabled,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => getSection(reportId, section, pageParam),
    getNextPageParam: (last) => last.page.next_cursor ?? undefined,
    retry: false,
  });
  return (
    <section aria-label={sectionTitles[section]}>
      {sectionTitles[section] === groupTitle ? null : (
        <h5 className={styles.liveSectionTitle}>{sectionTitles[section]}</h5>
      )}
      {query.isPending ? (
        <p role="status">Загружаем раздел…</p>
      ) : query.isError && !query.data ? (
        <ReadError error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          {query.data?.pages.map((page, pageIndex) => (
            <div key={pageIndex}>
              {page.availability !== 'available' ? (
                <p className={styles.unknown}>
                  {availabilityText[page.availability]}. Отсутствие сведений не подтверждает
                  отсутствие событий.
                </p>
              ) : null}
              {page.facts.map((fact) => (
                <ReportFactRow
                  key={fact.key}
                  row={factRow(fact)}
                  companyName={companyName}
                  onEvidence={onEvidence}
                  onDiscuss={onDiscuss}
                />
              ))}
              {page.records.map((record, index) => {
                const view = recordRows(record);
                return (
                  <section className={styles.liveRecord} key={record.evidence_refs[0] ?? index}>
                    <h6 className={styles.liveRecordTitle}>{view.title}</h6>
                    {view.rows.map((row) => (
                      <ReportFactRow
                        key={row.key}
                        row={row}
                        companyName={companyName}
                        onEvidence={onEvidence}
                        onDiscuss={onDiscuss}
                      />
                    ))}
                    {view.note ? <p className={styles.muted}>{view.note}</p> : null}
                    {!view.rows.length && record.evidence_refs[0] ? (
                      <Button
                        onClick={() => onEvidence(record.evidence_refs[0] as string)}
                        size={40}
                        view="text"
                      >
                        Открыть основание записи
                      </Button>
                    ) : null}
                  </section>
                );
              })}
              <Warnings warnings={page.warnings} />
            </div>
          ))}
          {query.isFetchNextPageError ? (
            <ReadError error={query.error} onRetry={() => void query.fetchNextPage()} />
          ) : null}
          {query.hasNextPage ? (
            <Button
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
              size={40}
              view="outlined"
            >
              {query.isFetchingNextPage ? 'Загружаем…' : 'Показать ещё записи'}
            </Button>
          ) : null}
        </>
      )}
    </section>
  );
}
const groups: readonly { id: string; title: string; sections: readonly SectionName[] }[] = [
  { id: 'finance', title: 'Финансы', sections: ['financials', 'coefficients'] },
  { id: 'courts', title: 'Суды', sections: ['arbitration'] },
  { id: 'proceedings', title: 'Взыскания', sections: ['execution_proceedings'] },
  {
    id: 'activity',
    title: 'Деятельность и разрешения',
    sections: ['activities', 'licenses', 'inspections', 'procurements'],
  },
  {
    id: 'other',
    title: 'Другие сведения',
    sections: [
      'profile',
      'status',
      'founders',
      'tax_systems',
      'contacts',
      'related_companies',
      'branches',
      'risk_signals',
      'zsk',
    ],
  },
];
export function LiveCompanyReport({
  projectId,
  reportId,
  onEvidence,
  onDiscuss,
}: {
  projectId: string;
  reportId: string;
  onEvidence: (ref: string) => void;
  onDiscuss: (context: DiscussionContext) => void;
}) {
  const query = useQuery({
    queryKey: reportKeys.overview(projectId, reportId),
    queryFn: () => getOverview(reportId),
    retry: false,
  });
  const [expanded, setExpanded] = usePersistentState<readonly string[]>(
    `report-sections:${projectId}:${reportId}`,
    [],
    (value) =>
      Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : null,
  );
  if (query.isPending) return <p role="status">Загружаем сведения компании…</p>;
  if (query.isError) return <ReadError error={query.error} onRetry={() => void query.refetch()} />;
  const report = query.data;
  return (
    <div className={styles.detail}>
      <p className={styles.rowMeta}>
        ИНН {report.company.inn} · сведения на {sourceDate(report.report.source_report_at)}
      </p>
      <p className={styles.muted}>
        Предоставленный учебный снимок. Сведения не обновляются из реестров и не являются актуальной
        оценкой компании.
      </p>
      <div className={styles.signals}>
        <Signal label="Риск по оценке банка" value={report.bank_risk} onEvidence={onEvidence} />
        <Signal label="ЗСК" value={report.zsk} onEvidence={onEvidence} />
      </div>
      <ReportFactRow
        row={factRow({
          key: 'status',
          label: 'Статус источника',
          value: report.status.raw_value,
          value_type: 'enum',
          availability: report.status.availability,
          evidence_refs: report.status.evidence_refs,
          warnings: [],
        })}
        companyName={report.company.short_name}
        onEvidence={onEvidence}
        onDiscuss={onDiscuss}
      />
      <Warnings warnings={report.warnings} />
      <div className={styles.panelGroups}>
        {groups.map((group) => {
          const open = expanded.includes(group.id);
          const bodyId = `live-${reportId}-${group.id}`;
          return (
            <section className={styles.group} key={group.id}>
              <h4 className={styles.sectionHeading}>
                <button
                  className={styles.groupHeader}
                  aria-controls={bodyId}
                  aria-expanded={open}
                  onClick={() =>
                    setExpanded((current) =>
                      open ? current.filter((item) => item !== group.id) : [...current, group.id],
                    )
                  }
                  type="button"
                >
                  <span className={styles.groupTitle}>{group.title}</span>
                  <span className={styles.groupCount}>{open ? 'Свернуть' : 'Раскрыть'}</span>
                </button>
              </h4>
              <div className={styles.groupBody} hidden={!open} id={bodyId}>
                {group.sections.map((section) => (
                  <SectionContent
                    key={section}
                    projectId={projectId}
                    reportId={reportId}
                    section={section}
                    enabled={open}
                    companyName={report.company.short_name}
                    groupTitle={group.title}
                    onEvidence={onEvidence}
                    onDiscuss={onDiscuss}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
