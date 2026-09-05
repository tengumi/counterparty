/**
 * A value the chat can publish without re-rendering the runtime host.
 *
 * `useAssistantTransportRuntime` rebuilds its thread-list adapter on every
 * render of the component that calls it, which discards the live thread. The
 * connection state therefore lives outside React state: subscribers re-render,
 * the host does not.
 */

import { useSyncExternalStore } from 'react';

export interface ValueStore<T> {
  readonly get: () => T;
  readonly set: (next: T) => void;
  readonly subscribe: (listener: () => void) => () => void;
}

export function createValueStore<T>(initial: T): ValueStore<T> {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set: (next: T) => {
      if (Object.is(next, value)) return;
      value = next;
      for (const listener of listeners) listener();
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export function useStoreValue<T>(store: ValueStore<T>): T {
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}
