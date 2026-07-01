// CR-031-F: SalesPnlPage revenue-model awareness + profit/loss coloring.
// useFetch is mocked and dispatched by URL so each block gets its own payload.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => {
  const empty = { data: null as any, meta: null as any, loading: false, error: null as string | null, refetch: () => {} };
  return { project: { ...empty }, dashboard: { ...empty }, sales: { ...empty }, ledger: { ...empty } };
});

vi.mock("@/hooks/useFetch", () => ({
  useFetch: (url: string | null) => {
    if (url == null) return { data: null, meta: null, loading: false, error: null, refetch: () => {} };
    if (url.includes("/unit-sales")) return h.sales;
    if (url.includes("/landowner-payments")) return h.ledger;
    if (url.includes("/dashboard")) return h.dashboard;
    return h.project;
  },
}));
vi.mock("@/components/currency", () => ({
  useShowUsd: () => false,
  CurrencyToggle: () => null,
  UsdMissingNote: () => null,
}));
vi.mock("@/components/ExportMenu", () => ({ ExportMenu: () => null }));
vi.mock("@/lib/api", () => ({ apiPost: vi.fn(), apiPut: vi.fn(), apiDelete: vi.fn() }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/layout/AppLayout", () => ({
  PageHeader: ({ title, action }: { title: string; action?: any }) => createElement("div", null, createElement("h1", null, title), action),
}));
vi.mock("react-router-dom", () => ({ useParams: () => ({ id: "p1" }) }));

import SalesPnlPage from "./SalesPnlPage";

const NULL_TRIO = { try: null, usd: null, try_today: null };
const M2 = { gross_m2: null, net_m2: null, unit_count: null, floor_count: null, per_gross_m2: NULL_TRIO, per_net_m2: NULL_TRIO, per_unit: NULL_TRIO, per_floor: NULL_TRIO };
const FX = { today_rate: null, cost_try_original: "400000", cost_try_today: null, fx_effect_try: null, fx_effect_pct: null };

// CR-053: sell-side operator-model extras (efektif arsa maliyeti + planned split).
const PLANNED_SPLIT = {
  has_schedule: true,
  total_gross_m2: "1000",
  contractor: { units: 6, gross_m2: "600", net_m2: "540", estimated_sales_try: "6000000.00" },
  landowner: { units: 4, gross_m2: "400", net_m2: "360", estimated_sales_try: null },
  sold: { units: 2, value_try: "2000000.00", value_usd: "0" },
  remaining: { units: 4, projected_value_try: "4000000.00" },
};

function pnl(source: "sales" | "hakedis", extra: any = {}) {
  const sellExtras =
    source === "sales"
      ? {
          efektif_arsa_maliyeti_try: "2000000.00",
          efektif_arsa_maliyeti_usd: null,
          landowner_share_pct: "40.00",
          landowner_share_basis: "units",
          planned_split: PLANNED_SPLIT,
        }
      : {};
  return {
    revenue_model: source === "sales" ? "kat_karsiligi" : "hakedis",
    revenue_source: source,
    revenue_breakdown:
      source === "sales"
        ? {
            unit_sales_try: "0.00",
            unit_sales_usd: "0.00",
            arsa_sahibi_sales_try: "0.00",
            arsa_sahibi_sales_usd: "0.00",
            landowner_try: "0.00",
            landowner_usd: "0.00",
            client_invoices_try: "0.00",
          }
        : { unit_sales_try: "0.00", landowner_try: "0.00", client_invoices_try: "0.00" },
    revenue_try: "500000", revenue_usd: "0", cost_try: "400000", cost_usd: "0",
    financing_try: "0.00", financing_usd: "0.00",
    net_excl_financing_try: "100000", net_incl_financing_try: "100000",
    net_excl_financing_usd: "0", net_incl_financing_usd: "0",
    margin_pct: "20.00", margin_incl_financing_pct: "20.00", usd_missing_count: 0,
    m2_analysis: M2, fx_effect: FX, ...sellExtras, ...extra,
  };
}
const IR = { irr_try_pct: "35.00", irr_usd_pct: null, roi_pct: "25.00", net_profit_try: "100000", total_cost_try: "400000", duration_months: 8, profit_per_net_m2_try: null, profit_per_unit_try: null, revenue_source: "sales", yearly: [] };

