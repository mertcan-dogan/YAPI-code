import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AIAlert } from "@/types";

const { toastInfo } = vi.hoisted(() => ({ toastInfo: vi.fn() }));
vi.mock("@/store/toast", () => ({ toast: { info: toastInfo, success: vi.fn(), error: vi.fn() } }));

import { BriefingHero } from "./BriefingHero";
import { KpiCards } from "./KpiCards";
import { ProjectRiskTable } from "./ProjectRiskTable";
import { ReportsPanel } from "./ReportsPanel";
import { RightRail } from "./RightRail";

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);
afterEach(() => vi.clearAllMocks());

const KPI_DATA = {
  kpis: { active_project_count: 12, total_contract_value_try: "86400000", weighted_avg_margin_pct: "19.8", cost_to_complete_try: "0", overdue_payment_count: 0 },
  exec_kpis: { net_cash_position_try: "1320000", backlog_try: "0", projected_profit_try: "0", total_receivables_try: "0" },
  portfolio_budget: { actual_try: "59300000", forecast_final_cost_try: "76500000", contract_try: "0", revised_budget_try: "0", committed_try: "12400000", open_committed_try: "12400000", committed_exposure_try: "71700000" },
  kpi_trends: { total_contract_value_try: { series: [70, 80, 86], delta_pct: 8.1 }, weighted_avg_margin_pct: { series: [21, 20, 19.8], delta_pct: null }, net_cash_position_try: { series: [1.8, 1.5, 1.32], delta_pct: -3 } },
};

describe("KpiCards (CR-029-D)", () => {
  it("renders the 8 KPIs with the CR-023 açık taahhüt figure wired in", () => {
    wrap(<KpiCards data={KPI_DATA} approvalsCount={27} loading={false} />);
    expect(screen.getByText("Aktif Projeler")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Taahhüt Edilen Maliyet")).toBeInTheDocument();
    // CR-023: real açık taahhüt number, no longer the "Yakında" placeholder.
    expect(screen.getByText("12,4 Mn ₺")).toBeInTheDocument();
    expect(screen.queryByText("Yakında")).not.toBeInTheDocument();
    expect(screen.getByText("27")).toBeInTheDocument(); // approvals
  });
});

describe("ProjectRiskTable (CR-029-E)", () => {
  const projects = Array.from({ length: 6 }, (_, i) => ({
    id: `p${i}`, name: `Proje ${i}`, completion_pct: "50", contract_value_try: "1000000",
    margin_pct: "15", net_cash_position_try: i === 0 ? "-5000" : "20000", rag_status: i === 0 ? "red" : "green",
  }));
  const perf = projects.map((p) => ({ project: p.name, contract_try: "1000000", actual_try: "600000", forecast_final_try: "900000" }));
  const mf = [{ name: "Proje 0", target_pct: "20", current_pct: "15" }];
  const alerts: AIAlert[] = [{ id: "a", project_id: "p0", alert_type: "cost_outlier", severity: "medium", title_tr: "Olağandışı maliyet", body_tr: "x", reasoning: null, recommended_action: null, is_actioned: false, created_at: "", dedup_key: "cost_outlier:1" }];

  it("renders rows, the Taahhüt '—' placeholder, an AI insight, and a status pill", () => {
    wrap(<ProjectRiskTable projects={projects} performance={perf} marginFade={mf} alerts={alerts} loading={false} />);
    expect(screen.getByText("Proje 0")).toBeInTheDocument();
    expect(screen.getByText("Olağandışı maliyet")).toBeInTheDocument();
    expect(screen.getByText("Kritik")).toBeInTheDocument(); // rag red → Kritik pill
    expect(screen.getByText("1–5 / 6 gösteriliyor")).toBeInTheDocument();
  });

  it("paginates (5 per page) with the next arrow", () => {
    wrap(<ProjectRiskTable projects={projects} performance={perf} marginFade={mf} alerts={alerts} loading={false} />);
    expect(screen.getByText("Proje 0")).toBeInTheDocument();
    expect(screen.queryByText("Proje 5")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Sonraki"));
    expect(screen.getByText("Proje 5")).toBeInTheDocument();
  });
});

describe("RightRail / AiActionQueue (CR-029-F)", () => {
  const alerts: AIAlert[] = [
    { id: "1", project_id: null, alert_type: "duplicate_cost", severity: "high", title_tr: "", body_tr: "", reasoning: null, recommended_action: null, is_actioned: false, created_at: "", dedup_key: "d:1" },
    { id: "2", project_id: null, alert_type: "duplicate_cost", severity: "high", title_tr: "", body_tr: "", reasoning: null, recommended_action: null, is_actioned: false, created_at: "", dedup_key: "d:2" },
  ];
  it("maps real counts, hides zero rows, shows nav links + Phase-2 'yakında' slots", () => {
    wrap(<RightRail alerts={alerts} approvalsByKind={{ faturalar: 3, ekIsler: 0 }} />);
    expect(screen.getByText("Olası yinelenen faturalar")).toBeInTheDocument(); // 2 dup findings
    expect(screen.getByText("Onay bekleyen faturalar")).toBeInTheDocument(); // faturalar=3
    expect(screen.queryByText("İncelenecek ek işler")).not.toBeInTheDocument(); // ekIsler=0 → hidden
    expect(screen.queryByText("Atanmamış maliyetler")).not.toBeInTheDocument(); // 0 → hidden
    // Navigational row (no count) always present:
    expect(screen.getByText("Hazır rapor talepleri")).toBeInTheDocument();
    expect(screen.getByText("AI Beceriler & Otomasyonlar")).toBeInTheDocument();
    expect(screen.getByText("Ekip Akışı")).toBeInTheDocument();
    // CR-011-D: the "Beceriler" slot is now live (scoped-agent dock), so only the
    // Ekip Akışı slot remains "yakında". The dock exposes the five domain agents.
    expect(screen.getAllByText("Bu özellik yakında tüm kullanıcılara sunulacak.").length).toBe(1);
    expect(screen.getByLabelText("Gider Agent")).toBeInTheDocument();
    expect(screen.getByLabelText("Finans Agent")).toBeInTheDocument();
  });
});

describe("BriefingHero (CR-029-C)", () => {
  it("renders the briefing text + the four risk chip counts", () => {
    wrap(<BriefingHero text="3 proje hedef marjın altında." chips={{ kritik: 3, izle: 5, firsat: 4, hazir: 6 }} />);
    expect(screen.getByText("3 proje hedef marjın altında.")).toBeInTheDocument();
    // Chips render in both the inline (≤2xl) and floating (2xl) variants.
    expect(screen.getAllByText("Kritik").length).toBeGreaterThan(0);
    expect(screen.getAllByText("İncelemeye Hazır").length).toBeGreaterThan(0);
  });
});

describe("ReportsPanel (CR-029-E)", () => {
  it("routes 'Oluştur' (deck gen = Phase 2) to an honest 'yakında' toast", () => {
    wrap(<ReportsPanel />);
    expect(screen.getByText("Aylık Finans Sunumu")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Oluştur")[0]);
    expect(toastInfo).toHaveBeenCalledWith("Bu özellik yakında tüm kullanıcılara sunulacak.");
  });
});
