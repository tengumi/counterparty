/**
 * Provided company reports of the mock workspace (WEB-06).
 *
 * Values keep the shape of the accepted snapshot `contractors_audit.snapshot`
 * (records 7449088645, 5029069967 and 7728380537), so what the panel shows is
 * as ragged as the real export: some sections are absent, some are checked and
 * empty, one is restricted and one number is a confirmed zero.
 *
 * Every row of a report is written together with its basis: the registry below
 * is built from the rows themselves, so a fact that could be rendered without
 * an `evidence_ref` simply cannot be described here. WEB-08 replaces the two
 * accessors with REST calls; the types the components see do not change.
 */

import type {
  CompanyReport,
  EvidenceRecord,
  FactState,
  ReportFact,
  ReportSection,
  SectionAvailability,
} from './types';
import { factStateLabels } from './types';

interface FactSeed {
  readonly id: string;
  readonly label: string;
  readonly state?: FactState;
  readonly value?: string;
  readonly note?: string;
  /** Reporting period of this row; never the date of the check. */
  readonly period: string;
  /** What the value does not say, when that is easy to misread. */
  readonly context?: string;
  /** Number of this row inside the demo answer, if it is cited there. */
  readonly number?: number;
  readonly documentId?: string;
}

interface SectionSeed {
  readonly id: string;
  readonly title: string;
  readonly hint?: string;
  readonly availability?: SectionAvailability;
  readonly facts?: readonly FactSeed[];
}

interface ReportSeed {
  readonly companyId: string;
  readonly companyName: string;
  readonly inn: string;
  readonly asOf: string;
  readonly asOfStale?: boolean;
  readonly bankRiskRaw: string;
  readonly zskRaw: string;
  readonly signalPeriod: string;
  readonly sections: readonly SectionSeed[];
}

const registry = new Map<string, EvidenceRecord>();

function remember(record: EvidenceRecord): string {
  registry.set(record.id, record);
  return record.id;
}

function buildFact(seed: FactSeed, report: ReportSeed, section: SectionSeed): ReportFact {
  const state = seed.state ?? 'value';
  const known = state === 'value' || state === 'zero';
  const value = known ? (seed.value ?? '') : null;
  const evidenceId = remember({
    id: seed.id,
    number: seed.number ?? null,
    title: seed.label,
    value: known ? (value ?? '') : factStateLabels[state as 'missing' | 'empty' | 'unavailable'],
    companyName: report.companyName,
    period: seed.period,
    source:
      seed.documentId === undefined
        ? `Предоставленный отчёт, раздел «${section.title}»`
        : 'Загруженный документ',
    asOf: report.asOf,
    context: seed.context ?? null,
    documentId: seed.documentId ?? null,
  });

  return {
    id: seed.id,
    label: seed.label,
    state,
    value,
    note: seed.note ?? null,
    evidenceId,
  };
}

function buildReport(seed: ReportSeed): CompanyReport {
  const sections: readonly ReportSection[] = seed.sections.map((section) => ({
    id: section.id,
    title: section.title,
    hint: section.hint ?? null,
    availability: section.availability ?? 'available',
    facts: (section.facts ?? []).map((fact) => buildFact(fact, seed, section)),
  }));

  const signals: SectionSeed = { id: 'signals', title: 'Оценки' };
  const bankRiskEvidenceId = buildFact(
    {
      id: `ev-${seed.companyId}-bank`,
      label: 'Риск по оценке банка',
      value: seed.bankRiskRaw,
      period: seed.signalPeriod,
      context: 'Не заменяет оценку финансового положения.',
    },
    seed,
    signals,
  ).evidenceId;
  const zskEvidenceId = buildFact(
    {
      id: `ev-${seed.companyId}-zsk`,
      label: 'ЗСК',
      value: seed.zskRaw,
      period: seed.signalPeriod,
      context: 'Внешний сигнал платформы «Знай своего клиента». Значение показано как есть.',
    },
    seed,
    signals,
  ).evidenceId;

  return {
    companyId: seed.companyId,
    companyName: seed.companyName,
    inn: seed.inn,
    asOf: seed.asOf,
    asOfStale: seed.asOfStale ?? false,
    educational: true,
    bankRiskRaw: seed.bankRiskRaw,
    bankRiskEvidenceId,
    zskRaw: seed.zskRaw,
    zskEvidenceId,
    sections,
  };
}

