import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

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
] as const;

function testApiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = new URL(typeof input === 'string' ? input : input.toString(), 'http://localhost');
  if (url.pathname === '/api/v1/projects' && (!init?.method || init.method === 'GET')) {
    return Promise.resolve(Response.json({ schema_version: '0.1', items: apiProjects, page: { limit: 100, next_cursor: null, has_more: false } }));
  }
  if (url.pathname === '/api/v1/projects' && init?.method === 'POST') {
    return Promise.resolve(Response.json(apiProjects[0], { status: 201 }));
  }
  const match = url.pathname.match(/^\/api\/v1\/projects\/([^/]+)$/);
  if (match && (!init?.method || init.method === 'GET')) {
    const project = apiProjects.find((item) => item.id === match[1]);
    return Promise.resolve(project ? Response.json(project) : Response.json({ code: 'not_found', message: 'project not found', retryable: false, request_id: 'test', details: null }, { status: 404 }));
  }
  return Promise.reject(new TypeError(`Unhandled test request: ${url.pathname}`));
}

vi.stubGlobal('fetch', vi.fn(testApiFetch));

// jsdom has no viewport media-query implementation; keep the actual DS components.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn((query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => false),
  })),
});

// jsdom ships no ResizeObserver; assistant-ui's viewport primitives observe content.
class ResizeObserverStub implements ResizeObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
globalThis.ResizeObserver = ResizeObserverStub;

// jsdom implements no scrolling; the thread viewport auto-scrolls on new content.
Element.prototype.scrollTo = vi.fn();

afterEach(() => {
  cleanup();
  // The S2 conveniences (drawer, draft, scroll) are per viewer, not per test.
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn(testApiFetch));
});
