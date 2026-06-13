import { CashFlowChart, PortfolioBudgetChart, PortfolioPerformanceChart } from "@/components/charts";
import { Card, CardBody } from "@/components/ui";
import { KPICard } from "@/components/KPICard";
import { BudgetBreakdownCard, type BudgetBreakdownItem } from "@/components/dashboard/BudgetBreakdownCard";
import { DashboardSection } from "@/components/dashboard/DashboardSection";
import { DashboardToolbar, DEFAULT_FILTERS, type DashboardFilters } from "@/components/dashboard/DashboardToolbar";
import { YapiAIRail } from "@/components/dashboard/YapiAIRail";
import { IncomingWorkflowCard } from "@/components/dashboard/IncomingWorkflowCard";
import { ApprovalsPanel } from "@/components/dashboard/ApprovalsPanel";
import { type BriefingItem } from "@/components/dashboard/InsightItem";
import { OverduePaymentsModal, LowMarginModal } from "@/components/dashboard/DashboardModals";
import { RAGIndicator } from "@/components/RAGIndicator";
import { DataTable, type Column } from "@/components/DataTable";
import { useFetch } from "@/hooks/useFetch";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useAISummaryStore } from "@/store/aiSummary";
import { formatCurrency, formatCurrencyAbbrev, formatPct, toNumber } from "@/utils/format";
import { AlarmClock, Hammer, PlusSquare, Target, TrendingUp, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

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
  // Phase 1: toolbar filter state (threaded into the data fetch in Phase 6).
  const [filters, setFilters] = useState<DashboardFilters>(DEFAULT_FILTERS);
  const { data, loading, refetch, error } = useFetch<DashboardData>("/dashboard");
  const [briefing, setBriefing] = useState<BriefingItem[]>([]);
  const [briefingState, setBriefingState] = useState<"loading" | "ready" | "error">("loading");
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [overdueOpen, setOverdueOpen] = useState(false);
  const [marginOpen, setMarginOpen] = useState(false);
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

  // Proje Performans Sıralaması — compact margin-ranked list (rank baked in).
  const rankedProjects = [...(data?.projects ?? [])]
    .sort((a, b) => toNumber(b.margin_pct) - toNumber(a.margin_pct))
    .map((r, i) => ({ ...r, _rank: i + 1 }));

  const RISK_MAP: Record<string, { l: string; c: string }> = {
    green: { l: "Düşük", c: "bg-green-50 text-success" },
    amber: { l: "Orta", c: "bg-amber-50 text-warning" },
    red: { l: "Yüksek", c: "bg-red-50 text-danger" },
  };

  const columns: Column<any>[] = [
    { key: "_rank", header: "#", maxWidth: 44, render: (r) => <span className="tabular text-text-secondary">{r._rank}</span> },
    {
      key: "name",
      header: "Proje",
      sortable: true,
      maxWidth: 220,
      render: (r) => (
        <span className="flex items-center gap-2 truncate font-medium text-primary" title={r.name}>
          <RAGIndicator status={r.rag_status} reason={r.rag_label_tr} /> <span className="truncate">{r.name}</span>
        </span>
      ),
    },
    {
      key: "margin_pct",
      header: "Marj % (Tahmini)",
      align: "right",
      sortable: true,
      sortValue: (r) => toNumber(r.margin_pct),
      render: (r) => {
        const m = toNumber(r.margin_pct);
        const color = m < 5 ? "text-danger" : m < 10 ? "text-accent" : "text-success";
        return <span className={`font-semibold ${color}`}>{formatPct(r.margin_pct)}</span>;
      },
    },
    {
      key: "margin_try",
      header: "Marj ₺ (Tahmini)",
      align: "right",
      sortValue: (r) => toNumber(r.margin_try),
      render: (r) => <span className={toNumber(r.margin_try) < 0 ? "text-danger" : ""}>{formatCurrency(r.margin_try)}</span>,
    },
    {
      key: "rag_status",
      header: "Risk",
      render: (r) => {
        const x = RISK_MAP[r.rag_status] ?? { l: r.rag_label_tr, c: "bg-bg text-text-secondary" };
        return <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${x.c}`}>{x.l}</span>;
      },
    },
  ];

  const chartData = (data?.cashflow_chart ?? []).map((c) => ({
    month: c.month,
    out: toNumber(c.out),
    in: toNumber(c.in),
    cumulative: toNumber(c.net_cumulative),
  }));

  const pb = data?.portfolio_budget;
  const bb = data?.budget_breakdown;
  const budgetChartData = pb
    ? [
        { name: "Sözleşme", value: toNumber(pb.contract_try), fill: "#059669" },
        { name: "Revize Bütçe", value: toNumber(pb.revised_budget_try), fill: "#2563EB" },
        { name: "Taahhüt", value: toNumber(pb.committed_try), fill: "#3B82F6" },
        { name: "Harcanan", value: toNumber(pb.actual_try), fill: "#1E40AF" },
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
      <DashboardToolbar firstName={firstName} filters={filters} onChange={setFilters} />

      <div className="flex flex-col gap-6 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1">
      {overdueCount > 0 && (
        <button
          onClick={() => setOverdueOpen(true)}
          className="mb-5 flex w-full items-center gap-2 rounded-xl border-l-4 border-danger bg-red-50 px-4 py-2.5 text-left text-sm font-medium text-danger transition-colors hover:brightness-95"
        >
          <AlarmClock className="h-4 w-4 shrink-0" />
          {overdueCount} vadesi geçmiş ödeme — görüntüle →
        </button>
      )}

      {/* --- KPI strip: hero row (5) --- */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
        <KPICard
          loading={loading}
          label="Gelir (Sözleşme Toplamı)"
          value={formatCurrencyAbbrev(k?.total_contract_value_try)}
          valueTitle={formatCurrency(k?.total_contract_value_try)}
          icon={Wallet}
          series={data?.kpi_trends?.total_contract_value_try?.series}
          delta={data?.kpi_trends?.total_contract_value_try?.delta_pct}
        />
        <KPICard
          loading={loading}
          label="Tamamlanma Maliyeti"
          value={formatCurrencyAbbrev(k?.cost_to_complete_try)}
          valueTitle={formatCurrency(k?.cost_to_complete_try)}
          icon={Hammer}
          series={data?.kpi_trends?.cost_to_complete_try?.series}
          delta={data?.kpi_trends?.cost_to_complete_try?.delta_pct}
        />
        <KPICard
          loading={loading}
          label="Tahmini Final Maliyet"
          value={formatCurrencyAbbrev(pb?.forecast_final_cost_try)}
          valueTitle={formatCurrency(pb?.forecast_final_cost_try)}
          icon={Target}
        />
        <KPICard
          loading={loading}
          label="Brüt Kar Marjı"
          value={formatPct(k?.weighted_avg_margin_pct)}
          icon={TrendingUp}
          series={marginSeries}
          delta={marginPP}
          deltaUnit="pp"
          alert={marginNum < 5 ? "red" : marginNum < 10 ? "amber" : null}
          onClick={() => setMarginOpen(true)}
        />
        <KPICard
          loading={loading}
          label="Ek İşler (Net)"
          value={formatCurrencyAbbrev(k?.variations_net_try)}
          valueTitle={formatCurrency(k?.variations_net_try)}
          icon={PlusSquare}
          series={data?.kpi_trends?.variations_net_try?.series}
          delta={data?.kpi_trends?.variations_net_try?.delta_pct}
        />
      </div>

      <OverduePaymentsModal
        open={overdueOpen}
        onClose={() => setOverdueOpen(false)}
        onChanged={refetch}
        onGoToReminders={() => navigate("/reminders")}
      />
      <LowMarginModal open={marginOpen} onClose={() => setMarginOpen(false)} projects={data?.projects ?? []} onSelect={(id) => { setMarginOpen(false); navigate(`/projects/${id}/dashboard`); }} />

      {/* --- Hero: portfolio performance + budget breakdown by category --- */}
      <div className="mt-8 grid grid-cols-1 gap-6 xl:grid-cols-3 xl:items-start">
        <DashboardSection
          className="xl:col-span-2"
          title="Portföy Performansı (Gerçekleşen vs Tahmin)"
          subtitle="Proje bazında gerçekleşen maliyet, tahmini final maliyet ve sözleşme bedeli."
        >
          <Card>
            <CardBody>
              <PortfolioPerformanceChart data={performanceData} height={340} />
            </CardBody>
          </Card>
        </DashboardSection>

        <DashboardSection
          title="Bütçe Dağılımı — Maliyet Kategorisi"
          info="Aktif projelerde girilmiş bütçe kalemlerinin (orijinal + onaylı ek işler) maliyet kategorisine göre toplamıdır. Kategori bazında bütçe girilmemiş projeler dahil olmadığından, “Revize Bütçe” toplamından düşük olabilir."
          subtitle="Girilmiş bütçe kalemlerinin kategori bazında toplamı."
        >
          <BudgetBreakdownCard items={bb?.items ?? []} total={bb?.total_try ?? "0"} loading={loading} />
        </DashboardSection>
      </div>

      {/* --- Project performance ranking (full width; AI moved to the rail) --- */}
      <DashboardSection
        className="mt-8"
        title="Proje Performans Sıralaması"
        subtitle="Tahmini kar marjına göre sıralı aktif projeler."
        right={
          <button onClick={() => navigate("/projects")} className="text-sm font-medium text-brand hover:underline">
            Tüm projeler →
          </button>
        }
      >
        <DataTable
          columns={columns}
          rows={rankedProjects}
          loading={loading}
          error={error}
          onRetry={refetch}
          minWidth={560}
          emptyMessage="Henüz proje yok. İlk projenizi oluşturun."
          emptyAction={{ label: "Yeni Proje", onClick: () => navigate("/projects/new") }}
          onRowClick={(r) => navigate(`/projects/${r.id}/dashboard`)}
        />
      </DashboardSection>

      {/* --- Incoming documents + pending approvals (director) --- */}
      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3 lg:items-start">
        <DashboardSection
          className={isDirector ? "lg:col-span-2" : "lg:col-span-3"}
          title="Gelen Belgeler"
          subtitle="Son eklenen faturalar, hakedişler ve ek işler."
          right={
            <button onClick={() => navigate("/document-capture")} className="text-sm font-medium text-brand hover:underline">
              Belge Yükle →
            </button>
          }
        >
          <IncomingWorkflowCard />
        </DashboardSection>

        {isDirector && (
          <DashboardSection title="Onay Bekleyenler" subtitle="Onayınızı bekleyen işlemler.">
            <ApprovalsPanel onGoToApprovals={() => navigate("/approvals")} />
          </DashboardSection>
        )}
      </div>

      {/* --- Portfolio budget totals + AR aging --- */}
      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2 lg:items-start">
        <DashboardSection
          title="Portföy Bütçe & Tahmin"
          subtitle="Tüm aktif projelerin toplamı — sözleşme, revize bütçe, taahhüt, harcanan ve tahmini final maliyet."
        >
          <Card>
            <CardBody>
              <PortfolioBudgetChart data={budgetChartData} height={300} />
            </CardBody>
          </Card>
        </DashboardSection>

        <DashboardSection
          title="Alacak Yaşlandırması"
          subtitle="Bekleyen alacakların vade yaşına göre dağılımı ve ortalama tahsilat süresi (DSO)."
        >
          <Card>
            <CardBody>
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
            </CardBody>
          </Card>
        </DashboardSection>
      </div>

      {/* --- Forward cash-flow projection (conditional) --- */}
      {forecastChartData.length > 0 && (
        <DashboardSection
          className="mt-8"
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
          <Card>
            <CardBody>
              <CashFlowChart data={forecastChartData} />
            </CardBody>
          </Card>
        </DashboardSection>
      )}

      {/* --- Combined historical cash flow --- */}
      <DashboardSection className="mt-8" title="Birleşik Nakit Akışı (Son 6 Ay)">
        <Card>
          <CardBody>
            <CashFlowChart data={chartData} />
          </CardBody>
        </Card>
      </DashboardSection>

      {/* --- Margin fade (conditional) --- */}
      {mf?.has_targets && (
        <DashboardSection
          className="mt-8"
          title="Kar Marjı Erozyonu"
          subtitle={
            <>
              Hedeflenen kar marjına karşı güncel (tahmini) marj. Portföy: Hedef{" "}
              <span className="font-semibold text-text-primary">{formatPct(mf.weighted_target_pct)}</span> · Güncel{" "}
              <span className="font-semibold text-text-primary">{formatPct(mf.weighted_current_pct)}</span>.
            </>
          }
        >
          <Card>
            <CardBody>
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
            </CardBody>
          </Card>
        </DashboardSection>
      )}
        </div>

        <YapiAIRail
          briefing={briefing}
          briefingState={briefingState}
          generatedAt={generatedAt}
          onRefresh={handleRefreshBriefing}
          onGoToTasks={() => navigate("/reminders")}
        />
      </div>
    </div>
  );
}