const companyA = buildReport({
  companyId: 'company-a',
  companyName: 'Компания А',
  inn: '7449088645',
  asOf: '5 августа 2026',
  bankRiskRaw: 'LOW',
  zskRaw: 'GREEN',
  signalPeriod: 'На дату среза',
  sections: [
    {
      id: 'finance',
      title: 'Финансы',
      hint: '2023–2025',
      facts: [
        {
          id: 'ev-revenue',
          label: 'Выручка, 2025',
          value: '74 586 000 ₽',
          note: '2024: 65 289 000 ₽ · 2023: 6 461 000 ₽',
          period: '2025 год, годовая отчётность',
        },
        {
          id: 'ev-capital',
          number: 1,
          label: 'Капитал и резервы, 2025',
          value: '−300 000 ₽',
          note: '2024: −1 224 000 ₽ · 2023: 35 000 ₽',
          period: '2025 год, годовая отчётность',
          context:
            'Отрицательный капитал — отдельный факт, а не установленное банкротство.',
        },
        {
          id: 'ev-bankroll',
          label: 'Денежные средства на 31 декабря 2025',
          value: '355 000 ₽',
          period: '31 декабря 2025',
          context: 'Остаток отчётной даты, а не сумма на счетах сегодня.',
        },
        {
          id: 'ev-fixed',
          label: 'Основные средства, 2025',
          state: 'zero',
          value: '0 ₽',
          note: 'Строка отчётности заполнена: это подтверждённый ноль',
          period: '31 декабря 2025',
          context: 'Ноль в отчётности — значение, а не отсутствие сведений.',
        },
      ],
    },
    {
      id: 'courts',
      title: 'Суды',
      hint: 'агрегировано',
      facts: [
        {
          id: 'ev-arbitration',
          label: 'Дела за всё время',
          value: '3 дела · 1 513 302 ₽',
          period: 'На дату среза',
        },
        {
          id: 'ev-arbitration-defendant',
          label: 'Как ответчик',
          value: '2 завершённых дела · 1 068 858 ₽',
          period: 'На дату среза',
        },
        {
          id: 'ev-arbitration-subject',
          label: 'Предметы дел',
          state: 'missing',
          period: 'На дату среза',
          context: 'Арбитраж в отчёте агрегирован: тексты решений не предоставлены.',
        },
      ],
    },
    {
      id: 'executions',
      title: 'Взыскания',
      facts: [
        {
          id: 'ev-executions',
          number: 2,
          label: 'Действующие исполнительные производства',
          state: 'empty',
          period: 'На дату среза',
          context: 'Проверено на дату среза; сведения не обновляются автоматически.',
        },
        {
          id: 'ev-executions-closed',
          label: 'Завершённые производства',
          value: '12 · последнее 8 августа 2024',
          note: 'Мелкие суммы: обычно пошлины и штрафы',
          period: '2015–2024 годы',
        },
      ],
    },
    {
      id: 'activity',
      title: 'Деятельность и разрешения',
      facts: [
        {
          id: 'ev-okved',
          label: 'Основной ОКВЭД',
          value: '41.20 — строительство жилых и нежилых зданий',
          period: 'На дату среза',
        },
        {
          id: 'ev-okved-other',
          label: 'Другие направления',
          value: 'Ещё 39, всего 40',
          period: 'На дату среза',
          context: 'Число кодов само по себе ничего не доказывает.',
        },
        {
          id: 'ev-licenses',
          label: 'Лицензии',
          state: 'missing',
          period: 'На дату среза',
        },
        {
          id: 'ev-inspections',
          label: 'Проверки ведомств',
          value: '11 записей',
          note: 'В последней записи нарушений не зафиксировано',
          period: '2022–2025 годы',
        },
        {
          id: 'ev-procurements',
          label: 'Госзакупки',
          state: 'empty',
          period: 'На дату среза',
        },
      ],
    },
    {
      id: 'other',
      title: 'Другие сведения',
      facts: [
        {
          id: 'ev-ids',
          label: 'ИНН и ОГРН',
          value: '7449088645 · 1097449003156',
          period: 'На дату среза',
        },
        {
          id: 'ev-age',
          number: 3,
          label: 'Дата регистрации',
          value: '16 апреля 2009',
          note: '17 лет работы',
          period: 'На дату среза',
        },
        {
          id: 'ev-size',
          label: 'Размер бизнеса',
          value: 'Микропредприятие',
          period: 'На дату среза',
        },
        {
          id: 'ev-status',
          label: 'Статус',
          value: 'Действующая · с 1 августа 2026',
          period: 'На дату среза',
        },
        {
          id: 'ev-related',
          label: 'Связанные компании',
          value: '2 записи без полных отчётов',
          period: 'На дату среза',
          context: 'Полные отчёты связанных компаний в выгрузку не вошли.',
        },
        {
          id: 'ev-beneficiaries',
          label: 'Сведения о бенефициарах',
          state: 'unavailable',
          period: 'На дату среза',
        },
        {
          id: 'ev-as-of',
          label: 'Дата среза',
          value: '5 августа 2026',
          period: 'На дату среза',
        },
      ],
    },
  ],
});

