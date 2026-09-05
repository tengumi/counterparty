/**
 * The single place holding mock workspace data for S1 and S2.
 *
 * Values mirror the accepted design baseline so the WEB-07 screenshots can be
 * compared with it. WEB-08 replaces the two accessors with REST queries.
 */

import { findReportEvidence } from './reports';
import type {
  ChatSummary,
  ConversationBlock,
  EvidenceRecord,
  ExamplePrompt,
  ProjectDetail,
  ProjectMaterials,
  ProjectSummary,
} from './types';

export const examplePrompts: readonly ExamplePrompt[] = [
  {
    id: 'supplier',
    label: 'Хочу проверить поставщика',
    text: 'Хочу проверить поставщика ',
  },
  {
    id: 'compare',
    label: 'Хочу сравнить компании',
    text: 'Хочу сравнить компании ',
  },
];

const demoProject: ProjectDetail = {
  id: 'demo-project',
  title: 'Поставка оборудования к 20 сентября',
  status: 'needs_input',
  continuation: 'Ждём подтверждение наличия товара',
  lastActivityLabel: 'Сегодня, 14:20',
  lastActivityAt: '2026-09-05T14:20:00+03:00',
  lastThreadId: 'demo-thread',
  isDemo: true,
  saveState: 'saved',
  companies: [{ id: 'company-a', name: 'Компания А', inn: '7449088645' }],
  chats: [
    {
      id: 'demo-thread',
      title: 'Поставка',
      hint: 'Ждём подтверждение наличия товара',
      status: 'needs_input',
    },
    {
      id: 'terms-thread',
      title: 'Условия оплаты',
      hint: 'Сопоставляю условия оплаты и финансовые сведения',
      status: 'running',
    },
  ],
};

const logisticsProject: ProjectDetail = {
  id: 'logistics-project',
  title: 'Логистика на Урал, 2 квартал',
  status: 'decision_recorded',
  continuation: null,
  lastActivityLabel: '27 августа',
  lastActivityAt: '2026-08-27T11:05:00+03:00',
  lastThreadId: 'logistics-thread',
  isDemo: false,
  saveState: 'saved',
  companies: [
    {
      id: 'ural-vostok',
      name: 'Общество с ограниченной ответственностью «Специализированная транспортно-логистическая компания Урал-Восток-Транзит»',
      inn: '6658123456',
    },
    { id: 'trans-line', name: 'Транс-Лайн', inn: '5904998877' },
  ],
  chats: [
    {
      id: 'logistics-thread',
      title: 'Выбор перевозчика',
      hint: 'Решение записано 27 августа',
      status: 'ready',
    },
  ],
};

const innProject: ProjectDetail = {
  id: 'inn-project',
  title: 'Проверка · ИНН 7714497158',
  status: 'in_progress',
  continuation: null,
  lastActivityLabel: '14 августа',
  lastActivityAt: '2026-08-14T09:40:00+03:00',
  lastThreadId: 'inn-thread',
  isDemo: false,
  saveState: 'saved',
  companies: [{ id: 'company-unknown', name: 'Компания по ИНН 7714497158', inn: '7714497158' }],
  chats: [
    {
      id: 'inn-thread',
      title: 'Первый разбор',
      hint: 'Сообщений пока нет',
      status: 'ready',
    },
  ],
};

const projects: readonly ProjectDetail[] = [demoProject, logisticsProject, innProject];

/** S1 list rows, newest first. */
export function listProjects(): readonly ProjectSummary[] {
  return [...projects].sort((a, b) => b.lastActivityAt.localeCompare(a.lastActivityAt));
}

/** S2 project, or `undefined` when the URL points at an unknown project. */
export function findProject(projectId: string | undefined): ProjectDetail | undefined {
  return projects.find((project) => project.id === projectId);
}

/** A locally created chat: mocks have no server, so the id stays client-side. */
export function newChat(index: number): ChatSummary {
  return {
    id: `local-chat-${index}`,
    title: `Новый чат ${index}`,
    hint: 'Сообщений пока нет',
    status: 'ready',
  };
}

/* ------------------------------------------------------------------ *
 * Conversation (WEB-04)
 * ------------------------------------------------------------------ */

/**
 * Bases that do not come from a company report.
 *
 * A report row carries its own basis (see `reports.ts`); this list holds the
 * ones read out of an uploaded document, so the basis can open the file.
 */
