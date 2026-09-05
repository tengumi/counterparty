/**
 * Wording and checks of the decision screen (07 D1, Specs 10 §4).
 *
 * Nothing here computes a business value: staleness is either the server's own
 * `freshness`, or the plain statement that the conclusion was drawn from an
 * older context version than the project has now. The client only decides how
 * to say it.
 */

import type {
  ApiAnalysisArtifact,
  ApiUserDecision,
  DecisionOutcome,
} from '../../api/decisions';

export const outcomeLabels: Readonly<Record<DecisionOutcome, string>> = {
  ready: 'Готов работать',
  ready_with_conditions: 'Готов при условиях',
  not_ready: 'Не готов работать',
  need_more_info: 'Нужно больше сведений',
};

/** Outcomes that promise something concrete and must name it (Specs 10 §4). */
export const outcomesNeedingConditions: readonly DecisionOutcome[] = [
  'ready_with_conditions',
  'need_more_info',
];

export const conditionsLabel: Readonly<Record<DecisionOutcome, string>> = {
  ready: 'Условия, если они есть',
  ready_with_conditions: 'Условия — по одному в строке',
  not_ready: 'Что именно мешает, если хотите записать',
  need_more_info: 'Каких сведений не хватает — по одному в строке',
};

export function parseConditions(raw: string): string[] {
  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/**
 * Why this decision cannot be sent yet, or `null` when it can.
 *
 * The server validates the same invariants; this only avoids offering a
 * request that is known to be refused.
 */
export function decisionProblem(
  outcome: DecisionOutcome | null,
  rationale: string,
  conditions: readonly string[],
): string | null {
  if (outcome === null) return 'Выберите своё решение по проверке.';
  if (rationale.trim().length === 0) {
    return 'Напишите основание: почему вы приняли это решение.';
  }
  if (outcomesNeedingConditions.includes(outcome) && conditions.length === 0) {
    return outcome === 'need_more_info'
      ? 'Назовите хотя бы одно конкретное недостающее сведение.'
      : 'Назовите хотя бы одно конкретное условие.';
  }
  return null;
}

export interface StaleMark {
  /** Short label shown next to the item. */
  readonly label: string;
  /** The two version numbers, stated as facts. */
  readonly detail: string;
}

/**
 * Whether the AI conclusion still matches the project it was drawn from.
 *
 * `freshness` is the server's answer and wins. The version comparison is only
 * used when the server still calls the artifact current while the project has
 * moved on — the two numbers are then reported as they are.
 */
export function artifactStaleMark(
  artifact: ApiAnalysisArtifact,
  contextVersion: number,
): StaleMark | null {
  const detail = `Вывод сделан по сведениям версии ${artifact.based_on_context_version}; сейчас версия ${contextVersion}.`;
  if (artifact.freshness === 'source_removed') {
    return { label: 'Источник вывода удалён', detail };
  }
  if (artifact.freshness === 'outdated') {
    return { label: 'Вывод устарел', detail };
  }
  if (artifact.based_on_context_version !== contextVersion) {
    return { label: 'Сведения изменились после вывода', detail };
  }
  return null;
}

/** The same statement for a recorded decision; the decision itself stands. */
export function decisionStaleMark(
  decision: ApiUserDecision,
  contextVersion: number,
): StaleMark | null {
  if (decision.context_version === contextVersion) return null;
  return {
    label: 'Сведения изменились после решения',
    detail: `Решение записано по сведениям версии ${decision.context_version}; сейчас версия ${contextVersion}. Решение остаётся в силе, пока вы не запишете новое.`,
  };
}

export function decisionDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return 'Дата недоступна';
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(date);
}

/** Newest first; the server keeps every version, so nothing is dropped. */
export function byNewest(decisions: readonly ApiUserDecision[]): readonly ApiUserDecision[] {
  return [...decisions].sort(
    (left, right) => new Date(right.created_at).valueOf() - new Date(left.created_at).valueOf(),
  );
}
