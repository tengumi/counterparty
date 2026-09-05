/** Public report DTOs from Specs 10; decimal values stay strings. */
export type Availability = 'available' | 'missing' | 'present_empty' | 'invalid' | 'restricted';
export type SectionName =
  | 'profile'
  | 'status'
  | 'activities'
  | 'financials'
  | 'coefficients'
  | 'founders'
  | 'tax_systems'
  | 'contacts'
  | 'execution_proceedings'
  | 'arbitration'
  | 'procurements'
  | 'licenses'
  | 'inspections'
  | 'related_companies'
  | 'branches'
  | 'risk_signals'
  | 'zsk';
export interface ReportWarning {
  readonly code: string;
  readonly message: string;
  readonly source_path?: string | null;
}
export interface FactValue {
  readonly key: string;
  readonly label: string;
  readonly value: string | number | boolean | null;
  readonly value_type: 'decimal' | 'integer' | 'boolean' | 'string' | 'date' | 'enum';
  readonly currency?: string | null;
  readonly unit?: string | null;
  readonly period?: string | number | null;
  readonly availability: Availability;
  readonly evidence_refs: readonly string[];
  readonly warnings: readonly ReportWarning[];
}
export interface ReportIdentity {
  readonly id: string;
  readonly source_report_at: string;
  readonly ingested_at: string;
  readonly source_kind: 'provided_snapshot';
}
export interface CompanyIdentity {
  readonly id: string;
  readonly inn: string;
  readonly ogrn?: string | null;
  readonly short_name: string;
  readonly full_name?: string | null;
}
export interface Assessment {
  readonly raw_value: string | null;
  readonly display_level: 'positive' | 'neutral' | 'attention' | 'negative';
  readonly availability: Availability;
  readonly evidence_refs: readonly string[];
  readonly label?: string;
  readonly display_note?: string | null;
}
export interface SectionAvailability {
  readonly section: SectionName;
  readonly availability: Availability;
  readonly record_count: number | null;
  readonly confirms_absence: boolean;
  readonly evidence_refs: readonly string[];
}
export interface CompanyOverview {
  readonly schema_version: string;
  readonly company: CompanyIdentity;
  readonly report: ReportIdentity;
  readonly status: {
    readonly raw_value: string | null;
    readonly label: string;
    readonly availability: Availability;
    readonly evidence_refs: readonly string[];
  };
  readonly bank_risk: Assessment;
  readonly zsk: Assessment;
  readonly facts: readonly FactValue[];
  readonly available_sections: readonly SectionAvailability[];
  readonly warnings: readonly ReportWarning[];
  readonly rule_version: string;
}
interface Grounded {
  readonly evidence_refs: readonly string[];
}
export interface FinancialPeriod extends Grounded {
  readonly kind: 'financial_period';
  readonly year: number;
  readonly proceeds: FactValue;
  readonly profit: FactValue;
  readonly total_assets: FactValue;
  readonly equity: FactValue;
  readonly cash: FactValue;
  readonly receivables: FactValue;
  readonly accounts_payable: FactValue;
  readonly additional_facts: readonly FactValue[];
}
export type ReportRecord =
  | FinancialPeriod
  | (Grounded & {
      readonly kind: 'profile_record';
      readonly short_name: string | null;
      readonly full_name: string | null;
      readonly inn: string | null;
      readonly kpp: string | null;
      readonly okpo: string | null;
      readonly address: string | null;
      readonly registration_date: string | null;
      readonly email: string | null;
      readonly website: string | null;
      readonly company_size: string | null;
    })
  | (Grounded & {
      readonly kind: 'activity';
      readonly code: string | null;
      readonly description: string | null;
      readonly is_primary: boolean;
    })
  | (Grounded & {
      readonly kind: 'proceeding';
      readonly id: string;
      readonly number: string | null;
      readonly started_at: string | null;
      readonly active: FactValue;
      readonly amount: FactValue;
    })
  | (Grounded & {
      readonly kind: 'arbitration_aggregate';
      readonly aggregation: 'year' | 'status';
      readonly role: 'plaintiff' | 'defendant';
      readonly year: number | null;
      readonly case_status_raw: string | null;
      readonly count: FactValue;
      readonly amount: FactValue;
    })
  | (Grounded & {
      readonly kind: 'procurement_aggregate';
      readonly year: number;
      readonly law_code: string;
      readonly winners_count: FactValue;
      readonly contracts_count: FactValue;
      readonly contracts_amount: FactValue;
    })
  | (Grounded & {
      readonly kind: 'license';
      readonly number: string | null;
      readonly name: string | null;
      readonly authority: string | null;
      readonly issue_date: string | null;
      readonly status_raw: string | null;
    })
  | (Grounded & {
      readonly kind: 'inspection';
      readonly external_id: string | null;
      readonly form: string | null;
      readonly authority: string | null;
      readonly start_date: string | null;
      readonly end_date: string | null;
      readonly status_raw: string | null;
    })
  | (Grounded & {
      readonly kind: 'related_entity';
      readonly inn: string | null;
      readonly ogrn: string | null;
      readonly name: string | null;
      readonly available_company_id: string | null;
    })
  | (Grounded & {
      readonly kind: 'risk_signal';
      readonly code: string;
      readonly source_name: string | null;
      readonly polarity: 'positive' | 'negative';
      readonly chapter: string | null;
      readonly interpretation_note: string | null;
    });
