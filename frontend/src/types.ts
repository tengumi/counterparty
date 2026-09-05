export interface Evidence {
  company_name?: string;
  evidence_id: string;
  source_name: string;
  report_at: string;
  quality: string;
  coverage: string;
  canonical_path: string;
  value?: unknown;
  unit?: string | null;
  currency?: string | null;
}
export interface Finding {
  finding_id: string;
  code?: string;
  period?: number | string | null;
  statement: string;
  category: string;
  severity: string;
  data_status: string;
  evidence_ids: string[];
}
export interface Card {
  short_name?: string | null;
  snapshot_id: string;
  name: string;
  inn: string;
  ogrn: string;
  report_at: string;
  raw_status: string;
  party_type: string;
  bank_risk: { display_level: string; raw_level: string | null };
  bank_evidence_id?: string;
  identity_evidence_id?: string;
  status_evidence_id?: string;
  report_evidence_id?: string;
  findings: Finding[];
  evidence: Evidence[];
}
export interface Cell {
  snapshot_id: string;
  display_value: string;
  value: string | number | null;
  evidence_ids: string[];
  data_status: string;
}
export interface Row {
  key: string;
  label: string;
  category: string;
  comparable: boolean;
  comparison_note: string;
  cells: Cell[];
}
export interface Candidate {
  snapshot_id: string;
  full_name: string;
  inn: string;
  ogrn: string;
}
export interface Selection {
  selection_id: string;
  position: number;
  status: string;
  message: string;
  candidates: Candidate[];
}
export interface ReviewContext {
  goal: string | null;
  role: string | null;
  subject: string | null;
  amount: string | null;
  advance: string | null;
  deadline: string | null;
  general_check: boolean;
  question: string | null;
  steps: string[];
  context_revision: number;
}
export interface ChatResponse {
  session_id: string;
  answer: string;
  status: string;
  llm_used: boolean;
  card: Card | null;
  cards: Card[];
  candidates: Candidate[];
  comparison: {
    snapshot_ids: string[];
    rows: Row[];
    financial_year: number | null;
    limitations: string[];
  } | null;
  comparison_selections: Selection[];
  focus_snapshot_id: string | null;
  comparison_pending: boolean;
  answer_claims: { text: string; evidence_ids: string[] }[];
  review?: ReviewContext | null;
  evidence?: Evidence[];
}
export interface Message {
  role: "user" | "assistant";
  text: string;
  evidence?: Evidence[];
}
export interface Health {
  companies_count: number;
  qa_available: boolean;
  source_status: string;
}
export interface ProjectDocument {
  document_id: string;
  name: string;
  status: string;
  note: string;
  content_hash: string;
  question_id: string | null;
  uploaded_at: string;
  fragments: { evidence_id: string; text: string; location: string }[];
}
export interface MemoItem {
  kind:
    "fact" | "document" | "analysis" | "condition" | "limitation" | "action";
  text: string;
  evidence_ids: string[];
  company_id: string | null;
}
export interface Memo {
  sources?: Evidence[];
  goal: string;
  created_at: string;
  items: MemoItem[];
  note: string;
  selected_snapshot_ids: string[];
  document_hashes: Record<string, string>;
}
export interface ProjectSummary {
  project_id: string;
  title: string;
  goal: string;
  revision: number;
  shortlist_ids: string[];
}
export interface Project extends ProjectSummary {
  focused_snapshot_id?: string | null;
  deal?: Omit<ReviewContext, "steps">;
  snapshot_ids: string[];
  session_id: string;
  updated_at: string;
  documents: ProjectDocument[];
  plan_mode: string;
  plan: { step_id: string; title: string; status: string; detail: string }[];
  questions: {
    question_id: string;
    text: string;
    document_ids: string[];
    answer?: string | null;
    status?: "open" | "answered" | "needs_confirmation";
    evidence_ids?: string[];
    answered_at?: string | null;
  }[];
  memo: Memo | null;
  memo_stale?: boolean;
  proposal: {
    proposal_id: string;
    base_revision: number;
    memo: Memo;
    diff: { kind: string; text: string }[];
  } | null;
}
