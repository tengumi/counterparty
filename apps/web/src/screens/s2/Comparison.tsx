import { Button } from '@alfalab/core-components/button';
import { Checkbox } from '@alfalab/core-components/checkbox';
import { Input } from '@alfalab/core-components/input';
import { useQuery } from '@tanstack/react-query';
import type { ApiProject } from '../../api/contracts';
import type {
  ComparisonCriterion,
  ComparisonInput,
  DiscussionContext,
} from '../../api/reportContracts';
import { compareReports, reportKeys } from '../../api/reports';
import { ReadError, Warnings } from './LiveCompanyReport';
import { factLabel, factText, sourceDate } from './liveReportView';
import { usePersistentState } from './persisted';
import styles from './S2.module.css';

const criterionLabels: Readonly<Record<ComparisonCriterion, string>> = {
  bank_risk: 'Риск банка',
  status: 'Статус',
  financials: 'Финансы',
  proceedings: 'Взыскания',
  arbitration: 'Суды',
  activities: 'Деятельность',
  licenses: 'Лицензии',
  procurement: 'Госзакупки',
};
const defaultCriteria: readonly ComparisonCriterion[] = [
  'bank_risk',
  'status',
  'financials',
  'proceedings',
];
function parseComparison(value: unknown): ComparisonInput | null {
  if (typeof value !== 'object' || value === null) return null;
  const raw = value as Partial<ComparisonInput>;
  if (
    !Array.isArray(raw.report_ids) ||
    !raw.report_ids.every((item) => typeof item === 'string') ||
    !Array.isArray(raw.criteria) ||
    !raw.criteria.every((item) => item in criterionLabels)
  )
    return null;
  if (!['common_latest', 'latest_available', 'explicit'].includes(raw.year_policy ?? ''))
    return null;
  if (raw.year != null && (!Number.isInteger(raw.year) || raw.year < 1900 || raw.year > 2200))
    return null;
  return raw as ComparisonInput;
}
function parseNullableComparison(value: unknown): ComparisonInput | null {
  return parseComparison(value);
}
export function Comparison({
  project,
  onEvidence,
  onDiscuss,
}: {
  project: ApiProject;
  onEvidence: (ref: string) => void;
  onDiscuss: (context: DiscussionContext) => void;
}) {
  const [selection, setSelection] = usePersistentState<ComparisonInput>(
    `comparison-selection:${project.id}`,
    {
      report_ids: project.companies.map((company) => company.report_id),
      criteria: defaultCriteria,
      year_policy: 'latest_available',
    },
    parseComparison,
  );
  const [submitted, setSubmitted] = usePersistentState<ComparisonInput | null>(
    `comparison-result:${project.id}`,
    null,
    parseNullableComparison,
  );
  const pins = new Set(project.companies.map((company) => company.report_id));
  const selected = selection.report_ids.filter((id) => pins.has(id));
  const valid =
    selected.length >= 2 &&
    selected.length <= 20 &&
    selection.criteria.length > 0 &&
    (selection.year_policy !== 'explicit' ||
      (selection.year != null &&
        Number.isInteger(selection.year) &&
        selection.year >= 1900 &&
        selection.year <= 2200));
  const ready =
    submitted !== null &&
    submitted.report_ids.length >= 2 &&
    submitted.report_ids.length <= 20 &&
    submitted.report_ids.every((id) => pins.has(id));
  const query = useQuery({
    queryKey: reportKeys.comparison(project.id, project.context_version, submitted ?? selection),
    queryFn: () => compareReports(project.id, submitted as ComparisonInput),
    enabled: ready,
    retry: false,
  });
  const toggleReport = (reportId: string) =>
    setSelection({
      ...selection,
      report_ids: selected.includes(reportId)
        ? selected.filter((id) => id !== reportId)
        : [...selected, reportId],
    });
  const columns = [
    ...new Map(
      query.data?.rows.flatMap((row) =>
        row.cells.map((cell) => [cell.key, factLabel(cell)] as const),
      ) ?? [],
    ).entries(),
  ];
  return (
    <div className={styles.detail}>
      <p className={styles.rowMeta}>Сравнение для: {project.title}</p>
      <p className={styles.muted}>
        Факты из закреплённых отчётов. Неизвестные условия не считаются худшими; автоматического
        победителя нет.
      </p>
      <fieldset className={styles.comparisonOptions}>
        <legend>Компании для сравнения — от 2 до 20</legend>
        {project.companies.map((company) => (
          <Checkbox
            key={company.company_id}
            label={`${company.short_name} · ИНН ${company.inn}`}
            checked={selected.includes(company.report_id)}
            onChange={() => toggleReport(company.report_id)}
          />
        ))}
      </fieldset>
      <fieldset className={styles.comparisonOptions}>
        <legend>Что сравнить</legend>
        {(Object.keys(criterionLabels) as ComparisonCriterion[]).map((criterion) => (
          <Checkbox
            key={criterion}
            label={criterionLabels[criterion]}
            checked={selection.criteria.includes(criterion)}
            onChange={() =>
              setSelection({
                ...selection,
                criteria: selection.criteria.includes(criterion)
                  ? selection.criteria.filter((item) => item !== criterion)
                  : [...selection.criteria, criterion],
              })
            }
          />
        ))}
      </fieldset>
      <label className={styles.liveSelect}>
        Финансовый период
        <select
          value={selection.year_policy}
          onChange={(event) =>
            setSelection({
              report_ids: selection.report_ids,
              criteria: selection.criteria,
              year_policy: event.target.value as ComparisonInput['year_policy'],
            })
          }
        >
          <option value="latest_available">Последний доступный у каждой компании</option>
          <option value="common_latest">Последний общий для всех</option>
          <option value="explicit">Указать год</option>
        </select>
      </label>
      {selection.year_policy === 'explicit' ? (
        <Input
          label="Год сравнения"
          type="number"
          min={1900}
          max={2200}
          value={selection.year?.toString() ?? ''}
          onChange={(_event, payload) =>
            setSelection({ ...selection, year: payload.value ? Number(payload.value) : undefined })
          }
          block={true}
        />
      ) : null}
      <Button
        disabled={!valid || query.isFetching}
        onClick={() => {
          const next: ComparisonInput = { ...selection, report_ids: selected };
          setSubmitted(next);
          if (JSON.stringify(next) === JSON.stringify(submitted)) void query.refetch();
        }}
        size={40}
        view="outlined"
      >
        Сравнить выбранные ({selected.length})
      </Button>
      {!valid ? (
        <p className={styles.muted}>
          Выберите от 2 до 20 компаний и хотя бы один критерий
          {selection.year_policy === 'explicit' ? ', укажите год' : ''}.
        </p>
      ) : null}
      {submitted && !ready ? (
        <p className={styles.unknown}>
          Состав проверки изменился. Выберите компании и обновите сравнение.
        </p>
      ) : null}
      {ready && query.isPending ? <p role="status">Сопоставляем сведения…</p> : null}
      {ready && query.isError ? (
        <ReadError error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {ready && query.data ? (
        <section aria-label="Результат сравнения">
          <h3>Сравнение {query.data.rows.length} компаний</h3>
          <p className={styles.rowMeta}>
            Критерии результата:{' '}
            {query.data.criteria.map((criterion) => criterionLabels[criterion]).join(', ')}. Период:{' '}
            {query.data.year_policy === 'explicit'
              ? query.data.year
              : query.data.year_policy === 'common_latest'
                ? 'последний общий для всех'
                : 'последний доступный у каждой компании'}
            .
          </p>
          <Warnings warnings={query.data.warnings} />
          <div
            className={styles.comparisonScroll}
            tabIndex={0}
            aria-label="Таблица сравнения с горизонтальной прокруткой"
          >
            <table className={styles.comparisonTable}>
              <thead>
                <tr>
                  <th scope="col">Компания</th>
                  {columns.map(([key, label]) => (
                    <th scope="col" key={key}>
                      {label}
                    </th>
                  ))}
                  <th scope="col">Условия предложения</th>
                </tr>
              </thead>
              <tbody>
                {query.data.rows.map((row) => (
                  <tr key={row.report.id}>
                    <th scope="row">
                      <span>{row.company.short_name}</span>
                      <span className={styles.rowMeta}>ИНН {row.company.inn}</span>
                      <span className={styles.rowMeta}>
                        {sourceDate(row.report.source_report_at)}
                      </span>
                      {row.status !== 'complete' ? (
                        <span className={styles.unknown}>
                          {row.status === 'partial'
                            ? 'Часть сведений недоступна'
                            : 'Сведения недоступны'}
                        </span>
                      ) : null}
                    </th>
                    {columns.map(([key]) => {
                      const cell = row.cells.find((item) => item.key === key);
                      return (
                        <td key={key}>
                          {cell ? (
                            <>
                              <span>{factText(cell)}</span>
                              {cell.period != null ? (
                                <span className={styles.rowMeta}>{cell.period} год</span>
                              ) : null}
                              {cell.evidence_refs[0] ? (
                                <Button
                                  aria-label={`Основание: ${row.company.short_name}, ${factLabel(cell)}`}
                                  onClick={() => onEvidence(cell.evidence_refs[0] as string)}
                                  size={32}
                                  view="text"
                                >
                                  Основание
                                </Button>
                              ) : null}
                            </>
                          ) : (
                            'Не предоставлено'
                          )}
                        </td>
                      );
                    })}
                    <td>Пока недоступны</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={styles.muted}>
            Результат относится к выбранным отчётам и критериям. Сохранение отдельного материала
            сравнения пока недоступно.
          </p>
          <Button
            onClick={() =>
              onDiscuss({
                kind: 'comparison',
                label: `Сравнение ${query.data.rows.length} компаний`,
                selection: submitted as ComparisonInput,
              })
            }
            size={40}
            view="outlined"
          >
            Обсудить сравнение
          </Button>
        </section>
      ) : null}
    </div>
  );
}
