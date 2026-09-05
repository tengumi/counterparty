/** Synthetic REST DTOs with UUID resources; independent of visual mock registries. */
import type { ApiProject } from '../api/contracts';
import type { CompanyOverview, FactValue, ReportSection } from '../api/reportContracts';
export const PROJECT_ID = '00000000-0000-4000-8000-000000000010';
export const COMPANY_ID = '00000000-0000-4000-8000-000000000020';
export const REPORT_ID = '00000000-0000-4000-8000-000000000030';
export const SECOND_REPORT_ID = '00000000-0000-4000-8000-000000000031';
export const REF = `report:${REPORT_ID}:/finReports/0/common/proceeds`;
export const liveProject: ApiProject = {
  schema_version: '0.1',
  id: PROJECT_ID,
  title: 'Проверка поставщика',
  default_thread_id: '00000000-0000-4000-8000-000000000040',
  threads_count: 1,
  context_version: 2,
  workflow_status: 'in_progress',
  last_open_question: null,
  created_at: '2026-09-05T00:00:00Z',
  updated_at: '2026-09-05T00:00:00Z',
  companies: [
    {
      company_id: COMPANY_ID,
      report_id: REPORT_ID,
      inn: '7449088645',
      short_name: 'Поставщик из REST',
      role: 'unknown',
      shortlisted: false,
      added_at: '2026-09-05T00:00:00Z',
    },
    {
      company_id: '00000000-0000-4000-8000-000000000021',
      report_id: SECOND_REPORT_ID,
      inn: '7702070139',
      short_name: 'Второй поставщик',
      role: 'unknown',
      shortlisted: false,
      added_at: '2026-09-05T00:00:00Z',
    },
  ],
};
export const zeroFact: FactValue = {
  key: 'proceeds',
  label: 'Выручка',
  value: '0.00',
  value_type: 'decimal',
  currency: 'RUB',
  period: 2025,
  availability: 'available',
  evidence_refs: [REF],
  warnings: [],
};
export const missingFact: FactValue = {
  ...zeroFact,
  key: 'profit',
  label: 'Прибыль',
  value: null,
  availability: 'missing',
  evidence_refs: [],
};
export const overview: CompanyOverview = {
  schema_version: '0.1',
  company: { id: COMPANY_ID, inn: '7449088645', short_name: 'Поставщик из REST' },
  report: {
    id: REPORT_ID,
    source_report_at: '2026-09-05T00:00:00Z',
    ingested_at: '2026-09-05T00:00:00Z',
    source_kind: 'provided_snapshot',
  },
  status: {
    raw_value: 'ACTIVE',
    label: 'ACTIVE',
    availability: 'available',
    evidence_refs: [`report:${REPORT_ID}:/status/status`],
  },
  bank_risk: {
    raw_value: 'LOW',
    label: 'LOW',
    display_level: 'neutral',
    availability: 'available',
    evidence_refs: [`report:${REPORT_ID}:/baseInfo/riskLevel`],
  },
  zsk: {
    raw_value: 'YELLOW',
    display_level: 'neutral',
    display_note: 'Отображение требует уточнения',
    availability: 'available',
    evidence_refs: [`report:${REPORT_ID}:/zskRiskLevel`],
  },
  facts: [zeroFact, missingFact],
  available_sections: [
    {
      section: 'financials',
      availability: 'available',
      record_count: 1,
      confirms_absence: false,
      evidence_refs: [`report:${REPORT_ID}:/finReports`],
    },
  ],
  warnings: [],
  rule_version: 'overview/1',
};
export const financeSection: ReportSection = {
  schema_version: '0.1',
  report_id: REPORT_ID,
  section: 'financials',
  availability: 'available',
  records: [],
  facts: [zeroFact, missingFact],
  page: { limit: 20, next_cursor: 'next-finance', has_more: true },
  total_records: 3,
  warnings: [],
  rule_version: 'report-section/1',
};
