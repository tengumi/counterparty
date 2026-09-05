/**
 * Presentation rules of the company report (07 P1-02, §9).
 *
 * Plain code, no rendering: a fact is either resolved into an existing basis
 * or withheld, and the two external signals are described without recomputing
 * them. Keeping this out of the component is what lets WEB-08 swap the mock
 * data source without touching either.
 */

import type { EvidenceRecord, FactState, ReportFact } from '../../mocks/types';
import { factStateLabels, factStateNotes } from '../../mocks/types';

/** How firmly the row is known; drives wording and emphasis, not a verdict. */
export type FactTone = 'known' | 'unknown';

export function factTone(state: FactState): FactTone {
  return state === 'value' || state === 'zero' ? 'known' : 'unknown';
}

/** Text of the row: the value itself, or what kind of unknown it is. */
export function factDisplay(fact: ReportFact): string {
  if (fact.state === 'value' || fact.state === 'zero') return fact.value ?? '';
  return factStateLabels[fact.state];
}

/** Second line of an unknown row, so it is never read as a zero. */
export function factStateNote(fact: ReportFact): string | null {
  if (fact.state === 'value' || fact.state === 'zero') return fact.note;
  return factStateNotes[fact.state];
}

/**
 * A row ready to render, or a row whose value must stay hidden.
 *
 * The product rule is one-directional: a value is shown only when its basis
 * exists. A dangling `evidence_ref` therefore hides the value and says why —
 * it never degrades into an unsourced number.
 */
export type ResolvedFact =
  | {
      readonly kind: 'shown';
      readonly fact: ReportFact;
      readonly evidence: EvidenceRecord;
      readonly display: string;
      readonly tone: FactTone;
      readonly note: string | null;
    }
  | { readonly kind: 'withheld'; readonly fact: ReportFact };

export function resolveFact(
  fact: ReportFact,
  lookup: (evidenceId: string) => EvidenceRecord | undefined,
): ResolvedFact {
  const evidence = lookup(fact.evidenceId);
  if (evidence === undefined) return { kind: 'withheld', fact };
  return {
    kind: 'shown',
    fact,
    evidence,
    display: factDisplay(fact),
    tone: factTone(fact.state),
    note: factStateNote(fact),
  };
}

export const WITHHELD_VALUE_TEXT =
  'Значение не показываем: основание недоступно.';

/** Neutral / positive / attention only; never a computed risk colour. */
export type SignalTone = 'positive' | 'attention' | 'neutral';

export interface SignalView {
  readonly label: string;
  /** The value exactly as it arrived; it is displayed, not translated away. */
  readonly raw: string;
  /** Human wording of a confirmed raw value; otherwise the raw value itself. */
  readonly valueLabel: string;
  readonly tone: SignalTone;
  readonly note: string;
  readonly evidenceId: string;
}

const bankRiskLabels: Readonly<Record<string, { label: string; tone: SignalTone }>> = {
  LOW: { label: 'Низкий', tone: 'positive' },
  MEDIUM: { label: 'Средний', tone: 'attention' },
  HIGH: { label: 'Высокий', tone: 'attention' },
};

/** Bank scale of the source: shown with its own wording and its own limits. */
export function describeBankRisk(raw: string, evidenceId: string): SignalView {
  const known = bankRiskLabels[raw];
  return {
    label: 'Риск по оценке банка',
    raw,
    valueLabel: known?.label ?? 'Оценка недоступна',
    tone: known?.tone ?? 'neutral',
    note:
      known === undefined
        ? 'Оценки в отчёте нет. Отсутствие оценки не означает отсутствие риска.'
        : 'Не заменяет оценку финансового положения.',
    evidenceId,
  };
}

/**
 * ЗСК is an unchangeable external signal (AGENTS.md, 07 §9).
 *
 * The raw value is kept and shown as it arrived, the colour is never
 * recomputed from anything else, and the closed methodology behind it is not
 * explained. Only `GREEN` has a confirmed display; every other value stays
 * neutral and says that its display is not settled yet — silently repainting
 * or reinterpreting it would be inventing a signal the bank did not send.
 */
export function describeZsk(raw: string, evidenceId: string): SignalView {
  const green = raw === 'GREEN';
  return {
    label: 'ЗСК',
    raw,
    valueLabel: green ? 'Зелёный' : raw,
    tone: green ? 'positive' : 'neutral',
    note: green
      ? 'Отдельный внешний сигнал платформы «Знай своего клиента». С оценкой банка не складывается.'
      : 'Отображение требует уточнения: подтверждённого соответствия для этого значения нет. Исходное значение сохранено.',
    evidenceId,
  };
}
