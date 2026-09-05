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

/* ------------------------------------------------------------------ *
 * Conversation (WEB-04)
 * ------------------------------------------------------------------ */

/**
 * One numbered basis behind a statement (07 P1-03).
 *
 * `id` is the future `evidence_ref`: the panel resolves the reference, the
 * answer only carries it, so nothing is restated as a free-text fact.
 */
export interface EvidenceRecord {
  readonly id: string;
  /**
   * Number shown next to the sentence in the answer.
   *
   * Numbering belongs to an answer, not to the report: a basis opened from a
   * report row has no number and the panel titles it «Основание».
   */
  readonly number: number | null;
  readonly title: string;
  readonly value: string;
  readonly companyName: string;
  readonly period: string;
  /** Where the value came from, e.g. «Предоставленный отчёт, раздел «Финансы»». */
  readonly source: string;
  /** Snapshot date of the source; never the current date. */
  readonly asOf: string;
  /** Available context: what the value does not say, or a comparable period. */
  readonly context: string | null;
  /**
   * File this basis was read from, when there is a real one (07 P1-03).
   *
   * `null` keeps the panel honest: without a first source it shows «Источник:
   * предоставленный отчёт» and never a made-up registry link.
   */
  readonly documentId: string | null;
}

/** One completed or running step under «Что проверено» (07 S2-05). */
export interface ActivityStep {
  readonly id: string;
  readonly label: string;
  /** Typed kind of the action (`PublicActivity.kind`), or `null` for mocks. */
  readonly kind: string | null;
  /** Human source of the step; no MCP arguments, no raw graph state. */
  readonly source: string;
  readonly status: 'running' | 'completed' | 'failed';
}

/** A sentence of an answer, optionally backed by one numbered basis. */
export interface AnswerPoint {
  readonly id: string;
  readonly text: string;
  readonly evidenceId: string | null;
}

/** Short reply option offered by a clarifying question (07 S2-04). */
export interface AnswerOption {
  readonly id: string;
  readonly label: string;
  /** Text put into the composer; choosing never sends by itself. */
  readonly text: string;
}

/**
 * Saved conversation blocks of one chat.
 *
 * The union is the contract between the data source and the renderers: the
 * live agent projection is mapped onto the same blocks, so WEB-08/WEB-09 swap
 * the source without touching a component.
 */
export type ConversationBlock =
  | { readonly kind: 'resume'; readonly id: string; readonly text: string }
  | {
      readonly kind: 'user';
      readonly id: string;
      readonly text: string;
      /** Removable context chip carried with the message (07 S2-08). */
      readonly context: string | null;
      readonly file: { readonly name: string; readonly state: string } | null;
    }
  | {
      readonly kind: 'notice';
      readonly id: string;
      readonly text: string;
      readonly action: { readonly label: string; readonly documentId: string } | null;
    }
  | {
      readonly kind: 'activity';
      readonly id: string;
      readonly label: string;
      readonly status: 'running' | 'completed' | 'failed';
      readonly steps: readonly ActivityStep[];
    }
  | {
      readonly kind: 'answer';
      readonly id: string;
      readonly text: string;
      readonly points: readonly AnswerPoint[];
      readonly followUp: string | null;
      readonly options: readonly AnswerOption[];
    }
  | {
      readonly kind: 'conclusion';
      readonly id: string;
      readonly text: string;
      readonly points: readonly AnswerPoint[];
      /** What is still not confirmed; missing is not the same as absent risk. */
      readonly unconfirmed: string | null;
      /** True after the terms changed under an existing conclusion. */
      readonly stale: boolean;
    }
  | {
      readonly kind: 'confirmation';
      readonly id: string;
      readonly text: string;
      readonly attachLabel: string;
      readonly declineLabel: string;
    };

/* ------------------------------------------------------------------ *
 * Materials panel (WEB-05)
 * ------------------------------------------------------------------ */

/** Editable term of the deal (07 P1-04). «Не указано» is not zero. */
export interface TermRow {
  readonly id: string;
  readonly label: string;
  /** `null` renders «Не указано», which never means 0. */
  readonly value: string | null;
  readonly source: string;
}

