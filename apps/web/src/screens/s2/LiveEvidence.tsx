import { useState } from 'react';
import { Button } from '@alfalab/core-components/button';
import { useQuery } from '@tanstack/react-query';
import { getEvidence, getOverview, reportKeys } from '../../api/reports';
import type { DiscussionContext } from '../../api/reportContracts';
import { ReadError, Warnings } from './LiveCompanyReport';
import {
  availabilityText,
  evidenceSection,
  evidenceTitle,
  fragmentRows,
  sourceDate,
} from './liveReportView';
import styles from './S2.module.css';

export function LiveEvidence({
  projectId,
  evidenceRef,
  onDiscuss,
}: {
  projectId: string;
  evidenceRef: string;
  onDiscuss: (context: DiscussionContext) => void;
}) {
  const query = useQuery({
    queryKey: reportKeys.evidence(projectId, evidenceRef),
    queryFn: () => getEvidence(projectId, evidenceRef),
    retry: false,
  });
  const reportId = query.data?.report.id ?? '';
  const overview = useQuery({
    queryKey: reportKeys.overview(projectId, reportId),
    queryFn: () => getOverview(reportId),
    enabled: Boolean(reportId),
    retry: false,
  });
  const [limit, setLimit] = useState(20);
  if (query.isPending) return <p role="status">Загружаем основание…</p>;
  if (query.isError) return <ReadError error={query.error} onRetry={() => void query.refetch()} />;
  const evidence = query.data;
  const title = evidenceTitle(evidence.evidence.source_path);
  const period =
    evidence.evidence.period ??
    overview.data?.facts.find((fact) => fact.evidence_refs.includes(evidenceRef))?.period;
  const rows =
    evidence.availability === 'available' || evidence.availability === 'present_empty'
      ? fragmentRows(evidence.value, title)
      : [];
  const companyName = overview.data?.company.short_name ?? 'Компания из предоставленного отчёта';
  return (
    <div className={styles.detail}>
      <p className={styles.detailTitle}>{title}</p>
      {evidence.availability !== 'available' ? (
        <p className={styles.unknown}>
          {availabilityText[evidence.availability]}. Это не означает отсутствие риска.
        </p>
      ) : null}
      <dl className={styles.detailList}>
        <dt>Компания</dt>
        <dd>{companyName}</dd>
        <dt>Период</dt>
        <dd>{period ?? 'Не указан в основании'}</dd>
        <dt>Откуда</dt>
        <dd>Предоставленный отчёт · {evidenceSection(evidence.evidence.source_path)}</dd>
        <dt>Дата среза</dt>
        <dd>{sourceDate(evidence.report.source_report_at)}</dd>
      </dl>
      <div aria-label="Исходный фрагмент">
        {rows.slice(0, limit).map((row, index) => (
          <div className={styles.liveSourceRow} key={index}>
            <span className={styles.rowMeta}>{row.label}</span>
            <span className={styles.rowName}>{row.value}</span>
          </div>
        ))}
      </div>
      {rows.length > limit ? (
        <Button onClick={() => setLimit((value) => value + 20)} size={40} view="outlined">
          Показать ещё сведения
        </Button>
      ) : null}
      <Warnings warnings={evidence.warnings} />
      <p className={styles.rowMeta}>
        Первоисточник — предоставленный отчёт; отдельной ссылки на реестр у этого значения нет.
      </p>
      <Button
        onClick={() =>
          onDiscuss({
            kind: 'evidence',
            evidence_ref: evidenceRef,
            label: `${title} · ${companyName}${period ? ` · ${period}` : ''}`,
          })
        }
        size={40}
        view="outlined"
      >
        Обсудить
      </Button>
    </div>
  );
}