const documentEvidence: readonly EvidenceRecord[] = [
  {
    id: 'ev-offer',
    number: 4,
    title: 'Срок поставки по счёту',
    value: '21 день после комплектации заказа',
    companyName: 'Компания А',
    period: 'Счёт-оферта № 114 от 3 сентября 2026',
    source: 'Счёт-оферта.pdf, страница 1',
    asOf: '5 сентября 2026',
    context: 'Дата комплектации в документе не названа, поэтому срок из него не следует.',
    documentId: 'doc-invoice',
  },
];

/** Saved blocks of the demo chat: what the user sees on returning. */
const demoConversation: readonly ConversationBlock[] = [
  {
    kind: 'resume',
    id: 'demo-resume',
    text: 'Ждём подтверждение наличия товара. Разбор условий поставки сохранён.',
  },
  {
    kind: 'user',
    id: 'demo-user-1',
    text: 'Можно ли перечислять 80% аванса этой компании?',
    context: null,
    file: null,
  },
  {
    kind: 'activity',
    id: 'demo-activity-1',
    label: 'Проверено: оценка банка, финансы, взыскания',
    status: 'completed',
    steps: [
      {
        id: 'demo-step-1',
        kind: 'reading_report',
        label: 'Прочитал финансовые сведения',
        source: 'Отчёт · срез 5 августа 2026',
        status: 'completed',
      },
      {
        id: 'demo-step-2',
        kind: 'comparing',
        label: 'Сопоставил аванс с капиталом компании',
        source: 'Условия проверки',
        status: 'completed',
      },
      {
        id: 'demo-step-3',
        kind: 'reading_report',
        label: 'Проверил исполнительные производства',
        source: 'Отчёт · срез 5 августа 2026',
        status: 'completed',
      },
    ],
  },
  {
    kind: 'answer',
    id: 'demo-answer-1',
    text:
      'Аванс 80% от 2 400 000 ₽ — это 1 920 000 ₽ до отгрузки. Собственный капитал компании отрицательный, ' +
      'поэтому подушки на возврат аванса у неё нет и риск при срыве поставки ложится на вас.',
    points: [
      {
        id: 'demo-point-1',
        text: 'Капитал и резервы за 2025 год — −300 000 ₽, годом ранее −1 224 000 ₽',
        evidenceId: 'ev-capital',
      },
      {
        id: 'demo-point-2',
        text: 'Действующих исполнительных производств в отчёте не обнаружено, 12 завершены',
        evidenceId: 'ev-executions',
      },
      {
        id: 'demo-point-3',
        text: 'Компания работает с 2009 года, статус — действующая',
        evidenceId: 'ev-age',
      },
      {
        id: 'demo-point-4',
        text: 'Срок поставки в счёте отсчитывается от комплектации, а её дата не названа',
        evidenceId: 'ev-offer',
      },
    ],
    followUp: 'Оплата до поставки или после? Насколько критичен срок 20 сентября?',
    options: [
      { id: 'demo-option-1', label: 'Аванс', text: 'Оплата авансом' },
      { id: 'demo-option-2', label: 'После поставки', text: 'Оплата после поставки' },
      { id: 'demo-option-3', label: 'Ещё не решили', text: 'Условие оплаты ещё не решили' },
    ],
  },
  {
    kind: 'confirmation',
    id: 'demo-confirmation-1',
    text: 'Наличие товара не подтверждено. Прикрепите письмо или документ, если он у вас есть.',
    attachLabel: 'Прикрепить',
    declineLabel: 'Документа нет',
  },
];

const termsConversation: readonly ConversationBlock[] = [
  {
    kind: 'user',
    id: 'terms-user-1',
    text: 'Сравни условия оплаты с финансовыми сведениями компании.',
    context: 'Капитал · Компания А · 2025',
    file: null,
  },
  {
    kind: 'activity',
    id: 'terms-activity-1',
    label: 'Сопоставляю условия оплаты и финансовые сведения',
    status: 'running',
    steps: [
      {
        id: 'terms-step-1',
        kind: 'reading_document',
        label: 'Прочитал условия проверки',
        source: 'Из вашего сообщения',
        status: 'completed',
      },
      {
        id: 'terms-step-2',
        kind: 'reading_report',
        label: 'Читаю финансовые сведения',
        source: 'Отчёт · срез 5 августа 2026',
        status: 'running',
      },
    ],
  },
];