const SALES = {
  basis: "net", denom_m2: "300", cost_total_try: "400000", cost_total_usd: "0", usd_missing_count: 0,
  totals: { count: 2, sale_price_try: "7000000", sale_price_usd: "0", cost_try: "400000", cost_usd: "0", pnl_try: "266667.00", pnl_usd: "0", total_m2: "300", avg_price_per_m2_try: null, margin_pct: "5.00" },
  allocations: [
    { id: "s1", project_id: "p1", project_unit_id: null, unit_label: "A-1", unit_type: "3+1", floor: "1", gross_m2: null, net_m2: "100", buyer_name: "Ahmet", sale_price_try: "5000000", sale_date: "2025-09-01", fx_rate_usd: null, sale_price_usd: null, payment_type: "Peşin", installment_note: null, deed_status: "Devredildi", deed_date: null, owner_side: "yuklenici", notes: null, basis_m2: "100", unit_cost_try: "240000", unit_cost_usd: null, pnl_try: "612345.00", pnl_usd: null, margin_pct: "30.60" },
    { id: "s2", project_id: "p1", project_unit_id: null, unit_label: "B-2", unit_type: "2+1", floor: "2", gross_m2: null, net_m2: "200", buyer_name: "Mehmet", sale_price_try: "2000000", sale_date: "2025-08-01", fx_rate_usd: null, sale_price_usd: null, payment_type: "Taksit", installment_note: null, deed_status: null, deed_date: null, owner_side: "arsa_sahibi", notes: null, basis_m2: "200", unit_cost_try: "160000", unit_cost_usd: null, pnl_try: "-345678.00", pnl_usd: null, margin_pct: "-34.50" },
  ],
};
const LEDGER = { payments: [], rollup: { total_try: "0.00", total_usd: "0.00", count: 0, committed_total_try: null, remaining_try: null, pct_paid: null, usd_missing_count: 0 } };

beforeEach(() => {
  h.dashboard = { data: { pnl: pnl("sales"), investment_return: IR }, meta: null, loading: false, error: null, refetch: () => {} };
  h.sales = { data: SALES, meta: null, loading: false, error: null, refetch: () => {} };
  h.ledger = { data: LEDGER, meta: null, loading: false, error: null, refetch: () => {} };
});
afterEach(cleanup);

function setProject(revenue_model: string) {
  h.project = { data: { id: "p1", name: "Test Projesi", revenue_model }, meta: null, loading: false, error: null, refetch: () => {} };
}

