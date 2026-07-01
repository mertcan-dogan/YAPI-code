// CR-024-B — agent tool name → Turkish "what it did" label for the
// "AI nasıl çalıştı?" explainability panel.
//
// Keys mirror the real tool names in the backend (services/agent.py TOOL_REGISTRY
// + create_chart). Past tense, because the panel reports what already happened.
// Any unmapped name falls back to the raw name via toolLabel() so the UI never
// crashes if the backend adds a tool before this map is updated.

export const TOOL_LABELS: Record<string, string> = {
  list_projects: "Projeler listelendi",
  get_project_financials: "Proje finansalları okundu",
  query_cost_entries: "Maliyet kayıtları okundu",
  query_client_invoices: "Hakedişler okundu",
  query_subcontractors: "Alt yükleniciler okundu",
  get_vendor_spend: "Tedarikçi harcamaları okundu",
  compare_vendors: "Tedarikçiler karşılaştırıldı",
  get_cashflow: "Nakit akışı hesaplandı",
  get_overdue_payments: "Vadesi geçmiş ödemeler tarandı",
  create_chart: "Grafik oluşturuldu",
  // CR-011-B — new read-only tools.
  get_equipment_utilisation: "Ekipman kullanımı incelendi",
  get_budget_variance: "Bütçe-gerçekleşen sapması hesaplandı",
  get_retention_summary: "Teminat kesintileri incelendi",
  get_assurance_findings: "Finans Güvence bulguları okundu",
  // CR-011-C — propose-only action tools (each creates a pending approval).
  propose_reminder: "Hatırlatıcı önerisi oluşturuldu",
  propose_flag_invoice: "İnceleme işareti önerisi oluşturuldu",
  propose_followup_task: "Görev önerisi oluşturuldu",
};

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}
