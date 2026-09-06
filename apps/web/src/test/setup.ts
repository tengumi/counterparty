import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

import { apiProjects } from './apiProjects';
export { apiProjects } from './apiProjects';

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
