import { act, renderHook } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { useAutoScroll } from './useAutoScroll';

it('preserves a restored reading position on the first resize and follows only after scrolling to the end', () => {
  const originalObserver = globalThis.ResizeObserver;
  let notify: (() => void) | undefined;
  class Observer implements ResizeObserver {
    constructor(callback: ResizeObserverCallback) { notify = () => callback([], this); }
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  }
  vi.stubGlobal('ResizeObserver', Observer);
  try {
    const container = document.createElement('div');
    Object.defineProperties(container, {
      scrollHeight: { value: 1200, configurable: true },
      clientHeight: { value: 400 },
    });
    container.scrollTop = 150;
    const containerRef = { current: container };
    const contentRef = { current: document.createElement('div') };
    const { result, unmount } = renderHook(() => useAutoScroll(containerRef, contentRef, false));

    act(() => notify?.());
    expect(container.scrollTop).toBe(150);
    container.scrollTop = 800;
    act(() => result.current());
    Object.defineProperty(container, 'scrollHeight', { value: 1400 });
    act(() => notify?.());
    expect(container.scrollTop).toBe(1400);
    unmount();
  } finally {
    vi.stubGlobal('ResizeObserver', originalObserver);
  }
});
