// Redesign smoke test for the condensed Proje Özeti: the three "story" tables
// render the right metrics with correct % proportions, a row click opens the
// KpiDetailModal, the Proje Sağlığı card renders its three %s + signal, and the
// Maliyet Dağılımı section + drill-down modal render. useFetch is mocked and
// dispatched by URL so each section gets its own payload.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => {
  const empty = { data: null as any, meta: null as any, loading: false, error: null as string | null, refetch: () => {} };
  return {
    showUsd: true,
    dashboard: { ...empty },
    period: { ...empty },
    cashflow: { ...empty },
    bySub: { ...empty },
    milestones: { ...empty, data: [] as any[] },
  };
});

// Dispatch useFetch by URL: dashboard / period-summary / by-subcategory / cashflow / milestones.
vi.mock("@/hooks/useFetch", () => ({
  useFetch: (url: string | null) => {
    if (url == null) return { data: null, meta: null, loading: false, error: null, refetch: () => {} };
    if (url.includes("/by-subcategory")) return h.bySub;
    if (url.includes("/period-summary")) return h.period;
    if (url.includes("/cashflow")) return h.cashflow;
    if (url.includes("/milestones")) return h.milestones;
    return h.dashboard;
  },
}));

vi.mock("@/components/currency", () => ({
  useShowUsd: () => h.showUsd,
  CurrencyToggle: () => null,
  UsdMissingNote: () => null,
}));
vi.mock("@/lib/api", () => ({ apiPost: vi.fn(() => Promise.resolve({})), apiPut: vi.fn(() => Promise.resolve({})), apiDelete: vi.fn(() => Promise.resolve({})) }));
vi.mock("@/store/auth", () => ({ useAuth: (sel: any) => sel({ user: { role: "director" } }) }));
vi.mock("@/store/aiSummary", () => ({
  useAISummaryStore: () => ({
    getSummary: () => ({ content: "özet", generatedAt: "2026-06-17T00:00:00Z" }),
    setSummary: () => {},
    clearSummary: () => {},
  }),
}));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/charts", () => ({
  CashFlowChart: () => null,
  MarginBridgeChart: () => null,
  SCurveChart: () => null,
  MetricLineChart: () => null,
}));
vi.mock("@/components/RAGIndicator", () => ({ RAGIndicator: () => null }));
vi.mock("@/components/UnitScheduleEditor", () => ({ ResidentialDetailsEditor: () => null, unitsForPayload: () => [] }));
vi.mock("@/components/dashboard/CostEntriesDrawer", () => ({ CostEntriesDrawer: () => null }));
vi.mock("@/components/layout/AppLayout", () => ({ PageHeader: ({ title }: { title: string }) => createElement("h1", null, title) }));
vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "p1" }),
  useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));

import ProjectDashboardPage from "./ProjectDashboardPage";

const PROJECT = {
  id: "p1", name: "Test Projesi", client_name: "ACME", project_code: "PRJ-1",
  project_type: "infrastructure", units: [], construction_gross_m2: null, construction_net_m2: null,
  target_margin_pct: "15", start_date: "2020-01-01", planned_end_date: "2020-12-31",
  financing_enabled_override: null, financing_annual_rate_pct_override: null,
};
const FINANCIALS = {
  contract_value_try: "1000", total_invoiced_try: "500", total_collected_try: "250",
  total_outstanding_try: "250", total_retention_try: "100", revised_budget_try: "800",
  total_actual_with_vat_try: "400", remaining_budget_try: "400", margin_pct: "12.5",
  completion_pct: "40", rag_status: "amber", rag_label_tr: "Orta", rag_reason_tr: "x",
};
const FAC = {
  original_budget_try: "400", revised_budget_try: "800", cost_to_date_try: "400",
  cost_to_complete_try: "400", forecast_final_cost_try: "800", forecast_final_margin_pct: "11", over_budget: false,
};
const DASHBOARD = {
  project: PROJECT, financials: FINANCIALS, forecast_at_completion: FAC,
  cashflow: [], margin_bridge: null,
  usd: { costs: { amount_usd: "6789", usd_missing_count: 0 }, invoices: { amount_usd: "12345", usd_missing_count: 0 } },
};
const BY_SUB = {
  categories: [
    { cost_category: "material_concrete", label_tr: "Beton", amount_try: "300", total_with_vat_try: "360", subcategories: [{ subcategory: "Hazır Beton", amount_try: "300", total_with_vat_try: "360" }] },
    { cost_category: "labor", label_tr: "İşçilik", amount_try: "200", total_with_vat_try: "240", subcategories: [{ subcategory: "Belirtilmemiş", amount_try: "200", total_with_vat_try: "240" }] },
  ],
};

