import { CashFlowChart, MetricLineChart, PortfolioBudgetChart, PortfolioPerformanceChart } from "@/components/charts";
import { KPICard } from "@/components/KPICard";
import { type BudgetBreakdownItem } from "@/components/dashboard/BudgetBreakdownCard";
import { DashboardSection } from "@/components/dashboard/DashboardSection";
import { DashboardToolbar, DEFAULT_FILTERS, type DashboardFilters } from "@/components/dashboard/DashboardToolbar";
import { YapiAIRail } from "@/components/dashboard/YapiAIRail";
import { ApprovalsPanel } from "@/components/dashboard/ApprovalsPanel";
import { KpiDetailModal, type KpiInfo } from "@/components/dashboard/KpiDetailModal";
import { IncomingWorkflowCard } from "@/components/dashboard/IncomingWorkflowCard";
import { type BriefingItem } from "@/components/dashboard/InsightItem";
import { OverduePaymentsModal, LowMarginModal } from "@/components/dashboard/DashboardModals";
import { useFetch } from "@/hooks/useFetch";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useAISummaryStore } from "@/store/aiSummary";
import { formatCurrency, formatCurrencyAbbrev, formatPct, toNumber } from "@/utils/format";
import { Banknote, Hammer, Percent, Wallet } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

/** Map the toolbar filters to /dashboard query params (Phase 0 backend). */
function filtersToParams(f: DashboardFilters): Record<string, string> {
  const params: Record<string, string> = {};
  if (f.rag.length) params.rag = f.rag.join(",");
  if (f.range !== "all") {
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth();
    const from = f.range === "this_month" ? new Date(y, m, 1) : f.range === "last_3_months" ? new Date(y, m - 2, 1) : new Date(y, 0, 1);
    const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    params.date_from = iso(from);
    params.date_to = iso(now);
  }
  return params;
}

interface DashboardData {
  kpis: {
    active_project_count: number;
    total_contract_value_try: string;
    weighted_avg_margin_pct: string;
    overdue_payment_count: number;
    cost_to_complete_try: string;
    variations_net_try: string;
  };
  projects: any[];
  cashflow_chart: { month: string; out: string; in: string; net_cumulative: string }[];
  kpi_trends?: Record<string, { series: number[]; delta_pct: number | null }>;
  exec_kpis?: { backlog_try: string; projected_profit_try: string; total_receivables_try: string; net_cash_position_try: string };
  portfolio_budget?: { contract_try: string; revised_budget_try: string; committed_try: string; actual_try: string; forecast_final_cost_try: string };
  portfolio_performance?: { project: string; contract_try: string; actual_try: string; forecast_final_try: string }[];
  budget_breakdown?: { total_try: string; items: BudgetBreakdownItem[] };
  ar_aging?: { not_due_try: string; d1_30_try: string; d31_60_try: string; d60_plus_try: string; total_outstanding_try: string; dso_days: number | null };
  cash_forecast?: { starting_cash_try: string; months: { month: string; inflow_try: string; outflow_try: string; net_try: string; cumulative_try: string }[]; min_cash_try: string; min_cash_month: string | null; shortfall: boolean };
  margin_fade?: { has_targets: boolean; weighted_target_pct: string; weighted_current_pct: string; projects: { name: string; target_pct: string; current_pct: string }[] };
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const firstName = useAuth((s) => s.user?.full_name?.split(" ")[0]);
  const isDirector = useAuth((s) => s.user?.role === "director");
  // Toolbar filters are threaded into the /dashboard query so the KPIs, charts
  // and tables re-query when they change.
  const [filters, setFilters] = useState<DashboardFilters>(DEFAULT_FILTERS);
  const dashboardParams = useMemo(() => filtersToParams(filters), [filters]);
  const { data, loading, refetch } = useFetch<DashboardData>("/dashboard", dashboardParams);
  const [briefing, setBriefing] = useState<BriefingItem[]>([]);
  const [briefingState, setBriefingState] = useState<"loading" | "ready" | "error">("loading");
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [overdueOpen, setOverdueOpen] = useState(false);
  const [marginOpen, setMarginOpen] = useState(false);
  const [kpiDetail, setKpiDetail] = useState<KpiInfo | null>(null);
  const { getSummary, setSummary, clearSummary } = useAISummaryStore();
  const CACHE_KEY = "dashboard-summary";

