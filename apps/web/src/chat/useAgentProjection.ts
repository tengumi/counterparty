/**
 * Tolerant read access to the published projection.
 *
 * `useAssistantTransportState` from @assistant-ui/react 0.15.18 throws while
 * the thread-list wrapper still exposes placeholder extras, which happens on
 * the first render of a component mounted next to the runtime. This hook reads
 * the same store slot through the public `useAuiState` and falls back to the
 * initial projection until the runtime publishes one.
 */

import { useAuiState } from '@assistant-ui/react';
import type { PublicAgentState } from './publicAgentState';

function isProjection(value: unknown): value is PublicAgentState {
  return (
    typeof value === 'object' &&
    value !== null &&
    Array.isArray((value as PublicAgentState).messages) &&
    Array.isArray((value as PublicAgentState).activities)
  );
}

export function useAgentProjection(fallback: PublicAgentState): PublicAgentState {
  return useAuiState((state) => {
    const extras = state.thread.extras as { state?: unknown } | undefined;
    return isProjection(extras?.state) ? extras.state : fallback;
  });
}