/** Uploaded file of the project (07 P1-05). */
export interface DocumentRow {
  readonly id: string;
  readonly name: string;
  readonly meta: string;
  readonly state: 'uploading' | 'reading' | 'ready' | 'failed';
}

/** Last agent proposal or the decision the user recorded (07 P1-07). */
export interface MaterialsSummary {
  /** Short line shown next to the group title. */
  readonly short: string;
  readonly line: string;
  /** A user record is visually different from a proposal. */
  readonly recorded: boolean;
}

export interface ProjectMaterials {
  readonly terms: readonly TermRow[];
  readonly documents: readonly DocumentRow[];
  readonly summary: MaterialsSummary;
}

export const documentStateLabels: Readonly<Record<DocumentRow['state'], string>> = {
  uploading: 'Загружается',
  reading: 'Читаю документ',
  ready: 'Готово',
  failed: 'Не удалось прочитать',
};

/* ------------------------------------------------------------------ *
 * Company report (WEB-06)
 * ------------------------------------------------------------------ */

/**
 * How one fact of the report is known (07 §9).
 *
 * The four unknown-ish states are deliberately separate: a missing block, a
 * checked-but-empty list, a restricted block and a confirmed zero mean
 * different things, and none of them means «no risk».
 */
export type FactState = 'value' | 'zero' | 'missing' | 'empty' | 'unavailable';

/** Wording of a state that has no value; `value`/`zero` print the value. */
export const factStateLabels: Readonly<
  Record<Exclude<FactState, 'value' | 'zero'>, string>
> = {
  missing: 'В отчёте нет этих сведений',
  empty: 'В отчёте события не обнаружены',
  unavailable: 'Эти сведения недоступны',
};

/** Short explanation shown under an unknown value, so it is not read as zero. */
export const factStateNotes: Readonly<
  Record<Exclude<FactState, 'value' | 'zero'>, string>
> = {
  missing: 'Раздел не предоставлен. Это не подтверждение, что событий не было.',
  empty: 'Раздел проверен, записей нет. Это не гарантия на будущее.',
  unavailable: 'Доступ к разделу ограничен. Отсутствие сведений не означает отсутствие риска.',
};

/** One row of a report section. Every row resolves to an existing basis. */
export interface ReportFact {
  readonly id: string;
  readonly label: string;
  readonly state: FactState;
  /** Formatted value for `value` and `zero`; `null` for the unknown states. */
  readonly value: string | null;
  /** Second line: comparable period, or what the value does not mean. */
  readonly note: string | null;
  /** `evidence_ref` of the row; a value is never shown without its basis. */
  readonly evidenceId: string;
}

/** Whether the report carries this section at all (07 P1-02). */
export type SectionAvailability = 'available' | 'missing' | 'unavailable';

export interface ReportSection {
  readonly id: string;
  readonly title: string;
  /** Period or scope of the section, e.g. «2024–2025». */
  readonly hint: string | null;
  readonly availability: SectionAvailability;
  readonly facts: readonly ReportFact[];
}

export const sectionAvailabilityLabels: Readonly<
  Record<SectionAvailability, string>
> = {
  available: 'Есть сведения',
  missing: 'Раздела нет в отчёте',
  unavailable: 'Раздел недоступен',
};

/**
 * The provided report of one company.
 *
 * `bankRiskRaw` and `zskRaw` stay as they arrived. The bank scale is described
 * by the source, and `zskRiskLevel` is an external signal the UI never
 * recolours and never explains beyond what the signal itself is.
 */
export interface CompanyReport {
  readonly companyId: string;
  readonly companyName: string;
  readonly inn: string;
  /** Snapshot date of the report; never the date of the check. */
  readonly asOf: string;
  /** Prototype rule of 07 §9: «Срез старше 30 дней» is stated, not hidden. */
  readonly asOfStale: boolean;
  /** Every mock company is a teaching example, and says so. */
  readonly educational: boolean;
  readonly bankRiskRaw: string;
  readonly bankRiskEvidenceId: string;
  readonly zskRaw: string;
  readonly zskEvidenceId: string;
  readonly sections: readonly ReportSection[];
}
