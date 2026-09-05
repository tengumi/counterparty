/**
 * Draft carried from S1 to S2 through router state.
 *
 * S1 has no backend to create a project on, so the text travels with the
 * navigation instead of being invented as a saved message. WEB-04 picks it up
 * as the initial composer draft.
 */

export interface TaskHandoff {
  readonly draft: string;
}

export function readTaskHandoff(state: unknown): TaskHandoff | null {
  if (typeof state !== 'object' || state === null) return null;
  const draft = (state as { draft?: unknown }).draft;
  return typeof draft === 'string' && draft.trim().length > 0 ? { draft } : null;
}