const uralVostok = buildReport({
  companyId: 'ural-vostok',
  companyName: 'Урал-Восток-Транзит',
  inn: '6658123456',
  asOf: '29 июля 2026',
  asOfStale: true,
  bankRiskRaw: 'UNKNOWN',
  zskRaw: 'GREEN',
  signalPeriod: 'На дату среза',
  sections: [
    {
      id: 'finance',
      title: 'Финансы',
      availability: 'missing',
    },
    {
      id: 'courts',
      title: 'Суды',
      hint: 'агрегировано',
      facts: [
        {
          id: 'ev-uv-arbitration',
          label: 'Дела за всё время',
          value: '1 525 дел · 4 534 783 044 ₽',
          period: 'На дату среза',
          context: 'Масштаб споров сам по себе не вывод: сопоставляйте с размером компании.',
        },
      ],
    },
    {
      id: 'executions',
      title: 'Взыскания',
      facts: [
        {
          id: 'ev-uv-executions',
          label: 'Действующие исполнительные производства',
          value: '45 · 1 571 231 ₽',
          period: 'На дату среза',
        },
      ],
    },
    {
      id: 'other',
      title: 'Другие сведения',
      facts: [
        {
          id: 'ev-uv-age',
          label: 'Дата регистрации',
          value: '17 июня 2003',
          note: '23 года работы',
          period: 'На дату среза',
        },
        {
          id: 'ev-uv-size',
          label: 'Размер бизнеса',
          state: 'missing',
          period: 'На дату среза',
        },
        {
          id: 'ev-uv-as-of',
          label: 'Дата среза',
          value: '29 июля 2026',
          note: 'Срез старше 30 дней',
          period: 'На дату среза',
        },
      ],
    },
  ],
});

const transLine = buildReport({
  companyId: 'trans-line',
  companyName: 'Транс-Лайн',
  inn: '5904998877',
  asOf: '5 августа 2026',
  bankRiskRaw: 'LOW',
  zskRaw: 'YELLOW',
  signalPeriod: 'На дату среза',
  sections: [
    {
      id: 'finance',
      title: 'Финансы',
      hint: '2025',
      facts: [
        {
          id: 'ev-tl-revenue',
          label: 'Выручка, 2025',
          value: '4 749 348 000 ₽',
          period: '2025 год, годовая отчётность',
        },
        {
          id: 'ev-tl-capital',
          label: 'Капитал и резервы, 2025',
          value: '213 087 000 ₽',
          period: '2025 год, годовая отчётность',
        },
      ],
    },
    {
      id: 'executions',
      title: 'Взыскания',
      facts: [
        {
          id: 'ev-tl-executions',
          label: 'Действующие исполнительные производства',
          value: '8 · 7 269 373 ₽',
          period: 'На дату среза',
        },
      ],
    },
    {
      id: 'other',
      title: 'Другие сведения',
      availability: 'unavailable',
    },
  ],
});

const reports: readonly CompanyReport[] = [companyA, uralVostok, transLine];

/**
 * The provided report of one company, or `undefined` when the demo base has
 * none. A company without a report is said so; it is not shown as clean.
 */
export function getCompanyReport(companyId: string | undefined): CompanyReport | undefined {
  if (companyId === undefined) return undefined;
  return reports.find((report) => report.companyId === companyId);
}

/** Bases produced by the report rows, keyed by `evidence_ref`. */
export function findReportEvidence(evidenceId: string): EvidenceRecord | undefined {
  return registry.get(evidenceId);
}
