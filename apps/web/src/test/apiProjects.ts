/** Shared synthetic REST projects for unit tests and the WEB-07 browser harness. */
import type { ApiProject } from '../api/contracts';

export const apiProjects = [
  {
    schema_version: '0.1', id: 'demo-project', title: 'Поставка оборудования к 20 сентября',
    default_thread_id: 'demo-thread', threads_count: 2, context_version: 0,
    workflow_status: 'needs_information', last_open_question: 'Ждём подтверждение наличия товара',
    created_at: '2026-09-01T10:00:00+03:00', updated_at: '2026-09-05T14:20:00+03:00',
    companies: [{ company_id: 'company-a', report_id: 'report-a', inn: '7449088645', short_name: 'Компания А', role: 'supplier', shortlisted: false, added_at: '2026-09-01T10:00:00+03:00' }],
  },
  {
    schema_version: '0.1', id: 'logistics-project', title: 'Логистика на Урал, 2 квартал',
    default_thread_id: 'logistics-thread', threads_count: 1, context_version: 0,
    workflow_status: 'decision_recorded', last_open_question: null,
    created_at: '2026-08-20T10:00:00+03:00', updated_at: '2026-08-27T11:05:00+03:00',
    companies: [
      { company_id: 'ural-vostok', report_id: 'report-u', inn: '6658123456', short_name: 'Общество с ограниченной ответственностью «Специализированная транспортно-логистическая компания Урал-Восток-Транзит»', role: 'unknown', shortlisted: false, added_at: '2026-08-20T10:00:00+03:00' },
      { company_id: 'trans-line', report_id: 'report-t', inn: '5904998877', short_name: 'Транс-Лайн', role: 'unknown', shortlisted: false, added_at: '2026-08-20T10:00:00+03:00' },
    ],
  },
  {
    schema_version: '0.1', id: 'inn-project', title: 'Проверка · ИНН 7714497158',
    default_thread_id: 'inn-thread', threads_count: 1, context_version: 0,
    workflow_status: 'in_progress', last_open_question: null,
    created_at: '2026-08-14T09:40:00+03:00', updated_at: '2026-08-14T09:40:00+03:00',
    companies: [{ company_id: 'company-unknown', report_id: 'report-i', inn: '7714497158', short_name: 'Компания по ИНН 7714497158', role: 'unknown', shortlisted: false, added_at: '2026-08-14T09:40:00+03:00' }],
  },
] as const satisfies readonly ApiProject[];