const logisticsConversation: readonly ConversationBlock[] = [
  {
    kind: 'user',
    id: 'logistics-user-1',
    text: 'Кого выбрать перевозчиком на 2 квартал?',
    context: null,
    file: null,
  },
  {
    kind: 'answer',
    id: 'logistics-answer-1',
    text: 'Различие в авансе весит больше разницы в цене: у Транс-Лайн аванс ниже при сопоставимом сроке.',
    points: [],
    followUp: null,
    options: [],
  },
  {
    kind: 'conclusion',
    id: 'logistics-conclusion-1',
    text: 'Готов работать с Транс-Лайн при оплате после поставки.',
    points: [
      {
        id: 'logistics-point-1',
        text: 'Действующих взысканий не найдено',
        evidenceId: null,
      },
    ],
    unconfirmed: 'Не подтверждено: страхование груза',
    stale: false,
  },
  {
    kind: 'notice',
    id: 'logistics-notice-1',
    text: 'Решение записано 27 августа. Его можно изменить в материалах проверки.',
    action: null,
  },
];

const conversations: Readonly<Record<string, readonly ConversationBlock[]>> = {
  'demo-thread': demoConversation,
  'terms-thread': termsConversation,
  'logistics-thread': logisticsConversation,
  'inn-thread': [],
};

/** Saved blocks of one chat; an unknown or new chat starts empty. */
export function getConversation(chatId: string | undefined): readonly ConversationBlock[] {
  if (chatId === undefined) return [];
  return conversations[chatId] ?? [];
}

/**
 * One basis, or `undefined` when the reference cannot be resolved.
 *
 * Report rows and document quotes are looked up in one place, so a statement
 * and the report row behind it are literally the same record.
 */
export function findEvidence(evidenceId: string | null | undefined): EvidenceRecord | undefined {
  if (!evidenceId) return undefined;
  return (
    findReportEvidence(evidenceId) ??
    documentEvidence.find((record) => record.id === evidenceId)
  );
}

/* ------------------------------------------------------------------ *
 * Materials panel (WEB-05)
 * ------------------------------------------------------------------ */

const materials: Readonly<Record<string, ProjectMaterials>> = {
  'demo-project': {
    terms: [
      { id: 'role', label: 'Роль компании', value: 'Поставщик', source: 'Из вашего сообщения' },
      { id: 'subject', label: 'Предмет', value: 'Оборудование', source: 'Из вашего сообщения' },
      { id: 'amount', label: 'Сумма', value: '2 400 000 ₽', source: 'Из вашего сообщения' },
      { id: 'payment', label: 'Оплата', value: 'Аванс 80%', source: 'Из вашего сообщения' },
      { id: 'term', label: 'Срок', value: '20 сентября', source: 'Из вашего сообщения' },
      { id: 'priority', label: 'Приоритет', value: null, source: 'Не указано' },
    ],
    documents: [
      {
        id: 'doc-invoice',
        name: 'Счёт-оферта.pdf',
        meta: 'Компания А · добавлен 5 сентября',
        state: 'ready',
      },
    ],
    summary: {
      short: 'Предложение помощника',
      line: 'Готов при условиях: аванс не выше 30% до подтверждения наличия товара',
      recorded: false,
    },
  },
  'logistics-project': {
    terms: [
      { id: 'role', label: 'Роль компании', value: 'Перевозчик', source: 'Из вашего сообщения' },
      { id: 'amount', label: 'Сумма', value: null, source: 'Не указано' },
    ],
    documents: [],
    summary: {
      short: 'Решение записано',
      line: 'Готов работать с Транс-Лайн при оплате после поставки · 27 августа',
      recorded: true,
    },
  },
  'inn-project': {
    terms: [],
    documents: [],
    summary: { short: 'Пока нет', line: 'Вывода по задаче ещё нет', recorded: false },
  },
};

const emptyMaterials: ProjectMaterials = {
  terms: [],
  documents: [],
  summary: { short: 'Пока нет', line: 'Вывода по задаче ещё нет', recorded: false },
};

/** Materials of one project; an unknown project has nothing loaded. */
export function getMaterials(projectId: string | undefined): ProjectMaterials {
  if (projectId === undefined) return emptyMaterials;
  return materials[projectId] ?? emptyMaterials;
}
