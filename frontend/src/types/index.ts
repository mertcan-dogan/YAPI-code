// Shared TypeScript interfaces mirroring backend schemas.

export type Role = "director" | "project_manager" | "finance" | "site_manager";
export type RAG = "red" | "amber" | "green";

export interface User {
  id: string;
  company_id: string;
  full_name: string;
  email: string;
  role: Role;
  phone: string | null;
  preferred_language: string;
  is_active: boolean;
  last_login_at: string | null;
  // CR-006-D: surfaced via /auth/me so the sidebar can render the company logo.
  company_name?: string | null;
  company_logo_url?: string | null;
}

export interface ProjectFinancials {
  contract_value_try: string;
  revised_budget_try: string;
  total_committed_try: string;
  total_actual_try: string;
  total_actual_with_vat_try: string;
  remaining_budget_try: string;
  forecast_final_cost_try: string;
  current_profit_try: string;
  margin_pct: string;
  total_invoiced_try: string;
  total_collected_try: string;
  total_outstanding_try: string;
  total_retention_try: string;
  net_cash_position_try: string;
  overdue_count: number;
  max_overdue_days: number;
  time_completion_pct: string;
  completion_pct: string;
  rag_status: RAG;
  rag_label_tr: string;
  rag_reason_tr: string;
  categories?: BudgetCategoryRow[];
  estimated_finish_date?: string | null;
}

export interface Project {
  id: string;
  company_id: string;
  name: string;
  project_code: string;
  project_type: string;
  // CR: revenue/billing model — hakedis | kat_karsiligi | yap_sat | hasilat_paylasimi | maliyet_kar
  revenue_model: string;
  contractor_share_pct: string | null;
  unit_count: number | null;
  client_name: string;
  client_contact: string | null;
  contract_number: string | null;
  location: string | null;
  description: string | null;
  contract_value_try: string;
  contract_value_eur: string | null;
  eur_try_rate: string;
  start_date: string;
  planned_end_date: string;
  actual_end_date: string | null;
  status: string;
  retention_pct: string;
  contingency_pct: string;
  original_budget_try: string;
  approved_variations_try: string;
  target_margin_pct: string | null;
  completion_pct: string;
  project_manager_id: string | null;
  // CR-016: residential / kentsel dönüşüm details (empty for other projects).
  construction_gross_m2: string | null;
  construction_net_m2: string | null;
  units: ProjectUnit[];
  // CR-015: per-project financing overrides (null = inherit company default).
  financing_enabled_override: boolean | null;
  financing_annual_rate_pct_override: string | null;
  financials?: ProjectFinancials;
}

// CR-016: a daire dağılımı row as returned by the API.
export interface ProjectUnit {
  id: string;
  project_id: string;
  company_id: string;
  unit_type: string;
  custom_label: string | null;
  count: number;
  gross_m2_each: string;
  net_m2_each: string | null;
  sale_price_try: string | null;
  notes: string | null;
}

// CR-016-B: computed residential aggregates on the dashboard payload.
export interface ResidentialAggregates {
  total_units: number;
  total_sellable_gross_m2: string;
  total_sellable_net_m2: string;
  total_estimated_sales_try: string | null;
}

export interface BudgetCategoryRow {
  cost_category: string;
  label_tr?: string;
  original_budget_try: string;
  approved_variations_try: string;
  revised_budget_try: string;
  committed_try: string;
  open_committed_try?: string; // CR-023: açık taahhüt (committed − linked actuals)
  exposure_try?: string; // CR-023: actual + open committed
  invoiced_try: string;
  paid_try: string;
  remaining_try: string;
  pct_spent: string;
  forecast_final: string;
  variance_try: string;
  status: RAG | "gray";
}

export interface CostEntry {
  id: string;
  project_id: string;
  entry_date: string;
  entry_type: string;
  cost_category: string;
  subcategory: string | null;
  supplier_name: string | null;
  description: string | null;
  invoice_number: string | null;
  amount_try: string;
  amount_usd?: string | null;
  fx_rate_usd?: string | null;
  vat_rate: string;
  vat_amount_try: string;
  total_with_vat_try: string;
  payment_due_date: string | null;
  payment_status: string;
  date_paid: string | null;
  amount_paid_try: string;
  document_url: string | null;
  notes: string | null;
  commitment_id?: string | null; // CR-023: relief link (actual → committed entry)
  po_number?: string | null;
  expected_date?: string | null;
  // CR-024: AI document-extraction confidence (0..1); null on manual/Excel rows.
  extraction_confidence?: number | null;
}

