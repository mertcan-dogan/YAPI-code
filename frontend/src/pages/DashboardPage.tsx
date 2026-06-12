import { CashFlowChart, PortfolioBudgetChart } from "@/components/charts";
import { AIDisclaimer, Button, Card, CardBody } from "@/components/ui";
import { KPICard } from "@/components/KPICard";
import { OverduePaymentsModal, LowMarginModal } from "@/components/dashboard/DashboardModals";
import { PageHeader } from "@/components/layout/AppLayout";
import { RAGIndicator } from "@/components/RAGIndicator";
import { DataTable, type Column } from "@/components/DataTable";
import { useFetch } from "@/hooks/useFetch";
import { apiGet, apiPut } from "@/lib/api";
import { useAISummaryStore } from "@/store/aiSummary";
import { formatCurrency, formatCurrencyAbbrev, formatDate, formatDateTime, formatPct, toNumber } from "@/utils/format";
import { AlarmClock, AlertTriangle, Banknote, Building2, CheckCircle2, GripVertical, Info, Layers, PiggyBank, Plus, RefreshCw, SlidersHorizontal, Sparkles, TrendingUp, Wallet, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import { Responsive, WidthProvider } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const ResponsiveGrid = WidthProvider(Responsive);

const WIDGETS: { id: string; label: string }[] = [
  { id: "ai_summary", label: "AI Özeti" },
  { id: "kpis_primary", label: "Ana Göstergeler (KPI)" },
  { id: "kpis_exec", label: "Yönetici Göstergeleri" },
  { id: "projects_briefing", label: "Proje Durumu & Öneriler" },
  { id: "portfolio_budget", label: "Portföy Bütçe & Tahmin" },
  { id: "cash_forecast", label: "Nakit Akış Projeksiyonu" },
  { id: "cashflow_ar", label: "Nakit Akışı & Alacak Yaşlandırması" },
  { id: "margin_fade", label: "Kar Marjı Erozyonu" },
];

// 12-col grid defaults per widget (rowHeight 30 + 16px margin).
const WIDGET_DEFAULTS: Record<string, { w: number; h: number; minW: number; minH: number }> = {
  ai_summary: { w: 12, h: 3, minW: 6, minH: 2 },
  kpis_primary: { w: 12, h: 4, minW: 6, minH: 3 },
  kpis_exec: { w: 12, h: 4, minW: 6, minH: 3 },
  projects_briefing: { w: 12, h: 13, minW: 6, minH: 6 },
  portfolio_budget: { w: 6, h: 10, minW: 4, minH: 6 },
  cash_forecast: { w: 6, h: 10, minW: 4, minH: 6 },
  cashflow_ar: { w: 12, h: 12, minW: 6, minH: 6 },
  margin_fade: { w: 6, h: 7, minW: 4, minH: 4 },
};

type GridItem = { i: string; x: number; y: number; w: number; h: number; minW?: number; minH?: number };

const DEFAULT_GRID: GridItem[] = [
  { i: "ai_summary", x: 0, y: 0, w: 12, h: 3 },
  { i: "kpis_primary", x: 0, y: 3, w: 12, h: 4 },
  { i: "kpis_exec", x: 0, y: 7, w: 12, h: 4 },
  { i: "projects_briefing", x: 0, y: 11, w: 12, h: 13 },
  { i: "portfolio_budget", x: 0, y: 24, w: 6, h: 10 },
  { i: "cash_forecast", x: 6, y: 24, w: 6, h: 10 },
  { i: "cashflow_ar", x: 0, y: 34, w: 12, h: 12 },
  { i: "margin_fade", x: 0, y: 46, w: 6, h: 7 },
].map((g) => ({ ...g, minW: WIDGET_DEFAULTS[g.i].minW, minH: WIDGET_DEFAULTS[g.i].minH }));

// Reconstruct the grid from saved JSON (handles new {grid:[]} and legacy [{id,visible}]).
function buildGrid(saved: any): GridItem[] {
  const valid = new Set(WIDGETS.map((w) => w.id));
  let items: GridItem[] | null = null;
  if (saved && Array.isArray(saved.grid)) {
    items = saved.grid
      .filter((g: any) => g && valid.has(g.i))
      .map((g: any) => ({
        i: g.i,
        x: g.x ?? 0,
        y: g.y ?? 0,
        w: g.w ?? WIDGET_DEFAULTS[g.i].w,
        h: g.h ?? WIDGET_DEFAULTS[g.i].h,
        minW: WIDGET_DEFAULTS[g.i].minW,
        minH: WIDGET_DEFAULTS[g.i].minH,
      }));
  } else if (Array.isArray(saved)) {
    const vis = saved.filter((it: any) => it && it.visible !== false && valid.has(it.id)).map((it: any) => it.id);
    const set = new Set(vis);
    items = DEFAULT_GRID.filter((g) => (set.size === 0 ? true : set.has(g.i))).map((g) => ({ ...g }));
  }
  if (!items || items.length === 0) items = DEFAULT_GRID.map((g) => ({ ...g }));
  return items;
}

interface DashboardData {
  kpis: {
    active_project_count: number;
    total_contract_value_try: string;
    weighted_avg_margin_pct: string;
    overdue_payment_count: number;
  };
  projects: any[];
  cashflow_chart: { month: string; out: string; in: string; net_cumulative: string }[];
  kpi_trends?: Record<string, { series: number[]; delta_pct: number | null }>;
  exec_kpis?: { backlog_try: string; projected_profit_try: string; total_receivables_try: string; net_cash_position_try: string };
  portfolio_budget?: { contract_try: string; revised_budget_try: string; committed_try: string; actual_try: string; forecast_final_cost_try: string };
  ar_aging?: { not_due_try: string; d1_30_try: string; d31_60_try: string; d60_plus_try: string; total_outstanding_try: string; dso_days: number | null };
  cash_forecast?: { starting_cash_try: string; months: { month: string; inflow_try: string; outflow_try: string; net_try: string; cumulative_try: string }[]; min_cash_try: string; min_cash_month: string | null; shortfall: boolean };
  margin_fade?: { has_targets: boolean; weighted_target_pct: string; weighted_current_pct: string; projects: { name: string; target_pct: string; current_pct: string }[] };
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { data, loading, refetch, error } = useFetch<DashboardData>("/dashboard");
  const [briefing, setBriefing] = useState<any[]>([]);
  const [briefingState, setBriefingState] = useState<"loading" | "ready" | "error">("loading");
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [overdueOpen, setOverdueOpen] = useState(false);
  const [marginOpen, setMarginOpen] = useState(false);
  const { getSummary, setSummary, clearSummary } = useAISummaryStore();
  const CACHE_KEY = "dashboard-summary";

  // Customizable Ana Sayfa — per-user resizable widget grid (saved to account).
  const [grid, setGrid] = useState<GridItem[]>(() => DEFAULT_GRID.map((g) => ({ ...g })));
  const [editMode, setEditMode] = useState(false);
  const [gridSnapshot, setGridSnapshot] = useState<GridItem[]>([]);
  const [savingLayout, setSavingLayout] = useState(false);
  const [bp, setBp] = useState("lg");
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    apiGet<{ layout: any }>("/settings/dashboard-layout")
      .then(({ data }) => setGrid(buildGrid(data?.layout)))
      .catch(() => setGrid(buildGrid(null)));
  }, []);

  const presentIds = new Set(grid.map((g) => g.i));
  const removableWidgets = WIDGETS.filter((w) => !presentIds.has(w.id));

  const startEdit = () => {
    setGridSnapshot(grid.map((g) => ({ ...g })));
    setEditMode(true);
  };
  const cancelEdit = () => {
    setGrid(gridSnapshot);
    setEditMode(false);
    setAddOpen(false);
  };
  const resetDefault = () => setGrid(DEFAULT_GRID.map((g) => ({ ...g })));
  const removeWidget = (id: string) => setGrid((g) => g.filter((it) => it.i !== id));
  const addWidget = (id: string) => {
    const d = WIDGET_DEFAULTS[id];
    setGrid((g) => [...g, { i: id, x: 0, y: Infinity, w: d.w, h: d.h, minW: d.minW, minH: d.minH }]);
    setAddOpen(false);
  };
  const onGridChange = (current: any[]) => {
    if (editMode && bp !== "sm") {
      setGrid(current.map((c: any) => ({ i: c.i, x: c.x, y: c.y, w: c.w, h: c.h, minW: WIDGET_DEFAULTS[c.i]?.minW, minH: WIDGET_DEFAULTS[c.i]?.minH })));
    }
  };
  const saveLayout = async () => {
    setSavingLayout(true);
    try {
      await apiPut("/settings/dashboard-layout", { layout: { grid: grid.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })) } });
      setEditMode(false);
      setAddOpen(false);
      toast.success("Panel düzeni kaydedildi");
    } catch (e: any) {
      toast.error(e.message ?? "Kaydedilemedi");
    } finally {
      setSavingLayout(false);
    }
  };

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

  const columns: Column<any>[] = [
    {
      key: "name",
      header: "Proje Adı",
      sortable: true,
      maxWidth: 220,
      render: (r) => (
        <span className="flex items-center gap-2 truncate font-medium text-primary" title={r.name}>
          <RAGIndicator status={r.rag_status} reason={r.rag_label_tr} /> <span className="truncate">{r.name}</span>
        </span>
      ),
    },
    { key: "client_name", header: "İşveren", maxWidth: 160 },
    { key: "contract_value_try", header: "Sözleşme Değeri", align: "right", render: (r) => formatCurrency(r.contract_value_try), sortValue: (r) => toNumber(r.contract_value_try) },
    {
      key: "spent_pct",
      header: "Harcanan %",
      align: "right",
      render: (r) => (
        <div className="flex items-center justify-end gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-border">
            <div className={`h-full ${toNumber(r.spent_pct) >= 90 ? "bg-danger" : "bg-brand"}`} style={{ width: `${Math.min(toNumber(r.spent_pct), 100)}%` }} />
          </div>
          {formatPct(r.spent_pct)}
        </div>
      ),
    },
    { key: "completion_pct", header: "Tamamlanma %", align: "right", render: (r) => formatPct(r.completion_pct) },
    {
      key: "margin_pct",
      header: "Kar Marjı %",
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
      key: "net_cash_position_try",
      header: "Nakit Durumu",
      align: "right",
      render: (r) => <span className={toNumber(r.net_cash_position_try) < 0 ? "text-danger" : ""}>{formatCurrency(r.net_cash_position_try)}</span>,
    },
    {
      key: "rag_label_tr",
      header: "Durum",
      render: (r) => {
        const map: Record<string, string> = { green: "bg-green-50 text-success", amber: "bg-amber-50 text-warning", red: "bg-red-50 text-danger" };
        return <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${map[r.rag_status] ?? "bg-bg text-text-secondary"}`}>{r.rag_label_tr}</span>;
      },
    },
    {
      key: "planned_end_date",
      header: "Bitiş Tarihi",
      align: "right",
      render: (r) => <span className={r.overdue ? "text-danger" : ""}>{formatDate(r.planned_end_date)}</span>,
    },
  ];

  const chartData = (data?.cashflow_chart ?? []).map((c) => ({
    month: c.month,
    out: toNumber(c.out),
    in: toNumber(c.in),
    cumulative: toNumber(c.net_cumulative),
  }));

  const ex = data?.exec_kpis;
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

  const widgetNodes: Record<string, ReactNode> = {
    ai_summary: <AISummaryStrip k={k} briefing={briefing} navigate={navigate} />,
    kpis_primary: (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KPICard loading={loading} label="Aktif Proje Sayısı" value={String(k?.active_project_count ?? 0)} icon={Building2} series={data?.kpi_trends?.active_project_count?.series} delta={data?.kpi_trends?.active_project_count?.delta_pct} onClick={() => navigate("/projects")} />
        <KPICard loading={loading} label="Toplam Sözleşme Değeri" value={formatCurrencyAbbrev(k?.total_contract_value_try)} valueTitle={formatCurrency(k?.total_contract_value_try)} icon={Wallet} series={data?.kpi_trends?.total_contract_value_try?.series} delta={data?.kpi_trends?.total_contract_value_try?.delta_pct} />
        <KPICard loading={loading} label="Ağırlıklı Ort. Kar Marjı" value={formatPct(k?.weighted_avg_margin_pct)} icon={TrendingUp} series={data?.kpi_trends?.weighted_avg_margin_pct?.series} delta={data?.kpi_trends?.weighted_avg_margin_pct?.delta_pct} alert={marginNum < 5 ? "red" : marginNum < 10 ? "amber" : null} onClick={() => setMarginOpen(true)} />
        <KPICard loading={loading} label="Vadesi Geçmiş Ödemeler" value={String(k?.overdue_payment_count ?? 0)} icon={AlarmClock} series={data?.kpi_trends?.overdue_payment_count?.series} delta={data?.kpi_trends?.overdue_payment_count?.delta_pct} invertDelta alert={(k?.overdue_payment_count ?? 0) > 0 ? "red" : null} onClick={() => setOverdueOpen(true)} />
      </div>
    ),
    kpis_exec: (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KPICard loading={loading} label="İş Bakiyesi (Backlog)" value={formatCurrencyAbbrev(ex?.backlog_try)} valueTitle={formatCurrency(ex?.backlog_try)} icon={Layers} series={data?.kpi_trends?.backlog_try?.series} delta={data?.kpi_trends?.backlog_try?.delta_pct} />
        <KPICard loading={loading} label="Tahmini Tamamlanma Karı" value={formatCurrencyAbbrev(ex?.projected_profit_try)} valueTitle={formatCurrency(ex?.projected_profit_try)} icon={PiggyBank} series={data?.kpi_trends?.projected_profit_try?.series} delta={data?.kpi_trends?.projected_profit_try?.delta_pct} alert={toNumber(ex?.projected_profit_try) < 0 ? "red" : null} />
        <KPICard loading={loading} label="Ticari Alacaklar" value={formatCurrencyAbbrev(ex?.total_receivables_try)} valueTitle={formatCurrency(ex?.total_receivables_try)} icon={Banknote} series={data?.kpi_trends?.total_receivables_try?.series} delta={data?.kpi_trends?.total_receivables_try?.delta_pct} />
        <KPICard loading={loading} label="Net Nakit Pozisyonu" value={formatCurrencyAbbrev(ex?.net_cash_position_try)} valueTitle={formatCurrency(ex?.net_cash_position_try)} icon={Wallet} series={data?.kpi_trends?.net_cash_position_try?.series} delta={data?.kpi_trends?.net_cash_position_try?.delta_pct} alert={toNumber(ex?.net_cash_position_try) < 0 ? "red" : null} />
      </div>
    ),
    projects_briefing: (
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-3 text-lg font-semibold text-primary">Proje Durumu</h2>
          <DataTable columns={columns} rows={data?.projects ?? []} loading={loading} error={error} onRetry={refetch} minWidth={900} emptyMessage="Henüz proje yok. İlk projenizi oluşturun." emptyAction={{ label: "Yeni Proje", onClick: () => navigate("/projects/new") }} onRowClick={(r) => navigate(`/projects/${r.id}/dashboard`)} />
        </div>
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-primary">
              <Sparkles className="h-4 w-4 text-brand" /> Bugün Ne Yapmalısın
            </h2>
            <div className="flex items-center gap-2">
              {generatedAt && <span className="text-[11px] italic text-text-secondary">Son güncelleme: {formatDateTime(generatedAt)}</span>}
              <button onClick={handleRefreshBriefing} disabled={briefingState === "loading"} title="Yenile" className="rounded p-1 text-text-secondary hover:text-primary disabled:opacity-50" aria-label="Yenile">
                <RefreshCw className={`h-3.5 w-3.5 ${briefingState === "loading" ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>
          <Card>
            <CardBody className="space-y-3">
              {briefingState === "loading" && (
                <div className="flex items-center gap-2 rounded-md bg-navy-50 px-3 py-2 text-sm text-brand">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-brand" />
                  Yapay zeka projelerinizi analiz ediyor…
                </div>
              )}
              {briefingState === "error" && (
                <div className="flex items-center gap-2 rounded-md bg-bg px-3 py-2 text-sm text-text-secondary">
                  <Info className="h-4 w-4" /> Yapay zeka şu an kullanılamıyor. Lütfen bekleyin.
                </div>
              )}
              {briefingState === "ready" && briefing.length === 0 && (
                <div className="flex items-center gap-2 rounded-md bg-green-50 px-3 py-2 text-sm text-success">
                  <CheckCircle2 className="h-4 w-4" /> Bugün için öncelikli işlem bulunmuyor.
                </div>
              )}
              {briefing.slice(0, 8).map((item, i) => {
                const sv = sevStyle(item.severity);
                return (
                  <div key={i} className="flex gap-3 border-b border-border pb-3 last:border-0 last:pb-0">
                    <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${sv.bg} ${sv.fg}`}>
                      <sv.Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <span className="block truncate text-xs font-semibold text-text-secondary">{item.project_name}</span>
                      <p className="mt-0.5 text-sm font-medium text-text-primary">{item.issue}</p>
                      <p className="mt-0.5 text-xs text-text-secondary">→ {item.recommended_action}</p>
                    </div>
                  </div>
                );
              })}
              {briefingState === "ready" && <AIDisclaimer />}
            </CardBody>
          </Card>
        </div>
      </div>
    ),
    portfolio_budget: (
      <div>
        <h2 className="mb-1 text-lg font-semibold text-primary">Portföy Bütçe &amp; Tahmin</h2>
        <p className="mb-3 text-xs text-text-secondary">Tüm aktif projelerin toplamı — sözleşme geliri, bütçe, taahhüt, harcanan ve tahmini final maliyet.</p>
        <Card><CardBody><PortfolioBudgetChart data={budgetChartData} /></CardBody></Card>
      </div>
    ),
    cash_forecast: forecastChartData.length > 0 ? (
      <div>
        <div className="mb-1 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-primary">Nakit Akış Projeksiyonu (Önümüzdeki 6 Ay)</h2>
          {fc?.shortfall && <span className="rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-danger">Nakit açığı riski</span>}
        </div>
        <p className="mb-3 text-xs text-text-secondary">
          Bekleyen faturalardan beklenen tahsilatlar ile vadesi gelen ödemelerin projeksiyonu. En düşük öngörülen nakit:{" "}
          <span className={fc?.shortfall ? "font-semibold text-danger" : "font-semibold text-text-primary"}>{formatCurrency(fc?.min_cash_try)}</span>
          {fc?.min_cash_month ? ` (${fc.min_cash_month})` : ""}.
        </p>
        <Card><CardBody><CashFlowChart data={forecastChartData} /></CardBody></Card>
      </div>
    ) : null,
    cashflow_ar: (
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 text-lg font-semibold text-primary">Birleşik Nakit Akışı (Son 6 Ay)</h2>
          <Card><CardBody><CashFlowChart data={chartData} /></CardBody></Card>
        </div>
        <div>
          <h2 className="mb-1 text-lg font-semibold text-primary">Alacak Yaşlandırması</h2>
          <p className="mb-3 text-xs text-text-secondary">Bekleyen alacakların vade yaşına göre dağılımı ve ortalama tahsilat süresi (DSO).</p>
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
                {arBuckets.map((bk, i) => (<div key={i} style={{ width: `${arSeg(bk.v)}%`, backgroundColor: bk.color }} title={bk.label} />))}
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
        </div>
      </div>
    ),
    margin_fade: mf?.has_targets ? (
      <div>
        <h2 className="mb-1 text-lg font-semibold text-primary">Kar Marjı Erozyonu</h2>
        <p className="mb-3 text-xs text-text-secondary">
          Hedeflenen kar marjına karşı güncel (tahmini) marj. Portföy: Hedef{" "}
          <span className="font-semibold text-text-primary">{formatPct(mf.weighted_target_pct)}</span> · Güncel{" "}
          <span className="font-semibold text-text-primary">{formatPct(mf.weighted_current_pct)}</span>.
        </p>
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
      </div>
    ) : null,
  };

  return (
    <div>
      <PageHeader
        title="Ana Sayfa"
        subtitle="Tüm aktif projelerin finansal durumu"
        action={
          editMode ? (
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Button variant="outline" onClick={() => setAddOpen((o) => !o)} disabled={removableWidgets.length === 0}>
                  <Plus className="h-4 w-4" /> Widget Ekle
                </Button>
                {addOpen && removableWidgets.length > 0 && (
                  <div className="absolute right-0 z-30 mt-1 w-64 rounded-xl border border-border bg-surface py-1 shadow-lg">
                    {removableWidgets.map((w) => (
                      <button key={w.id} onClick={() => addWidget(w.id)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-bg">
                        <Plus className="h-3.5 w-3.5 text-brand" /> {w.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <Button variant="outline" onClick={resetDefault}>Varsayılan</Button>
              <Button variant="outline" onClick={cancelEdit}>İptal</Button>
              <Button onClick={saveLayout} loading={savingLayout}>Kaydet</Button>
            </div>
          ) : (
            <Button variant="outline" onClick={startEdit}>
              <SlidersHorizontal className="h-4 w-4" /> Widget'ları Düzenle
            </Button>
          )
        }
      />

      <OverduePaymentsModal open={overdueOpen} onClose={() => setOverdueOpen(false)} onChanged={refetch} onGoToReminders={() => navigate("/reminders")} />
      <LowMarginModal open={marginOpen} onClose={() => setMarginOpen(false)} projects={data?.projects ?? []} onSelect={(id) => { setMarginOpen(false); navigate(`/projects/${id}/dashboard`); }} />

      {editMode && (
        <div className="mb-4 rounded-lg border border-brand/30 bg-navy-50 px-4 py-2 text-xs text-text-secondary">
          Düzenleme modu: widget'ları başlıktan tutup sürükleyin, sağ alt köşeden boyutlandırın, × ile kaldırın veya "Widget Ekle" ile geri ekleyin. Bitince <span className="font-medium text-text-primary">Kaydet</span>.
        </div>
      )}

      <div className="-mx-2">
        <ResponsiveGrid
          className={cn(editMode && "rounded-xl bg-bg/40")}
          layouts={{ lg: grid, md: grid, sm: grid }}
          breakpoints={{ lg: 1024, md: 768, sm: 0 }}
          cols={{ lg: 12, md: 12, sm: 1 }}
          rowHeight={30}
          margin={[16, 16]}
          isDraggable={editMode}
          isResizable={editMode}
          draggableHandle=".widget-drag"
          compactType="vertical"
          onBreakpointChange={(b) => setBp(b)}
          onLayoutChange={(cur) => onGridChange(cur)}
        >
          {grid.map((g) => {
            const node = widgetNodes[g.i];
            const meta = WIDGETS.find((w) => w.id === g.i);
            return (
              <div key={g.i} className={cn("flex h-full flex-col overflow-hidden", editMode && "rounded-xl border-2 border-dashed border-border bg-surface")}>
                {editMode && (
                  <div className="widget-drag flex shrink-0 cursor-move items-center justify-between rounded-t-lg bg-bg px-3 py-1.5">
                    <span className="flex items-center gap-2 text-xs font-medium text-text-secondary">
                      <GripVertical className="h-4 w-4" /> {meta?.label ?? g.i}
                    </span>
                    <button onClick={() => removeWidget(g.i)} className="rounded p-0.5 text-text-secondary hover:bg-surface hover:text-danger" aria-label="Widget'ı kaldır">
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                )}
                <div className={cn("min-h-0 flex-1 overflow-auto", editMode && "p-2")}>{node}</div>
              </div>
            );
          })}
        </ResponsiveGrid>
      </div>
    </div>
  );
}


function AISummaryStrip({ k, briefing, navigate }: { k: any; briefing: any[]; navigate: (p: string) => void }) {
  const parts: string[] = [];
  if (k) {
    parts.push(`${k.active_project_count ?? 0} aktif proje`);
    parts.push(`${formatCurrencyAbbrev(k.total_contract_value_try)} portföy`);
    parts.push(`ort. marj ${formatPct(k.weighted_avg_margin_pct)}`);
    if ((k.overdue_payment_count ?? 0) > 0) parts.push(`${k.overdue_payment_count} vadesi geçmiş ödeme`);
  }
  const top = briefing.slice(0, 2);
  return (
    <div className="mb-5 flex items-center gap-4 rounded-xl bg-gradient-to-r from-[#1e3a8a] via-[#2563eb] to-[#0891b2] px-4 py-3 text-white shadow-sm">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/15">
        <Sparkles className="h-5 w-5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">AI Özeti · Bugün</div>
        <div className="mt-0.5 text-[13px] leading-snug text-white/90">
          {parts.length ? parts.join(" · ") : "Projeleriniz analiz ediliyor…"}
          {top.length > 0 && (
            <span className="ml-1.5 inline-flex flex-wrap gap-1.5 align-middle">
              {top.map((t, i) => (
                <button key={i} onClick={() => navigate("/ai-alerts")} className="rounded-md bg-white/15 px-2 py-0.5 text-[11px] hover:bg-white/25">
                  {t.project_name}
                </button>
              ))}
            </span>
          )}
        </div>
      </div>
      <button onClick={() => navigate("/ai-assistant")} className="hidden shrink-0 items-center gap-1 rounded-lg bg-white/15 px-3 py-1.5 text-xs hover:bg-white/25 sm:flex">
        Detaylı analiz →
      </button>
    </div>
  );
}

function sevStyle(severity: string): { bg: string; fg: string; Icon: typeof AlertTriangle } {
  switch (severity) {
    case "high":
      return { bg: "bg-red-50", fg: "text-danger", Icon: AlertTriangle };
    case "medium":
      return { bg: "bg-amber-50", fg: "text-warning", Icon: AlarmClock };
    default:
      return { bg: "bg-navy-50", fg: "text-brand", Icon: Info };
  }
}
