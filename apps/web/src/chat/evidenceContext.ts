import { createContext } from 'react';

/**
 * Opens a numbered basis cited in an assistant answer (07 P1-03).
 * `null` when the surrounding chat has nowhere to open one, e.g. a fixture.
 */
export const EvidenceRefContext = createContext<((ref: string) => void) | null>(null);
