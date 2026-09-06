import { Button } from '@alfalab/core-components/button';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { getOverview, getReportSummary, getSection, reportKeys } from '../../api/reports';
import type {
  DiscussionContext,
  ReportWarning,
  SectionName,
} from '../../api/reportContracts';
import { requestErrorMessage } from '../../api/messages';
import { FinancialTable } from './report/FinancialTable';
import { ReportOverview } from './report/ReportOverview';
import reportStyles from './report/Report.module.css';
import { availabilityText, factRow, recordRows, sectionTitles, sourceDate } from './liveReportView';
import { ReportFactRow } from './report/ReportFactRow';
export { ReportFactRow } from './report/ReportFactRow';
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
/**
 * Internal snapshot bookkeeping the source attaches to a section — the moment
 * the data was captured and a "CURRENT / ARCHIVE" freshness flag. Not a fact
 * about the company, so it does not belong in the report.
 */
function isSnapshotMeta(fact: { key: string; value: unknown }): boolean {
  const leaf = fact.key.split(/[./]/).at(-1) ?? '';
  const value = String(fact.value ?? '').trim();
  if (/^(CURRENT|ACTUAL|ARCHIVE|OUTDATED|HISTORICAL)$/i.test(value)) return true;
  if (leaf === 'date' && /^\d{4}-\d\d-\d\dT/.test(value)) return true;
  return false;
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
              {page.facts.filter((fact) => !isSnapshotMeta(fact)).map((fact) => (
                <ReportFactRow
                  key={fact.key}
                  row={factRow(fact)}
                  section={section}
                  companyName={companyName}
                  onEvidence={onEvidence}
                  onDiscuss={onDiscuss}
                />
              ))}
              {section === 'financials' ? <FinancialTable
                records={page.records} companyName={companyName}
                onEvidence={onEvidence} onDiscuss={onDiscuss}
              /> : null}
              {(section === 'risk_signals'
                ? [...page.records].sort((a, b) => {
                    const w = (r: typeof a) =>
                      r.kind === 'risk_signal' && r.polarity === 'negative' ? 0 : 1;
                    return w(a) - w(b);
                  })
                : page.records
              ).map((record, index) => {
                const view = record.kind === 'financial_period'
                  ? { title: `${record.year} · Дополнительные показатели`, rows: record.additional_facts.map(factRow), note: null }
                  : recordRows(record);
                if (record.kind === 'financial_period' && !view.rows.length) return null;
                return (
                  <section className={styles.liveRecord} key={record.evidence_refs[0] ?? index}>
                    <h6 className={styles.liveRecordTitle}>{view.title}</h6>
                    {view.rows.map((row) => (
                      <ReportFactRow
                        key={row.key}
                        row={row}
                        section={section}
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
  // 'status' is left out on purpose: for the live report it carries only the
  // source's snapshot date and a CURRENT/ARCHIVE flag, nothing about the company.
  { id: 'profile', title: 'Кто эта компания', sections: ['profile', 'activities', 'tax_systems'] },
  { id: 'finance', title: 'Финансы', sections: ['financials', 'coefficients'] },
  { id: 'owners', title: 'Владельцы и управление', sections: ['founders'] },
  { id: 'courts', title: 'Судебные споры', sections: ['arbitration'] },
  { id: 'proceedings', title: 'Долги у приставов', sections: ['execution_proceedings'] },
  { id: 'experience', title: 'Опыт, разрешения и проверки', sections: ['procurements', 'licenses', 'inspections'] },
  { id: 'other', title: 'Связи и другие сведения', sections: ['related_companies', 'branches', 'contacts', 'risk_signals', 'zsk'] },
];
/**
 * The task-aware orientation block at the top of the report (mockup pReport).
 *
 * It is the assistant's read of this report *for the user's task* — explicitly
 * not a bank rating. It loads lazily and stays silent if the assistant can't
 * build it: the raw sections below are the report either way.
 */
function ReportSummaryBlock({
  projectId,
  reportId,
  onDiscuss,
}: {
  projectId: string;
  reportId: string;
  onDiscuss: (text: string) => void;
}) {
  const query = useQuery({
    queryKey: [...reportKeys.project(projectId), reportId, 'summary'],
    queryFn: () => getReportSummary(projectId, reportId),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
  if (query.isPending) {
    return (
      <div className={reportStyles.summary}>
        <p className={reportStyles.summaryTitle}>На что обратить внимание</p>
        <p className={reportStyles.summaryLoading} role="status">
          Помощник читает отчёт под вашу задачу…
        </p>
      </div>
    );
  }
  if (query.isError || query.data.bullets.length === 0) return null;
  const { bullets, caveat } = query.data;
  return (
    <div className={reportStyles.summary}>
      <p className={reportStyles.summaryTitle}>На что обратить внимание</p>
      <ul className={reportStyles.summaryList}>
        {bullets.map((bullet, index) => (
          <li className={reportStyles.summaryItem} key={index} data-tone={bullet.tone}>
            <span aria-hidden="true" className={reportStyles.summaryDot} data-tone={bullet.tone} />
            <span className={reportStyles.summaryText}>{bullet.text}</span>
            <button
              className={reportStyles.summaryDiscuss}
              onClick={() => onDiscuss(`Про пункт из отчёта: «${bullet.text}» — что это значит для сделки?`)}
              type="button"
            >
              Обсудить
            </button>
          </li>
        ))}
      </ul>
      {caveat ? <p className={reportStyles.summaryCaveat}>{caveat}</p> : null}
    </div>
  );
}

export function LiveCompanyReport({
  projectId,
  reportId,
  onEvidence,
  onDiscuss,
}: {
  projectId: string;
  reportId: string;
  onEvidence: (ref: string) => void;
  onDiscuss: (context: string | DiscussionContext) => void;
}) {
  const query = useQuery({
    queryKey: reportKeys.overview(projectId, reportId),
    queryFn: () => getOverview(reportId),
    retry: false,
  });
  if (query.isPending) return <p role="status">Загружаем сведения компании…</p>;
  if (query.isError) return <ReadError error={query.error} onRetry={() => void query.refetch()} />;
  const report = query.data;
  return (
    <div className={reportStyles.report}>
      <div className={reportStyles.companyHeading}>
        <h2>{report.company.short_name}</h2>
        <span>ИНН {report.company.inn} · срез {sourceDate(report.report.source_report_at)}</span>
      </div>
      <ReportSummaryBlock projectId={projectId} reportId={reportId} onDiscuss={onDiscuss} />
      <ReportOverview report={report} onEvidence={onEvidence} />
      <div className={reportStyles.sections}>
        {groups.map((group) => (
          <section className={reportStyles.section} key={group.id}>
            <h3>{group.title}</h3>
            {group.sections.map((section) => (
              <SectionContent
                key={section}
                projectId={projectId}
                reportId={reportId}
                section={section}
                enabled={true}
                companyName={report.company.short_name}
                groupTitle={group.title}
                onEvidence={onEvidence}
                onDiscuss={onDiscuss}
              />
            ))}
          </section>
        ))}
      </div>
      <p className={reportStyles.sourceNote}>
        Предоставленный учебный снимок. Сведения не обновляются из реестров и не являются актуальной оценкой компании.
      </p>
      <Warnings warnings={report.warnings} />
    </div>
  );
}