describe("SalesPnlPage — revenue-model awareness", () => {
  it("sell-side: shows sales register + editors + P&L statement", () => {
    setProject("kat_karsiligi");
    render(createElement(SalesPnlPage));
    expect(screen.getByText("Satış Kaydı")).toBeInTheDocument();
    expect(screen.getByText("Satış Ekle")).toBeInTheDocument();
    expect(screen.getByText("Arsa Sahibi Ödemeleri")).toBeInTheDocument();
    expect(screen.getByText("Kar/Zarar Tablosu")).toBeInTheDocument();
    // No hakediş note for a sell-side model.
    expect(screen.queryByText(/Gelir, Hakediş'ten geliyor/)).not.toBeInTheDocument();
  });

  it("yap_sat: shows the sales register but hides the landowner ledger", () => {
    setProject("yap_sat");
    render(createElement(SalesPnlPage));
    expect(screen.getByText("Satış Kaydı")).toBeInTheDocument();
    expect(screen.queryByText("Arsa Sahibi Ödemeleri")).not.toBeInTheDocument();
  });

  it("hakediş: hides the sell-side editors, still shows P&L / m² / kur-etkisi", () => {
    setProject("hakedis");
    h.dashboard = { data: { pnl: pnl("hakedis"), investment_return: { ...IR, revenue_source: "hakedis" } }, meta: null, loading: false, error: null, refetch: () => {} };
    render(createElement(SalesPnlPage));
    expect(screen.getByText(/Gelir, Hakediş'ten geliyor/)).toBeInTheDocument();
    expect(screen.queryByText("Satış Kaydı")).not.toBeInTheDocument();
    expect(screen.queryByText("Satış Ekle")).not.toBeInTheDocument();
    // The P&L statement, m² analizi and kur-etkisi still render.
    expect(screen.getByText("Kar/Zarar Tablosu")).toBeInTheDocument();
    expect(screen.getByText("m² Maliyet Analizi")).toBeInTheDocument();
    expect(screen.getByText("Kur Etkisi")).toBeInTheDocument();
  });

  it("hakediş: P&L 'Gelir kaynağı' label reads Hakediş (maps from revenue_source)", () => {
    setProject("hakedis");
    h.dashboard = { data: { pnl: pnl("hakedis"), investment_return: { ...IR, revenue_source: "hakedis" } }, meta: null, loading: false, error: null, refetch: () => {} };
    render(createElement(SalesPnlPage));
    expect(screen.getByText("Gelir kaynağı: Hakediş")).toBeInTheDocument();
    expect(screen.queryByText("Gelir kaynağı: Yüklenici satışları + nakit katkı")).not.toBeInTheDocument();
    // CR-053: efektif arsa maliyeti + planlı daire dağılımı are sell-side only.
    expect(screen.queryByText("Efektif Arsa Maliyeti")).not.toBeInTheDocument();
    expect(screen.queryByText("Planlı Daire Dağılımı")).not.toBeInTheDocument();
  });

  it("sell-side: P&L 'Gelir kaynağı' label reflects the operator model (own sales + cash)", () => {
    setProject("kat_karsiligi");
    render(createElement(SalesPnlPage));
    // CR-053: revenue is the contractor's own sales + cash landowner contributions.
    expect(screen.getByText("Gelir kaynağı: Yüklenici satışları + nakit katkı")).toBeInTheDocument();
  });

  it("clarifies the two profit figures and shows the reconciling unsold-cost chip", () => {
    setProject("kat_karsiligi");
    render(createElement(SalesPnlPage));
    // Project Net vs sold-units margin disambiguation.
    expect(screen.getByText("tüm proje, bugüne kadar (satılmamış daireler dahil)")).toBeInTheDocument();
    expect(screen.getByText("yalnızca satılan dairelerin brüt karı")).toBeInTheDocument();
    // Reconciling line bridging the gap (cost of still-unsold units).
    expect(screen.getByText("Satılmamış daire maliyeti")).toBeInTheDocument();
  });

  it("colors per-unit profit green and loss red", () => {
    setProject("kat_karsiligi");
    render(createElement(SalesPnlPage));
    const profit = screen.getByText("612.345,00 ₺");
    const loss = screen.getByText("-345.678,00 ₺");
    expect(profit.className).toContain("text-success");
    expect(loss.className).toContain("text-danger");
  });
});

// CR-053: operator-model surfaces on the sell-side page.
describe("SalesPnlPage — CR-053 operator model", () => {
  it("sell-side: renders Efektif Arsa Maliyeti (derived, informational) with the amount", () => {
    setProject("kat_karsiligi");
    render(createElement(SalesPnlPage));
    expect(screen.getByText("Efektif Arsa Maliyeti")).toBeInTheDocument();
    // Efektif tutar 2.000.000,00 ₺ (also equals the sold value in the fixture → getAllByText).
    expect(screen.getAllByText("2.000.000,00 ₺").length).toBeGreaterThan(0);
    // The caption makes clear it is informational and NOT added to revenue/cost.
    expect(screen.getByText(/bilgi amaçlıdır/)).toBeInTheDocument();
    expect(screen.getByText(/arsa sahibi payı \(%40,0\)/)).toBeInTheDocument();
  });

  it("sell-side: renders Planlı Daire Dağılımı with sellable / sold / remaining", () => {
    setProject("kat_karsiligi");
    render(createElement(SalesPnlPage));
    expect(screen.getByText("Planlı Daire Dağılımı")).toBeInTheDocument();
    expect(screen.getByText("Yüklenici (satılabilir)")).toBeInTheDocument();
    expect(screen.getByText("Arsa Sahibi")).toBeInTheDocument();
    expect(screen.getByText("Satılan")).toBeInTheDocument();
    expect(screen.getByText("Kalan")).toBeInTheDocument();
    // Contractor sellable = 6 daire, remaining projection present.
    expect(screen.getByText("Projeksiyon: 4.000.000,00 ₺")).toBeInTheDocument();
  });

  it("sell-side: Efektif shows '–' when the figure is null (share not derivable)", () => {
    setProject("kat_karsiligi");
    h.dashboard = {
      data: { pnl: pnl("sales", { efektif_arsa_maliyeti_try: null, efektif_arsa_maliyeti_usd: null, landowner_share_pct: null }), investment_return: IR },
      meta: null, loading: false, error: null, refetch: () => {},
    };
    render(createElement(SalesPnlPage));
    expect(screen.getByText("Efektif Arsa Maliyeti")).toBeInTheDocument();
    expect(screen.getByText("–")).toBeInTheDocument();
  });

  it("sell-side: Planlı Daire Dağılımı degrades calmly with no schedule", () => {
    setProject("kat_karsiligi");
    h.dashboard = {
      data: { pnl: pnl("sales", { planned_split: { ...PLANNED_SPLIT, has_schedule: false } }), investment_return: IR },
      meta: null, loading: false, error: null, refetch: () => {},
    };
    render(createElement(SalesPnlPage));
    expect(screen.getByText("Planlı Daire Dağılımı")).toBeInTheDocument();
    expect(screen.getByText(/Daire dağılımı girilmemiş/)).toBeInTheDocument();
  });
});
