/**
 * Per-viewer convenience state of S2: drawer, draft and scroll position.
 *
 * This is a local convenience, not a source of truth: the server owns the
 * conversation and the materials. Every storage access is guarded, because a
 * private window, cleared site data or a browser that blocks storage must
 * still render the screen with an empty value.
 */

import { useCallback, useEffect, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';

const PREFIX = 'counterparty.s2';

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    // Some browsers throw on the accessor itself when site data is blocked.
    return null;
  }
}

/** Read one stored value, or `null` when it is missing or unusable. */
export function readStored<T>(key: string, parse: (raw: unknown) => T | null): T | null {
  try {
    const raw = storage()?.getItem(`${PREFIX}.${key}`);
    if (raw === null || raw === undefined) return null;
    return parse(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

/** Store one value; a failure is silent, the screen keeps working. */
export function writeStored(key: string, value: unknown): void {
  try {
    storage()?.setItem(`${PREFIX}.${key}`, JSON.stringify(value));
  } catch {
    // Storage is full or unavailable: the value simply is not remembered.
  }
}

export function removeStored(key: string): void {
  try {
    storage()?.removeItem(`${PREFIX}.${key}`);
  } catch {
    // Nothing to do: the value was never readable in the first place.
  }
}

export function parseString(raw: unknown): string | null {
  return typeof raw === 'string' ? raw : null;
}

/** Ignores a stored empty draft, so a task carried from S1 still wins. */
export function parseNonEmptyString(raw: unknown): string | null {
  return typeof raw === 'string' && raw.length > 0 ? raw : null;
}

export function parseNumber(raw: unknown): number | null {
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
}

/**
 * State restored from storage on mount and written back on every change.
 *
 * The key is read once per mount: the caller remounts the subtree when the
 * chat changes, so one chat never shows another chat's draft.
 */
export function usePersistentState<T>(
  key: string,
  fallback: T,
  parse: (raw: unknown) => T | null,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => readStored(key, parse) ?? fallback);

  useEffect(() => {
    writeStored(key, value);
  }, [key, value]);

  return [value, setValue];
}

/**
 * Restore the scroll position of a container and keep it up to date.
 *
 * A missing value leaves the container where it is, so the first visit of a
 * conversation is not scrolled to a remembered place it never had.
 */
export function useRestoredScroll(key: string, ref: { current: HTMLElement | null }): () => void {
  useEffect(() => {
    const element = ref.current;
    const stored = readStored(key, parseNumber);
    if (element === null || stored === null) return;
    element.scrollTop = stored;
  }, [key, ref]);

  return useCallback(() => {
    const element = ref.current;
    if (element === null) return;
    writeStored(key, element.scrollTop);
  }, [key, ref]);
}
