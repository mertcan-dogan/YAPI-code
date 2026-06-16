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
  financials?: ProjectFinancials;
}

export interface BudgetCategoryRow {
  cost_category: string;
  label_tr?: string;
  original_budget_try: string;
  approved_variations_try: string;
  revised_budget_try: string;
  committed_try: string;
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
  vat_rate: string;
  vat_amount_try: string;
  total_with_vat_try: string;
  payment_due_date: string | null;
  payment_status: string;
  date_paid: string | null;
  amount_paid_try: string;
  document_url: string | null;
  notes: string | null;
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
}
