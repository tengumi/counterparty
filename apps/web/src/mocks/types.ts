/**
 * Typed workspace shapes for the S1/S2 screens.
 *
 * The REST API for these surfaces does not exist yet (WEB-08 replaces the mock
 * module below). Components only ever see these types, so the swap is a data
 * source change and not a component rewrite.
 */

/** Project status from 07 §4. Company risk never appears here. */
export type ProjectStatus = 'in_progress' | 'needs_input' | 'decision_recorded';

/** Current work state of one chat inside a project (06 §8). */
export type ChatStatus = 'running' | 'needs_input' | 'ready';

/** Whether the server has confirmed the last change (07 S2-01). */
export type SaveState = 'saved' | 'saving' | 'error';

export interface CompanyRef {
  readonly id: string;
  readonly name: string;
  /** 10 digits for a legal entity, 12 for a sole trader. */
  readonly inn: string;
}

export interface ChatSummary {
  readonly id: string;
  readonly title: string;
  /** Last message or open question shown under the title (07 S2-14). */
  readonly hint: string;
  readonly status: ChatStatus;
}

export interface ProjectSummary {
  readonly id: string;
  readonly title: string;
  readonly status: ProjectStatus;
  /** Short reason to come back, only for `needs_input` (07 S1-05). */
  readonly continuation: string | null;
  /** Human label shown in the list; the ISO value stays for ordering. */
  readonly lastActivityLabel: string;
  readonly lastActivityAt: string;
  /** Thread the row reopens, i.e. the saved place of the project. */
  readonly lastThreadId: string;
}

export interface ProjectDetail extends ProjectSummary {
  readonly companies: readonly CompanyRef[];
  readonly chats: readonly ChatSummary[];
  readonly saveState: SaveState;
  /** Marks the single scripted demo project; never claims real company data. */
  readonly isDemo: boolean;
}

export interface ExamplePrompt {
  readonly id: string;
  readonly label: string;
  /** Editable text inserted into the composer; it is never auto-sent. */
  readonly text: string;
}

/** Maximum companies per project, an accepted prototype limit (07 P1-08). */
export const COMPANY_LIMIT = 20;

/** Search appears from this many saved checks (07 S1-04). */
export const SEARCH_THRESHOLD = 6;

export const projectStatusLabels: Readonly<Record<ProjectStatus, string>> = {
  in_progress: 'В работе',
  needs_input: 'Нужны сведения',
  decision_recorded: 'Решение записано',
};

export const chatStatusLabels: Readonly<Record<ChatStatus, string>> = {
  running: 'Работает',
  needs_input: 'Нужны сведения',
  ready: 'Готов',
};