export interface ReportSection {
  readonly schema_version: string;
  readonly report_id: string;
  readonly section: SectionName;
  readonly availability: Availability;
  readonly records: readonly ReportRecord[];
  readonly facts: readonly FactValue[];
  readonly total_records: number | null;
  readonly page: {
    readonly limit: number;
    readonly next_cursor: string | null;
    readonly has_more: boolean;
  };
  readonly warnings: readonly ReportWarning[];
  readonly rule_version: string;
}
export type JsonValue =
  | null
  | string
  | number
  | boolean
  | readonly JsonValue[]
  | { readonly [key: string]: JsonValue };
export interface ReportEvidence {
  readonly schema_version: string;
  readonly evidence: {
    readonly id: string;
    readonly kind: 'report_field';
    readonly report_id: string;
    readonly company_id: string | null;
    readonly source_path: string;
    readonly period: number | string | null;
  };
  readonly report: ReportIdentity;
  readonly availability: Availability;
  readonly value: JsonValue;
  readonly warnings: readonly ReportWarning[];
}
export type ComparisonCriterion =
  | 'bank_risk'
  | 'status'
  | 'financials'
  | 'proceedings'
  | 'arbitration'
  | 'activities'
  | 'licenses'
  | 'procurement';
export interface ComparisonInput {
  readonly report_ids: readonly string[];
  readonly criteria: readonly ComparisonCriterion[];
  readonly year_policy: 'common_latest' | 'latest_available' | 'explicit';
  readonly year?: number;
}
export interface ProjectComparison extends Omit<ComparisonInput, 'year'> {
  readonly year: number | null;
  readonly schema_version: string;
  readonly id: string | null;
  readonly project_id: string;
  readonly rows: readonly {
    readonly company: CompanyIdentity;
    readonly report: ReportIdentity;
    readonly cells: readonly FactValue[];
    readonly status: 'complete' | 'partial' | 'unavailable';
    readonly warnings: readonly ReportWarning[];
  }[];
  readonly proposal_facts: readonly FactValue[];
  readonly warnings: readonly ReportWarning[];
  readonly rule_version: string;
}
export type DiscussionContext =
  | { readonly kind: 'evidence'; readonly label: string; readonly evidence_ref: string }
  | { readonly kind: 'comparison'; readonly label: string; readonly selection: ComparisonInput };