export interface ClientInvoice {
  id: string;
  project_id: string;
  invoice_number: string;
  invoice_date: string;
  hakkedis_period: string | null;
  invoice_type: string;
  description: string | null;
  amount_try: string;
  amount_usd?: string | null;
  fx_rate_usd?: string | null;
  vat_rate: string;
  vat_amount_try: string;
  total_with_vat_try: string;
  retention_amount_try: string;
  net_due_try: string;
  due_date: string;
  payment_status: string;
  date_received: string | null;
  amount_received_try: string;
  outstanding_try: string;
  document_url: string | null;
  // CR-024: AI document-extraction confidence (0..1); null on manual rows.
  extraction_confidence?: number | null;
}

// --- CR-031: Satışlar & Kar/Zarar (sell-side revenue lane) ---
export interface UnitSale {
  id: string;
  project_id: string;
  project_unit_id: string | null;
  unit_label: string;
  unit_type: string | null;
  floor: string | null;
  gross_m2: string | null;
  net_m2: string | null;
  buyer_name: string | null;
  sale_price_try: string;
  sale_date: string;
  fx_rate_usd: string | null;
  sale_price_usd: string | null;
  payment_type: string | null;
  installment_note: string | null;
  deed_status: string | null;
  deed_date: string | null;
  owner_side: string;
  notes: string | null;
}

// A unit_sales GET row: the sale fields + read-time cost-allocation P&L (CR-031-A).
export interface UnitSaleAllocation extends UnitSale {
  basis_m2: string | null;
  unit_cost_try: string | null;
  unit_cost_usd: string | null;
  pnl_try: string | null;
  pnl_usd: string | null;
  margin_pct: string | null;
}

export interface UnitSalesPayload {
  basis: "net" | "gross";
  denom_m2: string;
  allocations: UnitSaleAllocation[];
  totals: {
    count: number;
    sale_price_try: string;
    sale_price_usd: string;
    cost_try: string;
    cost_usd: string;
    pnl_try: string;
    pnl_usd: string;
    total_m2: string;
    avg_price_per_m2_try: string | null;
    margin_pct: string | null;
  };
  cost_total_try: string;
  cost_total_usd: string;
  usd_missing_count: number;
}

export interface LandownerPayment {
  id: string;
  payer_name: string | null;
  committed_total_try: string | null;
  payment_date: string;
  amount_try: string;
  amount_usd: string | null;
  fx_rate_usd: string | null;
  payment_type: string | null;
  description: string | null;
  notes: string | null;
}

export interface LandownerLedger {
  payments: LandownerPayment[];
  rollup: {
    total_try: string;
    total_usd: string;
    count: number;
    committed_total_try: string | null;
    remaining_try: string | null;
    pct_paid: string | null;
    usd_missing_count: number;
  };
}

interface PnlTrio {
  try: string | null;
  usd: string | null;
  try_today: string | null;
}

export interface ProjectPnl {
  revenue_model: string;
  revenue_source: "sales" | "hakedis";
  revenue_breakdown: Record<string, string>;
  revenue_try: string;
  revenue_usd: string;
  cost_try: string;
  cost_usd: string;
  financing_try: string;
  financing_usd: string;
  net_excl_financing_try: string;
  net_incl_financing_try: string;
  net_excl_financing_usd: string;
  net_incl_financing_usd: string;
  margin_pct: string | null;
  margin_incl_financing_pct: string | null;
  usd_missing_count: number;
  m2_analysis: {
    gross_m2: string | null;
    net_m2: string | null;
    unit_count: number | null;
    floor_count: number | null;
    per_gross_m2: PnlTrio;
    per_net_m2: PnlTrio;
    per_unit: PnlTrio;
    per_floor: PnlTrio;
  };
  fx_effect: {
    today_rate: string | null;
    cost_try_original: string;
    cost_try_today: string | null;
    fx_effect_try: string | null;
    fx_effect_pct: string | null;
  };
  split?: {
    contractor_share_pct: string | null;
    contractor: { sales_try: string; sales_usd: string; allocated_cost_try: string | null };
    landowner: { sales_try: string; sales_usd: string; payments_try: string; payments_usd: string; allocated_cost_try: string | null };
  };
}