  // CR-005-G: fetch the briefing and cache it (per-page) so navigating away and
  // back does not re-trigger the AI call.
  const fetchBriefing = () => {
    setBriefingState("loading");
    apiGet("/ai/daily-briefing")
      .then((r) => {
        setBriefing(r.data);
        setBriefingState("ready");
        setSummary(CACHE_KEY, JSON.stringify(r.data));
        setGeneratedAt(getSummary(CACHE_KEY)?.generatedAt ?? new Date().toISOString());
      })
      .catch(() => {
        setBriefing([]);
        setBriefingState("error");
      });
  };

  useEffect(() => {
    const cached = getSummary(CACHE_KEY);
    if (cached) {
      // Cache hit — show stored briefing, skip the API call.
      try {
        setBriefing(JSON.parse(cached.content));
      } catch {
        setBriefing([]);
      }
      setGeneratedAt(cached.generatedAt);
      setBriefingState("ready");
      return;
    }
    fetchBriefing();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRefreshBriefing = () => {
    clearSummary(CACHE_KEY);
    fetchBriefing();
  };

  const k = data?.kpis;
  const marginNum = toNumber(k?.weighted_avg_margin_pct);
  // True percentage-points change for margin (points, not relative %).
  const marginSeries = data?.kpi_trends?.weighted_avg_margin_pct?.series;
  const marginPP = marginSeries && marginSeries.length >= 2 ? marginSeries[marginSeries.length - 1] - marginSeries[0] : null;

  const chartData = (data?.cashflow_chart ?? []).map((c) => ({
    month: c.month,
    out: toNumber(c.out),
    in: toNumber(c.in),
    cumulative: toNumber(c.net_cumulative),
  }));

  const pb = data?.portfolio_budget;
  const budgetChartData = pb
    ? [
        { name: "Sözleşme", value: toNumber(pb.contract_try), fill: "#059669" },
        { name: "Revize Bütçe", value: toNumber(pb.revised_budget_try), fill: "#2563EB" },
        { name: "Taahhüt", value: toNumber(pb.committed_try), fill: "#3B82F6" },
        { name: "Harcanan", value: toNumber(pb.actual_try), fill: "#1E40AF" },
        { name: "Tahmini Final", value: toNumber(pb.forecast_final_cost_try), fill: "#D97706" },
      ]
    : [];

  // Compact comparison shown next to Portföy Performansı (replaces the KPI card).
  const finalCostChartData = pb
    ? [
        { name: "Sözleşme", value: toNumber(pb.contract_try), fill: "#059669" },
        { name: "Gerçekleşen", value: toNumber(pb.actual_try), fill: "#2563EB" },
        { name: "Tahmini Final", value: toNumber(pb.forecast_final_cost_try), fill: "#D97706" },
      ]
    : [];

  const performanceData = (data?.portfolio_performance ?? []).map((p) => ({
    project: p.project,
    contract: toNumber(p.contract_try),
    actual: toNumber(p.actual_try),
    forecast: toNumber(p.forecast_final_try),
  }));

  const ar = data?.ar_aging;
  const arTotal = toNumber(ar?.total_outstanding_try);
  const arSeg = (v?: string) => (arTotal > 0 ? (toNumber(v) / arTotal) * 100 : 0);
  const dso = ar?.dso_days ?? null;
  const dsoColor = dso == null ? "text-text-secondary" : dso <= 40 ? "text-success" : dso <= 60 ? "text-warning" : "text-danger";
  const dsoLabel = dso == null ? "Bekleyen tahsilat yok" : dso <= 40 ? "Sağlıklı" : dso <= 60 ? "İzlenmeli" : "Yüksek — tahsilat yavaş";
  const arBuckets = [
    { label: "Vadesi Gelmemiş", v: ar?.not_due_try, color: "#2563EB" },
    { label: "1–30 gün gecikmiş", v: ar?.d1_30_try, color: "#F59E0B" },
    { label: "31–60 gün gecikmiş", v: ar?.d31_60_try, color: "#EA580C" },
    { label: "60+ gün gecikmiş", v: ar?.d60_plus_try, color: "#EF4444" },
  ];

  const mf = data?.margin_fade;
  const fc = data?.cash_forecast;
  const forecastChartData = (fc?.months ?? []).map((mo) => ({
    month: mo.month,
    in: toNumber(mo.inflow_try),
    out: toNumber(mo.outflow_try),
    cumulative: toNumber(mo.cumulative_try),
  }));

  const overdueCount = k?.overdue_payment_count ?? 0;

  return (
    <div>
      <DashboardToolbar
        firstName={firstName}
        filters={filters}
        onChange={setFilters}
        overdueCount={overdueCount}
        onOverdueClick={() => setOverdueOpen(true)}
        onAddDocument={() => navigate("/document-capture")}
        briefing={briefing}
        briefingState={briefingState}
        onRefreshBriefing={handleRefreshBriefing}
      />

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1">
      {/* --- KPI strip: hero row (4) --- */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPICard
          loading={loading}
          label="Gelir (Sözleşme Toplamı)"
          value={formatCurrencyAbbrev(k?.total_contract_value_try)}
          valueTitle={formatCurrency(k?.total_contract_value_try)}
          icon={Wallet}
          accentColor="#2563EB"
          series={data?.kpi_trends?.total_contract_value_try?.series}
          delta={data?.kpi_trends?.total_contract_value_try?.delta_pct}
          onClick={() =>
            setKpiDetail({
              title: "Gelir (Sözleşme Toplamı)",
              value: formatCurrency(k?.total_contract_value_try),
              description: "Tüm aktif projelerin sözleşme bedellerinin toplamı. Portföyün toplam gelir potansiyelini gösterir.",
              series: data?.kpi_trends?.total_contract_value_try?.series,
              delta: data?.kpi_trends?.total_contract_value_try?.delta_pct,
              accentColor: "#2563EB",
              action: { label: "Projeleri gör", onClick: () => navigate("/projects") },
            })
          }
        />
        <KPICard
          loading={loading}
          label="Tamamlanma Maliyeti"
          value={formatCurrencyAbbrev(k?.cost_to_complete_try)}
          valueTitle={formatCurrency(k?.cost_to_complete_try)}
          icon={Hammer}
          accentColor="#F59E0B"
          series={data?.kpi_trends?.cost_to_complete_try?.series}
          delta={data?.kpi_trends?.cost_to_complete_try?.delta_pct}
          onClick={() =>
            setKpiDetail({
              title: "Tamamlanma Maliyeti",
              value: formatCurrency(k?.cost_to_complete_try),
              description: "Tahmini final maliyet ile bugüne kadar gerçekleşen maliyet arasındaki fark — işi tamamlamak için kalan tahmini maliyet.",
              series: data?.kpi_trends?.cost_to_complete_try?.series,
              delta: data?.kpi_trends?.cost_to_complete_try?.delta_pct,
              accentColor: "#F59E0B",
            })
          }
        />
        <KPICard
          loading={loading}
          label="Brüt Kar Marjı"
          value={formatPct(k?.weighted_avg_margin_pct)}
          icon={Percent}
          accentColor="#059669"
          series={marginSeries}
          delta={marginPP}
          deltaUnit="pp"
          alert={marginNum < 5 ? "red" : marginNum < 10 ? "amber" : null}
          onClick={() =>
            setKpiDetail({
              title: "Brüt Kar Marjı",
              value: formatPct(k?.weighted_avg_margin_pct),
              description: "Aktif projelerin sözleşme bedeline göre ağırlıklı ortalama (tahmini) kar marjı.",
              series: marginSeries,
              delta: marginPP,
              deltaUnit: "pp",
              valueKind: "percent",
              accentColor: "#059669",
              action: { label: "Düşük marjlı projeler", onClick: () => setMarginOpen(true) },
            })
          }
        />
        <KPICard
          loading={loading}
          label="Nakit Pozisyonu"
          value={formatCurrencyAbbrev(data?.exec_kpis?.net_cash_position_try)}
          valueTitle={formatCurrency(data?.exec_kpis?.net_cash_position_try)}
          icon={Banknote}
          accentColor="#0E1525"
          series={data?.kpi_trends?.net_cash_position_try?.series}
          delta={data?.kpi_trends?.net_cash_position_try?.delta_pct}
          alert={toNumber(data?.exec_kpis?.net_cash_position_try) < 0 ? "red" : null}
          onClick={() =>
            setKpiDetail({
              title: "Nakit Pozisyonu",
              value: formatCurrency(data?.exec_kpis?.net_cash_position_try),
              description: "Tüm aktif projelerin net nakit pozisyonu — tahsil edilen tutarlar eksi yapılan ödemeler.",
              series: data?.kpi_trends?.net_cash_position_try?.series,
              delta: data?.kpi_trends?.net_cash_position_try?.delta_pct,
              accentColor: "#0E1525",
            })
          }
        />
      </div>

      <OverduePaymentsModal
        open={overdueOpen}
        onClose={() => setOverdueOpen(false)}
        onChanged={refetch}
        onGoToReminders={() => navigate("/reminders")}
      />
      <LowMarginModal open={marginOpen} onClose={() => setMarginOpen(false)} projects={data?.projects ?? []} onSelect={(id) => { setMarginOpen(false); navigate(`/projects/${id}/dashboard`); }} />
      <KpiDetailModal open={!!kpiDetail} onClose={() => setKpiDetail(null)} kpi={kpiDetail} />

      {/* --- Hero: portfolio performance + tahmini final maliyet graph --- */}
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3 xl:items-stretch">
        <DashboardSection
          className="xl:col-span-2"
          title="Portföy Performansı (Gerçekleşen vs Tahmin)"
          subtitle="Proje bazında gerçekleşen maliyet, tahmini final maliyet ve sözleşme bedeli."
        >
          <div className="px-4 pb-4">
            <PortfolioPerformanceChart data={performanceData} height={200} />
          </div>
        </DashboardSection>

        <DashboardSection
          title="Tahmini Final Maliyet"
          subtitle="Sözleşme bedeli, gerçekleşen ve tahmini final maliyet."
        >
          <div className="px-4 pb-4">
            <MetricLineChart data={finalCostChartData} height={200} />
          </div>
        </DashboardSection>
      </div>

      {/* --- Incoming documents + pending approvals (director) --- */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-stretch">
        <DashboardSection
          className={isDirector ? "lg:col-span-2" : "lg:col-span-3"}
          title={
            <span className="inline-flex items-center gap-3">
              Gelen Belgeler
              <button onClick={() => navigate("/document-capture")} className="rounded-md border border-border px-2 py-0.5 text-xs font-medium text-brand hover:border-brand">
                Belge Yükle →
              </button>
            </span>
          }
          subtitle="Son eklenen faturalar, hakedişler ve ek işler."
        >
          <IncomingWorkflowCard />
        </DashboardSection>

        {isDirector && (
          <DashboardSection
            title="Onay Bekleyenler"
            subtitle={<span className="block truncate">Onayınızı bekleyen işlemler.</span>}
            right={
              <button onClick={() => navigate("/approvals")} className="text-sm font-medium text-brand hover:underline">
                Tüm onaylar →
              </button>
            }
          >
            <ApprovalsPanel onGoToApprovals={() => navigate("/approvals")} />
          </DashboardSection>
        )}
      </div>

      {/* --- Portfolio budget totals + AR aging --- */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
        <DashboardSection
          title="Portföy Bütçe & Tahmin"
          subtitle="Tüm aktif projelerin toplamı — sözleşme, revize bütçe, taahhüt, harcanan ve tahmini final maliyet."
        >
          <div className="px-4 pb-4">
            <PortfolioBudgetChart data={budgetChartData} height={300} />
          </div>
        </DashboardSection>

        <DashboardSection
          title="Alacak Yaşlandırması"
          subtitle="Bekleyen alacakların vade yaşına göre dağılımı ve ortalama tahsilat süresi (DSO)."
        >
          <div className="px-4 pb-4">
              <div className="flex items-end justify-between">
                <div>
                  <div className="text-xs text-text-secondary">Ortalama Tahsilat Süresi (DSO)</div>
                  <div className={`tabular mt-1 text-3xl font-bold ${dsoColor}`}>{dso == null ? "—" : `${dso} gün`}</div>
                  <div className={`mt-0.5 text-xs ${dsoColor}`}>{dsoLabel}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-text-secondary">Toplam Ticari Alacak</div>
                  <div className="tabular text-lg font-semibold text-primary">{formatCurrency(ar?.total_outstanding_try)}</div>
                </div>
              </div>
              <div className="mt-4 flex h-3 w-full overflow-hidden rounded-full bg-bg">
                {arBuckets.map((bk, i) => (
                  <div key={i} style={{ width: `${arSeg(bk.v)}%`, backgroundColor: bk.color }} title={bk.label} />
                ))}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3">
                {arBuckets.map((bk, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-xs text-text-secondary">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: bk.color }} />
                      {bk.label}
                    </span>
                    <span className="tabular text-sm font-medium text-text-primary">{formatCurrency(bk.v)}</span>
                  </div>
                ))}
              </div>
          </div>
        </DashboardSection>
      </div>

      {/* --- Forward cash-flow projection (conditional) --- */}
      {forecastChartData.length > 0 && (
        <DashboardSection
          className="mt-4"
          title="Nakit Akış Projeksiyonu (Önümüzdeki 6 Ay)"
          right={fc?.shortfall ? <span className="rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-danger">Nakit açığı riski</span> : undefined}
          subtitle={
            <>
              Bekleyen faturalardan beklenen tahsilatlar ile vadesi gelen ödemelerin projeksiyonu. En düşük öngörülen nakit:{" "}
              <span className={fc?.shortfall ? "font-semibold text-danger" : "font-semibold text-text-primary"}>{formatCurrency(fc?.min_cash_try)}</span>
              {fc?.min_cash_month ? ` (${fc.min_cash_month})` : ""}.
            </>
          }
        >
          <div className="px-4 pb-4">
            <CashFlowChart data={forecastChartData} />
          </div>
        </DashboardSection>
      )}

      {/* --- Combined historical cash flow --- */}
      <DashboardSection className="mt-4" title="Birleşik Nakit Akışı (Son 6 Ay)">
        <div className="px-4 pb-4">
          <CashFlowChart data={chartData} />
        </div>
      </DashboardSection>

      {/* --- Margin fade (conditional) --- */}
      {mf?.has_targets && (
        <DashboardSection
          className="mt-4"
          title="Kar Marjı Erozyonu"
          subtitle={
            <>
              Hedeflenen kar marjına karşı güncel (tahmini) marj. Portföy: Hedef{" "}
              <span className="font-semibold text-text-primary">{formatPct(mf.weighted_target_pct)}</span> · Güncel{" "}
              <span className="font-semibold text-text-primary">{formatPct(mf.weighted_current_pct)}</span>.
            </>
          }
        >
          <div className="px-4 pb-4">
              {mf.projects.map((pr, i) => {
                const diff = toNumber(pr.current_pct) - toNumber(pr.target_pct);
                const chip = diff >= 0 ? "bg-green-50 text-success" : "bg-red-50 text-danger";
                return (
                  <div key={i} className="flex items-center justify-between gap-3 border-b border-border py-2.5 last:border-0">
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-text-primary" title={pr.name}>{pr.name}</span>
                    <div className="flex shrink-0 items-center gap-4 text-sm">
                      <span className="tabular text-text-secondary">Hedef <span className="font-medium text-text-primary">{formatPct(pr.target_pct)}</span></span>
                      <span className="tabular text-text-secondary">Güncel <span className="font-medium text-text-primary">{formatPct(pr.current_pct)}</span></span>
                      <span className={`tabular rounded-full px-2 py-0.5 text-xs font-medium ${chip}`}>{diff >= 0 ? "+" : ""}{diff.toFixed(1)} puan</span>
                    </div>
                  </div>
                );
              })}
          </div>
        </DashboardSection>
      )}
        </div>

        <YapiAIRail onGoToTasks={() => navigate("/reminders")} />
      </div>
    </div>
  );
}
