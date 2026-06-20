import { AskAgentDrawer } from "@/components/dashboard/AskAgentDrawer";
import { PriorityBriefingDrawer } from "@/components/dashboard/PriorityBriefingDrawer";
import { type BriefingItem } from "@/components/dashboard/InsightItem";
import { BriefingHero, type RiskChips } from "@/components/dashboard/buildflow/BriefingHero";
import { KpiCards } from "@/components/dashboard/buildflow/KpiCards";
import { DashboardCharts } from "@/components/dashboard/buildflow/DashboardCharts";
import { ProjectRiskTable } from "@/components/dashboard/buildflow/ProjectRiskTable";
import { ReportsPanel } from "@/components/dashboard/buildflow/ReportsPanel";
import { RightRail } from "@/components/dashboard/buildflow/RightRail";
import { LoadError } from "@/components/EmptyState";
import { Modal } from "@/components/ui";
import { useFetch } from "@/hooks/useFetch";
import { apiGet } from "@/lib/api";
import { cachedGet } from "@/lib/requestCache";
import { useAuth } from "@/store/auth";
import { useAISummaryStore } from "@/store/aiSummary";
import { useDashboardFilters } from "@/store/dashboardFilters";
import type { AIAlert } from "@/types";
import { formatCurrency, formatPct, toNumber } from "@/utils/format";
import { ArrowUp, Filter as FilterIcon, Settings2, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

// ---- dashboard data shape (subset used here; full payload from GET /dashboard) ----
interface DashboardData {
  kpis: {
    active_project_count: number;
    total_contract_value_try: string;
    weighted_avg_margin_pct: string;
    overdue_payment_count: number;
    cost_to_complete_try: string;
  };
  projects: any[];
  kpi_trends?: Record<string, { series: number[]; delta_pct: number | null }>;
  exec_kpis?: { backlog_try: string; projected_profit_try: string; total_receivables_try: string; net_cash_position_try: string };
  portfolio_budget?: { contract_try: string; revised_budget_try: string; committed_try: string; actual_try: string; forecast_final_cost_try: string };
  portfolio_performance?: { project: string; contract_try: string; actual_try: string; forecast_final_try: string }[];
  cash_forecast?: { months: { month: string; inflow_try: string; outflow_try: string; net_try: string; cumulative_try: string }[]; min_cash_try: string; min_cash_month: string | null; shortfall: boolean };
  margin_fade?: { has_targets: boolean; weighted_target_pct: string; weighted_current_pct: string; projects: { name: string; target_pct: string; current_pct: string }[] };
  // CR-014 portfolio USD snapshot totals (the only USD figures the payload exposes).
  usd?: { costs: { amount_usd: string | null; usd_missing_count: number }; invoices: { amount_usd: string | null; usd_missing_count: number } };
}

function rangeToParams(range: string): Record<string, string> {
  if (range === "all") return {};
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const from = range === "this_month" ? new Date(y, m, 1) : range === "last_3_months" ? new Date(y, m - 2, 1) : new Date(y, 0, 1);
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { date_from: iso(from), date_to: iso(now) };
}

/** Compose the briefing paragraph from the SAME dashboard payload the KPI cards
 *  use (kpis.weighted_avg_margin_pct, exec_kpis.net_cash_position_try) so the
 *  narrative and the KPIs can never contradict (fix #2). Risk drivers come from
 *  the dashboard project list (lowest margin), consistent with the table — not
 *  from a separate AI computation. No fabricated numbers; "—"-safe. */
function composeBriefing(data: DashboardData | null): string {
  if (!data) return "";
  const k = data.kpis;
  const ex = data.exec_kpis;
  const mf = data.margin_fade;
  const fc = data.cash_forecast;
  const active = k?.active_project_count ?? 0;
  const below = mf?.projects?.filter((p) => toNumber(p.current_pct) < toNumber(p.target_pct)).length ?? 0;
  const parts: string[] = [`${active} aktif proje`];
  if (below > 0) parts.push(`${below}'i hedef marjın altında`);
  if (k?.weighted_avg_margin_pct != null && k.weighted_avg_margin_pct !== "") parts.push(`öngörülen portföy marjı ${formatPct(k.weighted_avg_margin_pct)}`);
  if (ex?.net_cash_position_try != null && ex.net_cash_position_try !== "") parts.push(`net nakit pozisyonu ${formatCurrency(ex.net_cash_position_try)}`);
  let s = parts.join("; ") + ".";
  if (fc?.shortfall) s += ` Önümüzdeki dönemde en düşük öngörülen nakit ${formatCurrency(fc.min_cash_try)}${fc.min_cash_month ? ` (${fc.min_cash_month})` : ""} — nakit açığı riski.`;
  const risky = [...(data.projects ?? [])]
    .sort((a, b) => toNumber(a.margin_pct) - toNumber(b.margin_pct))
    .slice(0, 3)
    .map((p) => p.name)
    .filter(Boolean);
  if (risky.length) s += ` Öne çıkan riskli projeler: ${risky.join(", ")}.`;
  return s;
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { range } = useDashboardFilters(); // fix #1: date range now lives in the top header
  const params = useMemo(() => rangeToParams(range), [range]);
  const { data, loading, error, refetch } = useFetch<DashboardData>("/dashboard", params);
  const { data: alerts } = useFetch<AIAlert[]>("/ai/alerts");
  const isDirector = useAuth((s) => s.user?.role === "director");
  // fix #5: split /approvals by kind so the action queue gets real faturalar + ek iş counts.
  const [approvalsCount, setApprovalsCount] = useState<number | null>(null);
  const [approvalsByKind, setApprovalsByKind] = useState<{ faturalar: number; ekIsler: number } | null>(null);
  useEffect(() => {
    if (!isDirector) return; // /approvals is director-scoped → others see "—"
    cachedGet<any[]>("/approvals")
      .then((r) => {
        const items = (r.data ?? []) as { kind?: string }[];
        setApprovalsCount(items.length);
        setApprovalsByKind({
          faturalar: items.filter((i) => i.kind === "cost_entry").length,
          ekIsler: items.filter((i) => i.kind === "variation").length,
        });
      })
      .catch(() => { setApprovalsCount(null); setApprovalsByKind(null); });
  }, [isDirector]);

  // CR-029 §6: cached daily briefing (no fresh agent call per load).
  const [briefing, setBriefing] = useState<BriefingItem[]>([]);
  const [briefingState, setBriefingState] = useState<"loading" | "ready" | "error">("loading");
  const { getSummary, setSummary, clearSummary } = useAISummaryStore();
  const CACHE_KEY = "dashboard-summary";

  const fetchBriefing = () => {
    setBriefingState("loading");
    apiGet<BriefingItem[]>("/ai/daily-briefing")
      .then((r) => {
        setBriefing(r.data);
        setBriefingState("ready");
        setSummary(CACHE_KEY, JSON.stringify(r.data));
      })
      .catch(() => {
        setBriefing([]);
        setBriefingState("error");
      });
  };

  useEffect(() => {
    const cached = getSummary(CACHE_KEY);
    if (cached) {
      try {
        setBriefing(JSON.parse(cached.content));
      } catch {
        setBriefing([]);
      }
      setBriefingState("ready");
      return;
    }
    fetchBriefing();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // CR-029-B: the sidebar "AI Sistem Durumu" refresh button broadcasts this.
  useEffect(() => {
    const onRefresh = () => {
      refetch();
      clearSummary(CACHE_KEY);
      fetchBriefing();
    };
    window.addEventListener("yapi:refresh", onRefresh);
    return () => window.removeEventListener("yapi:refresh", onRefresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refetch]);

  // ---- AI command bar (⌘K) → cited agent answer in a SideDrawer ----
  const [cmd, setCmd] = useState("");
  const [askQuestion, setAskQuestion] = useState<string | null>(null);
  const [briefingOpen, setBriefingOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false); // hero info → "brifing nasıl üretildi"
  const [customiseOpen, setCustomiseOpen] = useState(false); // fix #2 → personalisation panel
  const cmdRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        e.stopImmediatePropagation();
        cmdRef.current?.focus();
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, []);

  const ask = () => {
    const q = cmd.trim();
    if (q) setAskQuestion(q);
  };

  // ---- briefing text + risk chips (real data) ----
  const briefingText = useMemo(() => composeBriefing(data ?? null), [data]);
  const chips: RiskChips = useMemo(() => {
    const a = alerts ?? [];
    return {
      kritik: a.filter((x) => x.severity === "high").length,
      izle: a.filter((x) => x.severity === "medium").length,
      firsat: a.filter((x) => x.severity === "low").length,
      hazir: a.filter((x) => !!x.dedup_key).length, // CR-022 assurance findings
    };
  }, [alerts]);

  return (
    <div className="px-4 pb-[18px]">
      {/* AI command row (§5) */}
      <div className="flex items-center gap-3.5 py-3">
        <div className="flex h-[42px] flex-1 items-center gap-2.5 rounded-card border-[1.5px] border-[#6366F1] bg-surface px-3.5 shadow-[0_0_0_3px_rgba(99,102,241,0.06)]">
          <Sparkles className="h-[18px] w-[18px] shrink-0 text-purple" />
          <input
            ref={cmdRef}
            value={cmd}
            onChange={(e) => setCmd(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
            placeholder="Yapı'ya sor… bu hafta marj neden düştü?"
            aria-label="Yapı'ya sor"
            className="h-full w-full bg-transparent text-[13px] outline-none placeholder:text-text-faint"
          />
          <button
            onClick={ask}
            disabled={!cmd.trim()}
            aria-label="Sor"
            className="focus-ring flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[7px] bg-brand text-white transition hover:bg-brand-light disabled:opacity-40"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        </div>

        {/* Filters & Customise — opens the personalisation panel (fix #2). Date /
            project / currency now live in the top header (fix #1). */}
        <button
          onClick={() => setCustomiseOpen(true)}
          className="focus-ring hidden h-9 items-center gap-2 rounded-control border border-border bg-surface px-3 text-[13px] text-text-secondary transition-colors hover:bg-surface-hover lg:flex"
        >
          <FilterIcon className="h-4 w-4 text-text-muted" />
          <Settings2 className="h-4 w-4 text-text-muted" />
          <span>Filtreler &amp; Özelleştir</span>
        </button>
      </div>

      {error && !loading ? (
        <div className="rounded-card border border-border bg-surface shadow-card">
          <LoadError message="Gösterge paneli verileri yüklenemedi. Lütfen tekrar deneyin." onRetry={refetch} />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-[minmax(0,1fr)_350px]">
          {/* main column */}
          <div className="flex min-w-0 flex-col gap-3">
            <BriefingHero
              text={briefingText}
              loading={loading || briefingState === "loading"}
              error={briefingState === "error"}
              chips={chips}
              onChipClick={() => navigate("/ai-alerts")}
              onDetail={() => setBriefingOpen(true)}
              onInfo={() => setInfoOpen(true)}
            />
            <KpiCards data={data} approvalsCount={approvalsCount} loading={loading} />
            <DashboardCharts data={data} loading={loading} />

            {/* Lower grid: project-risk table (wide) + reports & decks (§9–§10) */}
            <div className="grid grid-cols-1 gap-2.5 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.9fr)]">
              <ProjectRiskTable
                projects={data?.projects ?? []}
                performance={data?.portfolio_performance ?? []}
                marginFade={data?.margin_fade?.projects ?? []}
                alerts={alerts ?? []}
                loading={loading}
              />
              <ReportsPanel />
            </div>

            {/* Custom layout hint (§12) → personalisation panel (fix #2). */}
            <div className="flex items-center gap-2 px-1 pt-1 text-[11.5px] text-text-muted">
              <Settings2 className="h-3.5 w-3.5" />
              Widget'ları sürükleyerek yeniden düzenleyin • Widget ekley/çıkarın:&nbsp;
              <button className="focus-ring font-medium text-brand hover:underline" onClick={() => setCustomiseOpen(true)}>Özel düzen</button>
            </div>
          </div>

          {/* right rail — CR-029-F: action queue, skills, feed. */}
          <div className="flex flex-col gap-3">
            <RightRail alerts={alerts ?? []} approvalsByKind={approvalsByKind} />
          </div>
        </div>
      )}

      <AskAgentDrawer question={askQuestion} onClose={() => setAskQuestion(null)} />
      <PriorityBriefingDrawer
        open={briefingOpen}
        onClose={() => setBriefingOpen(false)}
        briefing={briefing}
        briefingState={briefingState}
        onRefresh={() => { clearSummary(CACHE_KEY); fetchBriefing(); }}
      />
      <Modal open={infoOpen} title="Bu brifing nasıl üretildi?" onClose={() => setInfoOpen(false)} size="md">
        <div className="space-y-2 text-sm text-text-secondary">
          <p>Yapı AI Brifingi, panodaki gerçek verilerinizden (aktif projeler, hedef-altı marjlar, öngörülen portföy marjı, nakit projeksiyonu) ve günlük AI brifingindeki risk maddelerinden derlenir.</p>
          <p>Yalnızca okur; hiçbir finansal veriyi değiştirmez. Sayılar mevcut verilerinizle birebir uyumludur — eksik alanlar uydurulmaz.</p>
        </div>
      </Modal>
      {/* fix #2: the personalisation/customise panel (NOT the briefing explainer). */}
      <Modal open={customiseOpen} title="Panoyu Özelleştir" onClose={() => setCustomiseOpen(false)} size="md">
        <div className="space-y-2 text-sm text-text-secondary">
          <p>Bu panelden pano widget'larını <span className="font-medium text-text-primary">ekleyebilir, çıkarabilir ve yeniden düzenleyebilirsiniz</span>; tarih aralığı, proje ve para birimi filtreleri üst çubukta yer alır.</p>
          <p>Sürükle-bırak ile yeniden düzenleme ve widget aç/kapa: <span className="font-medium text-text-primary">Bu özellik yakında tüm kullanıcılara sunulacak.</span></p>
        </div>
      </Modal>
    </div>
  );
}