export interface InvestmentReturn {
  irr_try_pct: string | null;
  irr_usd_pct: string | null;
  roi_pct: string | null;
  net_profit_try: string;
  total_cost_try: string;
  duration_months: number | null;
  profit_per_net_m2_try: string | null;
  profit_per_unit_try: string | null;
  revenue_source: "sales" | "hakedis";
  yearly: {
    year: number;
    inflow_try: string;
    outflow_try: string;
    net_try: string;
    inflow_usd: string;
    outflow_usd: string;
    net_usd: string;
  }[];
}

export interface Subcontractor {
  id: string;
  project_id: string;
  name: string;
  scope_of_work: string | null;
  contract_value_try: string;
  approved_variations_try: string;
  retention_pct: string;
  status: string;
  contact_name: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  revised_contract_try: string;
  total_paid_try: string;
  retention_held_try: string;
  progress_pct: string;
}

export interface Equipment {
  id: string;
  equipment_name: string;
  ownership_type: string;
  supplier_name: string | null;
  rate_try: string | null;
  rate_unit: string | null;
  deployment_start: string;
  deployment_end: string | null;
  fuel_maintenance_try: string;
  notes?: string | null;
  photo_urls?: string[];
  duration_days: number | null;
  total_cost_try: string | null;
}

export interface Reminder {
  kind: "payable" | "receivable";
  project_id: string;
  project_name: string;
  party: string;
  description: string;
  amount_try: string;
  due_date: string;
  days_remaining: number;
  days_label: string;
  border_colour: string;
  status: string;
  record_id: string;
}

export interface Variation {
  id: string;
  project_id: string;
  variation_number: string;
  title: string;
  description: string | null;
  submitted_date: string;
  approved_date: string | null;
  status: string;
  value_try: string;
  approved_value_try: string | null;
  cost_impact_try: string;
  margin_impact_try: string;
  cost_category: string | null;
  document_url: string | null;
  notes: string | null;
}

export interface AIAlert {
  id: string;
  project_id: string | null;
  alert_type: string;
  severity: "high" | "medium" | "low";
  title_tr: string;
  body_tr: string;
  reasoning: string | null;
  recommended_action: string | null;
  is_actioned: boolean;
  created_at: string;
  feedback?: string | null;
  // CR-022: record linkage for assurance findings (NULL on legacy health alerts).
  source_type?: string | null;
  source_id?: string | null;
  dedup_key?: string | null;
}

// CR-022-B: POST /ai/assurance/scan summary.
export interface AssuranceScanSummary {
  scanned: { cost_entries: number; client_invoices: number };
  found: Record<string, number>;
  total_found: number;
  created: number;
}

// Proje Kapanışı (project closeout) — lifecycle Aktif → Geçici Kabul → Kesin Hesap
// → Kesin Kabul. `stage` is the FURTHEST stage reached (or null when not started).
export type CloseoutStage = "gecici_kabul" | "kesin_hesap" | "kesin_kabul";

export interface CloseoutSummary {
  project_name: string;
  client_name: string;
  contract_value: string;
  total_actual: string;
  forecast_final: string;
  margin_pct: string;
  net_cash: string;
  report_date: string;
  generated_at: string;
}

export interface CloseoutObj {
  id: string;
  project_id: string;
  company_id: string;
  stage: CloseoutStage | null;
  gecici_kabul_date: string | null;
  kesin_hesap_date: string | null;
  kesin_kabul_date: string | null;
  is_active: boolean;
  frozen_at: string | null;
  reopened_at: string | null;
  created_at: string;
  // The /closeouts archive list carries these per record (newest first).
  summary?: CloseoutSummary | null;
  report_frozen?: boolean;
}

// GET /projects/{id}/closeout envelope.
export interface CloseoutResponse {
  closeout: CloseoutObj | null;
  project_status: "active" | "completed";
  summary: CloseoutSummary | null;
  report_frozen: boolean;
  report_stale: boolean;
}
