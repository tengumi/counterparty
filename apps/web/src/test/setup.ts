import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

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
});
