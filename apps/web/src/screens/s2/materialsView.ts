/**
 * Where the materials panel currently is (07 §6).
 *
 * The panel is one surface with a small navigation stack: the list of groups,
 * then one element of a group, then at most one source behind a basis. The
 * stack is what «К материалам» walks back through, and what is restored when
 * the panel is reopened.
 */

export type MaterialsGroup = 'companies' | 'terms' | 'documents' | 'summary';

export type MaterialsView =
  | { readonly kind: 'list' }
  | { readonly kind: 'company'; readonly companyId: string }
  | { readonly kind: 'evidence'; readonly evidenceId: string }
  | { readonly kind: 'document'; readonly documentId: string }
  | { readonly kind: 'summary' }
  | { readonly kind: 'comparison' };

export interface MaterialsState {
  readonly open: boolean;
  /** Expanded groups of the list screen; collapsing is remembered too. */
  readonly expanded: readonly MaterialsGroup[];
  /** Navigation stack, oldest first; the last item is the current screen. */
  readonly stack: readonly MaterialsView[];
}

export const groupTitles: Readonly<Record<MaterialsGroup, string>> = {
  companies: 'Компании',
  terms: 'Условия',
  documents: 'Документы',
  summary: 'Итог',
};

export const initialMaterials: MaterialsState = {
  open: false,
  expanded: ['companies'],
  stack: [{ kind: 'list' }],
};

function parseView(raw: unknown): MaterialsView | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const value = raw as { kind?: unknown; companyId?: unknown; evidenceId?: unknown; documentId?: unknown };
  if (value.kind === 'list') return { kind: 'list' };
  if (value.kind === 'summary') return { kind: 'summary' };
  if (value.kind === 'comparison') return { kind: 'comparison' };
  if (value.kind === 'company' && typeof value.companyId === 'string') {
    return { kind: 'company', companyId: value.companyId };
  }
  if (value.kind === 'evidence' && typeof value.evidenceId === 'string') {
    return { kind: 'evidence', evidenceId: value.evidenceId };
  }
  if (value.kind === 'document' && typeof value.documentId === 'string') {
    return { kind: 'document', documentId: value.documentId };
  }
  return null;
}

/** Tolerant reader: anything unexpected in storage falls back to the list. */
export function parseMaterialsState(raw: unknown): MaterialsState | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const value = raw as { open?: unknown; expanded?: unknown; stack?: unknown };
  const expanded = Array.isArray(value.expanded)
    ? value.expanded.filter((item): item is MaterialsGroup =>
        typeof item === 'string' && item in groupTitles,
      )
    : initialMaterials.expanded;
  const stack = Array.isArray(value.stack)
    ? value.stack.map(parseView).filter((view): view is MaterialsView => view !== null)
    : [];

  return {
    open: value.open === true,
    expanded,
    stack: stack.length > 0 ? stack : [{ kind: 'list' }],
  };
}

export function currentView(state: MaterialsState): MaterialsView {
  return state.stack[state.stack.length - 1] ?? { kind: 'list' };
}
