/**
 * The single place holding mock workspace data for S1 and S2.
 *
 * Values mirror the accepted design baseline so the WEB-07 screenshots can be
 * compared with it. WEB-08 replaces the two accessors with REST queries.
 */

import type {
  ChatSummary,
  ExamplePrompt,
  ProjectDetail,
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
  companies: [{ id: 'company-a', name: 'Компания А', inn: '7714497158' }],
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
  companies: [{ id: 'company-a', name: 'Компания А', inn: '7714497158' }],
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