beforeEach(() => {
  h.showUsd = true;
  h.dashboard = { data: DASHBOARD, meta: null, loading: false, error: null, refetch: () => {} };
  h.period = { data: null, meta: null, loading: false, error: null, refetch: () => {} };
  h.cashflow = { data: null, meta: null, loading: false, error: null, refetch: () => {} };
  h.bySub = { data: BY_SUB, meta: null, loading: false, error: null, refetch: () => {} };
  h.milestones = { data: [], meta: null, loading: false, error: null, refetch: () => {} };
});
afterEach(cleanup);

describe("ProjectDashboardPage redesign", () => {
  it("renders the three story tables with the right metrics + % proportions", () => {
    render(createElement(ProjectDashboardPage));

    // Table titles
    expect(screen.getByText("Gelir & Tahsilat")).toBeInTheDocument();
    expect(screen.getByText("Bütçe & Maliyet")).toBeInTheDocument();
    expect(screen.getByText("Kârlılık")).toBeInTheDocument();

    // Metric rows
    expect(screen.getByText("İşverene Faturalanan")).toBeInTheDocument();
    expect(screen.getByText("Hakediş Kesintisi")).toBeInTheDocument();
    expect(screen.getByText("Orijinal Bütçe")).toBeInTheDocument();
    expect(screen.getByText("Güncel Kar Marjı")).toBeInTheDocument();
    expect(screen.getByText("Hedef Marj")).toBeInTheDocument();

    // % proportions: retention is 100/1000 = 10% of contract (unique), invoiced 50%.
    expect(screen.getByText("%10,0")).toBeInTheDocument();
    expect(screen.getAllByText("%50,0").length).toBeGreaterThan(0);
    // Kârlılık shows the margin itself, target margin is set.
    expect(screen.getByText("%12,5")).toBeInTheDocument();
    expect(screen.getByText("%15,0")).toBeInTheDocument();

    // USD shown where the block carries it (invoices snapshot; also in the top strip).
    expect(screen.getAllByText("$12,345.00").length).toBeGreaterThan(0);
  });

  it("opens KpiDetailModal when a metric row is clicked", () => {
    render(createElement(ProjectDashboardPage));

    // Description only exists inside the modal.
    expect(screen.queryByText(/İşverene kesilen hakediş ve faturaların toplam tutarı/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("İşverene Faturalanan"));
    expect(screen.getByText(/İşverene kesilen hakediş ve faturaların toplam tutarı/)).toBeInTheDocument();
  });

  it("renders the Proje Sağlığı card with the three %s and a signal", () => {
    render(createElement(ProjectDashboardPage));

    expect(screen.getByText("Proje Sağlığı")).toBeInTheDocument();
    expect(screen.getByText("% Tamamlandı")).toBeInTheDocument();
    expect(screen.getByText("% Bütçe Harcandı")).toBeInTheDocument();
    expect(screen.getByText("% Süre Geçti")).toBeInTheDocument();
    // start+end both in the past → time elapsed = 100% → cost/time lead progress → Riskli.
    expect(screen.getAllByText("Riskli").length).toBeGreaterThan(0);
  });

  it("renders Maliyet Dağılımı and opens its drill-down modal", () => {
    render(createElement(ProjectDashboardPage));

    expect(screen.getByText("Maliyet Dağılımı")).toBeInTheDocument();
    expect(screen.getByText("Beton")).toBeInTheDocument();
    // Beton = 360 / 600 = 60% of total cost.
    expect(screen.getByText("%60,0")).toBeInTheDocument();

    // Subcategory detail only exists inside the modal.
    expect(screen.queryByText("Hazır Beton")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Maliyet Dağılımı"));
    expect(screen.getByText("Hazır Beton")).toBeInTheDocument();
  });

  it("shows a retryable error if the cost breakdown fails (not an empty state)", () => {
    h.bySub = { data: null, meta: null, loading: false, error: "500", refetch: () => {} };
    render(createElement(ProjectDashboardPage));
    expect(screen.getByText(/Maliyet dağılımı yüklenemedi/)).toBeInTheDocument();
  });

  it("shows a retryable error on the period charts when the ranged cashflow fetch fails (not an empty state)", () => {
    const refetch = vi.fn();
    h.cashflow = { data: null, meta: null, loading: false, error: "500", refetch };
    render(createElement(ProjectDashboardPage));
    // Activate a date range so the ranged cashflow fetch drives the S-curve + cashflow charts.
    fireEvent.click(screen.getByText("Son 3 Ay"));
    // Both charts surface the retryable error instead of collapsing to a silent "no data".
    expect(screen.getAllByText("Dönem grafiği yüklenemedi.").length).toBe(2);
    expect(screen.queryByText("Henüz maliyet verisi yok.")).not.toBeInTheDocument();
    expect(screen.queryByText("Henüz nakit hareketi yok.")).not.toBeInTheDocument();
    // Retry is wired to the ranged-cashflow refetch.
    fireEvent.click(screen.getAllByText("Tekrar Dene")[0]);
    expect(refetch).toHaveBeenCalled();
  });

  it("non-ranged charts show the normal EmptyState (not LoadError) when there is simply no data", () => {
    // Default window comes from the dashboard fetch (cashflow: []). No range is
    // active, so the charts must read as "no data" — never a failure.
    render(createElement(ProjectDashboardPage));
    expect(screen.getByText("Henüz maliyet verisi yok.")).toBeInTheDocument();
    expect(screen.getByText("Henüz nakit hareketi yok.")).toBeInTheDocument();
    expect(screen.queryByText("Dönem grafiği yüklenemedi.")).not.toBeInTheDocument();
  });

  it("a cashflow error does NOT leak a chart LoadError while NO range is active", () => {
    // With the default preset ("Tümü") the ranged cashflow fetch is disabled
    // (URL=null, never fetched), so an error parked on it must never surface — the
    // charts fall back to the dashboard window and read as empty, not failed.
    h.cashflow = { data: null, meta: null, loading: false, error: "500", refetch: () => {} };
    render(createElement(ProjectDashboardPage));
    expect(screen.queryByText("Dönem grafiği yüklenemedi.")).not.toBeInTheDocument();
    expect(screen.getByText("Henüz maliyet verisi yok.")).toBeInTheDocument();
    expect(screen.getByText("Henüz nakit hareketi yok.")).toBeInTheDocument();
  });

  it("renders LoadError+retry (not an infinite skeleton) when the dashboard load fails/times out", () => {
    const refetch = vi.fn();
    h.dashboard = { data: null, meta: null, loading: false, error: "İstek zaman aşımına uğradı.", refetch };
    render(createElement(ProjectDashboardPage));
    // The retry affordance is shown; the normal story tables are NOT rendered.
    expect(screen.getByText("Tekrar Dene")).toBeInTheDocument();
    expect(screen.queryByText("Gelir & Tahsilat")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Tekrar Dene"));
    expect(refetch).toHaveBeenCalled();
  });

  // --- Display fixes: divide-by-zero + neutral health ---------------------- #
  it("renders '—' (not %0,0) in the % columns when the denominators are 0", () => {
    // Headline budget is 0 (real project): no Sözleşme/Revize base → no proportion.
    const zeroProject = { ...PROJECT, completion_pct: "0", target_margin_pct: null };
    const zeroFin = {
      ...FINANCIALS, contract_value_try: "0", total_invoiced_try: "0", total_collected_try: "0",
      total_outstanding_try: "0", total_retention_try: "0", revised_budget_try: "0",
      total_actual_with_vat_try: "0", remaining_budget_try: "0", completion_pct: "0",
      margin_pct: "5", // Kârlılık shows a real value, not a divide
    };
    const zeroFac = {
      ...FAC, original_budget_try: "0", revised_budget_try: "0", cost_to_date_try: "0",
      cost_to_complete_try: "0", forecast_final_cost_try: "0", forecast_final_margin_pct: "8",
    };
    h.dashboard = { data: { ...DASHBOARD, project: zeroProject, financials: zeroFin, forecast_at_completion: zeroFac }, meta: null, loading: false, error: null, refetch: () => {} };
    render(createElement(ProjectDashboardPage));

    // No "%0,0" anywhere — zero-denominator proportions render as "—".
    expect(screen.queryByText("%0,0")).not.toBeInTheDocument();
    // The em-dash proportion is present in the % columns.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("Proje Sağlığı shows the neutral state (not a false 'Riskli') when completion + budget are unset", () => {
    const zeroProject = { ...PROJECT, completion_pct: "0", target_margin_pct: null };
    const zeroFin = { ...FINANCIALS, revised_budget_try: "0", total_actual_with_vat_try: "0", completion_pct: "0", margin_pct: "5" };
    const zeroFac = { ...FAC, revised_budget_try: "0" };
    // No `milestones` block → no objective progress → completion is a blank default.
    h.dashboard = { data: { ...DASHBOARD, project: zeroProject, financials: zeroFin, forecast_at_completion: zeroFac }, meta: null, loading: false, error: null, refetch: () => {} };
    render(createElement(ProjectDashboardPage));

    expect(screen.getByText("Proje Sağlığı")).toBeInTheDocument();
    expect(screen.queryByText("Riskli")).not.toBeInTheDocument();
    expect(screen.getAllByText("Yeterli veri yok").length).toBeGreaterThan(0);
  });

  // --- CR-019-C: schedule section + health wiring -------------------------- #
  const MS_BLOCK = { schedule_progress_pct: "75.00", total: 4, done: 3, next_deadline: "2099-01-01", overdue_count: 2, by_stage: [] };

  it("renders the Aşamalar & Kilometre Taşları section with progress/next/overdue", () => {
    h.dashboard = { data: { ...DASHBOARD, milestones: MS_BLOCK }, meta: null, loading: false, error: null, refetch: () => {} };
    render(createElement(ProjectDashboardPage));

    expect(screen.getByText("Aşamalar & Kilometre Taşları")).toBeInTheDocument();
    expect(screen.getByText("3 / 4 tamamlandı")).toBeInTheDocument();
    expect(screen.getByText(/Sıradaki:/)).toBeInTheDocument();
    expect(screen.getByText(/2 gecikmiş/)).toBeInTheDocument();
  });

  it("Proje Sağlığı uses the milestone-derived % (labeled) when milestones exist", () => {
    h.dashboard = { data: { ...DASHBOARD, milestones: MS_BLOCK }, meta: null, loading: false, error: null, refetch: () => {} };
    render(createElement(ProjectDashboardPage));
    // The % Tamamlandı bar is labeled as milestone-based.
    expect(screen.getByText("% Tamamlandı (kilometre taşı)")).toBeInTheDocument();
    expect(screen.queryByText("% Tamamlandı")).not.toBeInTheDocument(); // plain label not used
  });

  it("uses the manual completion (plain label) when there are no milestones", () => {
    // Default DASHBOARD has no milestones block.
    render(createElement(ProjectDashboardPage));
    expect(screen.getByText("% Tamamlandı")).toBeInTheDocument();
    expect(screen.queryByText("% Tamamlandı (kilometre taşı)")).not.toBeInTheDocument();
  });

  it("milestones do not change any money display (separate lanes §0.2)", () => {
    // Money proportions/margins are identical whether or not milestones exist.
    h.dashboard = { data: { ...DASHBOARD, milestones: MS_BLOCK }, meta: null, loading: false, error: null, refetch: () => {} };
    render(createElement(ProjectDashboardPage));
    expect(screen.getByText("%10,0")).toBeInTheDocument();   // retention 100/1000
    expect(screen.getByText("%12,5")).toBeInTheDocument();   // güncel kar marjı
    expect(screen.getAllByText("$12,345.00").length).toBeGreaterThan(0); // USD snapshot
  });
});
