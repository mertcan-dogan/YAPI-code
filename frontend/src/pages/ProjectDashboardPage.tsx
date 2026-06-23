import { CashFlowChart, MarginBridgeChart, SCurveChart } from "@/components/charts";
import { AIDisclaimer, Button, Modal, Skeleton } from "@/components/ui";
import { CostEntriesDrawer } from "@/components/dashboard/CostEntriesDrawer";
import { DashboardSection } from "@/components/dashboard/DashboardSection";
import { KpiDetailModal, type KpiInfo } from "@/components/dashboard/KpiDetailModal";
import { MilestonesCard, type MilestonesBlock } from "@/components/dashboard/MilestonesCard";
import { CurrencyToggle, UsdMissingNote, useShowUsd } from "@/components/currency";
import { EmptyState, LoadError } from "@/components/EmptyState";
import { PageHeader } from "@/components/layout/AppLayout";
import { RAGIndicator } from "@/components/RAGIndicator";
import { ResidentialDetailsEditor, unitsForPayload, type UnitRow } from "@/components/UnitScheduleEditor";
import { UNIT_TYPES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { useAISummaryStore } from "@/store/aiSummary";
import type { ProjectFinancials, Project, ResidentialAggregates } from "@/types";
import { formatCurrency, formatDate, formatDateTime, formatPct, formatUSD, toNumber } from "@/utils/format";
import { shouldShowFinancingHint } from "@/utils/financing";
import { dashRangeParams, type DashPreset } from "@/utils/dashboardRange";
import { computeProjectHealth, healthExplanation, HEALTH_SIGNAL_META, type ProjectHealth } from "@/utils/projectHealth";
import { cn } from "@/lib/cn";
import { Activity, Building2, ChevronRight, Coins, Pencil, PieChart, RefreshCw, Sparkles } from "lucide-react";
import * as React from "react";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

// One row in a "story" metric table: a Turkish label, the ₺ amount, an optional
// USD snapshot (else "—"), a % (proportion in money mode / the value itself in
// percent mode), and the KpiInfo opened on click. `alert` tints the figure.
interface MetricRowDef {
  label: string;
  tryValue?: string | null;
  usdValue?: string | null;
  // Proportion (money mode) or the value itself (percent mode). `null` means the
  // denominator was 0 (no valid proportion) → render "—", never "%0,0".
  pct: number | null;
  alert?: "amber" | "red" | null;
  kpi: KpiInfo;
}

const RESIDENTIAL_TYPES = new Set(["building_residential", "urban_transformation"]);

// CR: dashboard date-range filter — mirrors the CashFlowPage preset pattern.
const DASH_PRESETS: { key: DashPreset; label: string }[] = [
  { key: "3m", label: "Son 3 Ay" },
  { key: "6m", label: "Son 6 Ay" },
  { key: "12m", label: "Son 12 Ay" },
  { key: "year", label: "Bu Yıl" },
  { key: "all", label: "Tümü" },
  { key: "custom", label: "Özel" },
];

interface PeriodSummary {
  from_date: string;
  to_date: string;
  cost_incurred_try: string;
  invoiced_try: string;
  collected_try: string;
  net_try: string;
  cost_incurred_usd: string;
  invoiced_usd: string;
  collected_usd: string;
  usd_missing_count: number;
  cost_count: number;
  invoice_count: number;
  collected_count: number;
}

interface FAC {
  original_budget_try: string;
  revised_budget_try: string;
  cost_to_date_try: string;
  cost_to_complete_try: string;
  forecast_final_cost_try: string;
  forecast_final_margin_pct: string;
  over_budget: boolean;
  // CR-015-B: separable financing overlay (0.00 / equal to base when off).
  financing_cost_try?: string;
  forecast_final_cost_with_financing_try?: string;
  forecast_final_margin_with_financing_pct?: string;
}

// CR-015-B: modeled financing-cost block (forecast overlay, never an actual cost).
interface FinancingBlock {
  enabled: boolean;
  annual_rate_pct: string | null;
  basis: string;
  total_usd: string;
  total_try: string;
  months: { month: string; financed_try: string; rate: string; interest_usd: string; interest_try: string }[];
}

// CR-014-C/D: USD snapshot-sum totals (point-in-time), with missing-snapshot counts.
interface UsdBlock {
  costs: { amount_usd: string; usd_missing_count: number };
  invoices: { amount_usd: string; usd_missing_count: number };
}

export default function ProjectDashboardPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [costDrawer, setCostDrawer] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [kpiDetail, setKpiDetail] = useState<KpiInfo | null>(null);

  // CR-007-H: an AI cost-entry citation deep-links here as ?highlight=<id>. Open
  // the cost drawer to that entry, then clear the param so back/refresh is clean.
  const [searchParams, setSearchParams] = useSearchParams();
  const [highlightCostId, setHighlightCostId] = useState<string | null>(null);
  useEffect(() => {
    const h = searchParams.get("highlight");
    if (!h) return;
    setHighlightCostId(h);
    setCostDrawer(true);
    searchParams.delete("highlight");
    setSearchParams(searchParams, { replace: true });
    const t = setTimeout(() => setHighlightCostId(null), 2500);
    return () => clearTimeout(t);
  }, [searchParams, setSearchParams]);
  const { data, loading, error, refetch } = useFetch<{ project: Project; financials: ProjectFinancials; cashflow: any[]; forecast_at_completion: FAC; margin_bridge: Record<string, string>; usd?: UsdBlock; residential?: ResidentialAggregates; financing?: FinancingBlock; milestones?: MilestonesBlock; degraded_sections?: string[] }>(
    `/projects/${id}/dashboard`,
    undefined,
    // Bound a hanging request so a stalled load shows LoadError+retry rather than
    // an infinite skeleton (the silent-load-failure class).
    { timeout: 20000 }
  );
  const showUsd = useShowUsd(); // CR-014-D
  const p = data?.project;
  const f = data?.financials;
  const fac = data?.forecast_at_completion;

  // CR-016-C: residential details (m² + daire dağılımı). Visible for residential
  // project types or any project that already carries a schedule / construction m².
  const isDirector = useAuth((s) => s.user?.role === "director");
  // CR-019-C: directors + project managers manage milestones (mirrors the API).
  const role = useAuth((s) => s.user?.role);
  const canManageMilestones = role === "director" || role === "project_manager";
  const isResidential =
    (p?.units?.length ?? 0) > 0 ||
    !!(p?.construction_gross_m2) ||
    (p ? RESIDENTIAL_TYPES.has(p.project_type) : false);
  const [resEdit, setResEdit] = useState(false);
  const [resSaving, setResSaving] = useState(false);
  const [resGross, setResGross] = useState("");
  const [resNet, setResNet] = useState("");
  const [resUnits, setResUnits] = useState<UnitRow[]>([]);

  const openResEdit = () => {
    setResGross(p?.construction_gross_m2 ?? "");
    setResNet(p?.construction_net_m2 ?? "");
    setResUnits(
      (p?.units ?? []).map((u) => ({
        id: u.id,
        unit_type: u.unit_type,
        custom_label: u.custom_label ?? "",
        count: String(u.count),
        gross_m2_each: u.gross_m2_each,
        net_m2_each: u.net_m2_each ?? "",
        sale_price_try: u.sale_price_try ?? "",
        notes: u.notes ?? "",
      }))
    );
    setResEdit(true);
  };

  const saveResidential = async () => {
    setResSaving(true);
    try {
      await apiPut(`/projects/${id}`, {
        construction_gross_m2: resGross || null,
        construction_net_m2: resNet || null,
        units: unitsForPayload(resUnits),
      });
      toast.success("Konut detayları kaydedildi");
      setResEdit(false);
      refetch();
    } catch (e: any) {
      toast.error(e?.message ?? "Konut detayları kaydedilemedi");
    } finally {
      setResSaving(false);
    }
  };

  // CR-015-C: modeled financing cost (forecast overlay). Include/exclude toggle
  // flips the *displayed* forecast margin between base and with-financing; an
  // expandable per-month breakdown; a director-only project override.
  const financing = data?.financing;
  const financingOn = !!financing?.enabled && toNumber(financing?.total_try) > 0;
  const [includeFinancing, setIncludeFinancing] = useState(true);
  const [finMonthsOpen, setFinMonthsOpen] = useState(false);
  const [finEditOpen, setFinEditOpen] = useState(false);
  const [finSaving, setFinSaving] = useState(false);
  const [finForm, setFinForm] = useState<{ mode: string; rate: string }>({ mode: "inherit", rate: "" });

  const openFinEdit = () => {
    const enabledOverride = p?.financing_enabled_override;
    setFinForm({
      mode: enabledOverride === null || enabledOverride === undefined ? "inherit" : enabledOverride ? "on" : "off",
      rate: p?.financing_annual_rate_pct_override ?? "",
    });
    setFinEditOpen(true);
  };

  const saveFinancing = async () => {
    setFinSaving(true);
    try {
      await apiPut(`/projects/${id}`, {
        financing_enabled_override: finForm.mode === "inherit" ? null : finForm.mode === "on",
        financing_annual_rate_pct_override: finForm.rate === "" ? null : finForm.rate,
      });
      toast.success("Finansman ayarı kaydedildi");
      setFinEditOpen(false);
      refetch();
    } catch (e: any) {
      toast.error(e?.message ?? "Finansman ayarı kaydedilemedi");
    } finally {
      setFinSaving(false);
    }
  };

  // The forecast margin actually shown: with financing when enabled + included.
  const shownForecastMargin =
    financingOn && includeFinancing && fac?.forecast_final_margin_with_financing_pct != null
      ? fac.forecast_final_margin_with_financing_pct
      : fac?.forecast_final_margin_pct;

  // CR-003-F + CR-005-G: AI narrative, cached per project so it runs once and
  // survives navigation/reload; manual refresh re-runs it.
  const [narrative, setNarrative] = useState<{ narrative: string; generated_at: string } | null>(null);
  const [narrLoading, setNarrLoading] = useState(false);
  const [narrCachedAt, setNarrCachedAt] = useState<string | null>(null);
  const { getSummary, setSummary, clearSummary } = useAISummaryStore();
  const cacheKey = `project-summary-${id}`;

  const fetchNarrative = () => {
    setNarrLoading(true);
    apiPost<{ narrative: string; generated_at: string }>(`/projects/${id}/ai-narrative`)
      .then((r) => {
        setNarrative(r);
        setSummary(cacheKey, r.narrative, id);
        setNarrCachedAt(getSummary(cacheKey)?.generatedAt ?? new Date().toISOString());
      })
      .catch(() => setNarrative(null))
      .finally(() => setNarrLoading(false));
  };

  const loadNarrative = () => {
    const cached = getSummary(cacheKey);
    if (cached) {
      setNarrative({ narrative: cached.content, generated_at: cached.generatedAt });
      setNarrCachedAt(cached.generatedAt);
      return;
    }
    fetchNarrative();
  };

  const refreshNarrative = () => {
    clearSummary(cacheKey);
    fetchNarrative();
  };

  useEffect(() => { if (id) loadNarrative(); /* eslint-disable-next-line */ }, [id]);

  const margin = toNumber(f?.margin_pct);
  const remaining = toNumber(f?.remaining_budget_try);
  const actualVsBudget = toNumber(f?.total_actual_with_vat_try) / Math.max(toNumber(f?.revised_budget_try), 1);

  // CR: date-range filter. Only "Dönem Özeti" + the time-series charts respond;
  // the headline KPIs (Sözleşme, Marj, Tahmin…) stay full-project. Default "Tümü".
  const [preset, setPreset] = useState<DashPreset>("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const r = dashRangeParams(preset, customFrom, customTo);
  const { rangeActive, label: rangeLabel, invalid: customInvalid } = r;

  // Period summary (always fetched; "Tümü" uses wide bounds = whole project).
  const period = useFetch<PeriodSummary>(`/projects/${id}/period-summary`, {
    from_date: r.from_date,
    to_date: r.to_date,
  });
  const ps = period.data;
  // Charts: ranged cashflow when a range is active, else the dashboard's window.
  const cfRange = useFetch<any[]>(
    rangeActive ? `/projects/${id}/cashflow` : null,
    rangeActive ? { from_month: r.from_month, to_month: r.to_month } : undefined,
  );

  // Build S-curve + monthly cashflow series from the (optionally ranged) window.
  const cf = rangeActive ? (cfRange.data ?? []) : (data?.cashflow ?? []);
  // Silent-load guard: when a range is active and its cashflow fetch fails, the
  // charts must show a retryable error — NOT collapse to an "empty" EmptyState
  // that reads as "no data". (The non-ranged window comes from the main dashboard
  // fetch, already covered by the page-level LoadError above.)
  const cfError = rangeActive && !!cfRange.error && !cfRange.loading;
  let plannedCum = 0;
  let actualCum = 0;
  const sCurve = cf.map((r) => {
    plannedCum += toNumber(r.planned_out_try);
    actualCum += toNumber(r.actual_out_try);
    return { month: r.month, planned: plannedCum, actual: actualCum };
  });
  let cum = 0;
  const cashflow = cf.map((r) => {
    const inV = r.is_past || r.is_current ? toNumber(r.actual_in_try) : toNumber(r.planned_in_try);
    const outV = r.is_past || r.is_current ? toNumber(r.actual_out_try) : toNumber(r.planned_out_try);
    cum += inV - outV;
    return { month: r.month, out: outV, in: inV, cumulative: cum };
  });

  // --- Three "story" tables (whole-project; unaffected by the date-range filter).
  // % proportions: revenue rows share Sözleşme Değeri, budget rows share Revize
  // Bütçe. USD shown only where the dashboard's USD block carries it, else "—".
  const contract = toNumber(f?.contract_value_try);
  const revised = toNumber(fac?.revised_budget_try ?? f?.revised_budget_try);
  // Divide-by-zero guard: a 0 base yields no proportion → null → renders "—".
  const shareOf = (base: number, v?: string | null): number | null => (base > 0 ? (toNumber(v) / base) * 100 : null);

  const revenueRows: MetricRowDef[] = [
    {
      label: "Sözleşme Değeri", tryValue: f?.contract_value_try, pct: contract > 0 ? 100 : null,
      kpi: { title: "Sözleşme Değeri", value: formatCurrency(f?.contract_value_try), accentColor: "#2563EB",
        description: "Proje sözleşme bedeli — işverenle anlaşılan toplam gelir (KDV hariç)." },
    },
    {
      label: "İşverene Faturalanan", tryValue: f?.total_invoiced_try, usdValue: data?.usd?.invoices.amount_usd, pct: shareOf(contract, f?.total_invoiced_try),
      kpi: { title: "İşverene Faturalanan", value: formatCurrency(f?.total_invoiced_try), accentColor: "#2563EB",
        description: "İşverene kesilen hakediş ve faturaların toplam tutarı.",
        action: { label: "Faturalara git", onClick: () => navigate(`/projects/${id}/invoices`) } },
    },
    {
      label: "Tahsil Edilen", tryValue: f?.total_collected_try, pct: shareOf(contract, f?.total_collected_try),
      kpi: { title: "Tahsil Edilen", value: formatCurrency(f?.total_collected_try), accentColor: "#059669",
        description: "İşverenden bugüne kadar tahsil edilen toplam tutar.",
        action: { label: "Faturalara git", onClick: () => navigate(`/projects/${id}/invoices`) } },
    },
    {
      label: "Bekleyen Tahsilat", tryValue: f?.total_outstanding_try, pct: shareOf(contract, f?.total_outstanding_try),
      kpi: { title: "Bekleyen Tahsilat", value: formatCurrency(f?.total_outstanding_try), accentColor: "#D97706",
        description: "Faturalanan ancak henüz tahsil edilmemiş tutar — açık alacaklar.",
        action: { label: "Faturalara git", onClick: () => navigate(`/projects/${id}/invoices`) } },
    },
    {
      label: "Hakediş Kesintisi", tryValue: f?.total_retention_try, pct: shareOf(contract, f?.total_retention_try),
      kpi: { title: "Hakediş Kesintisi", value: formatCurrency(f?.total_retention_try), accentColor: "#0E1525",
        description: "Hakedişlerden kesilen teminat (stopaj/teminat) toplamı.",
        action: { label: "Faturalara git", onClick: () => navigate(`/projects/${id}/invoices`) } },
    },
  ];

  const budgetRows: MetricRowDef[] = [
    {
      label: "Orijinal Bütçe", tryValue: fac?.original_budget_try, pct: shareOf(revised, fac?.original_budget_try),
      kpi: { title: "Orijinal Bütçe", value: formatCurrency(fac?.original_budget_try), accentColor: "#2563EB",
        description: "Projenin başlangıçtaki onaylı bütçesi (ek işler hariç)." },
    },
    {
      label: "Revize Bütçe", tryValue: fac?.revised_budget_try, pct: revised > 0 ? 100 : null,
      kpi: { title: "Revize Bütçe", value: formatCurrency(fac?.revised_budget_try), accentColor: "#06B6D4",
        description: "Onaylı ek işler eklendikten sonraki güncel bütçe." },
    },
    {
      label: "Gerçekleşen Maliyet", tryValue: f?.total_actual_with_vat_try, usdValue: data?.usd?.costs.amount_usd,
      pct: shareOf(revised, f?.total_actual_with_vat_try), alert: actualVsBudget > 0.8 ? "amber" : null,
      kpi: { title: "Gerçekleşen Maliyet", value: formatCurrency(f?.total_actual_with_vat_try), accentColor: "#F59E0B",
        description: "Bu projede bugüne kadar gerçekleşen toplam maliyet (KDV dahil). Revize bütçenin %80'ini aşınca uyarı verir.",
        action: { label: "Maliyet kayıtlarını gör", onClick: () => setCostDrawer(true) } },
    },
    {
      label: "Kalan Bütçe", tryValue: f?.remaining_budget_try, pct: shareOf(revised, f?.remaining_budget_try), alert: remaining < 0 ? "red" : null,
      kpi: { title: "Kalan Bütçe", value: formatCurrency(f?.remaining_budget_try), accentColor: "#06B6D4",
        description: "Revize bütçeden bugüne kadar harcanan tutar düşüldükten sonra kalan bakiye. Negatif değer bütçe aşımını gösterir.",
        action: { label: "Bütçeye git", onClick: () => navigate(`/projects/${id}/budget`) } },
    },
    {
      label: "Tamamlamaya Kalan Maliyet", tryValue: fac?.cost_to_complete_try, pct: shareOf(revised, fac?.cost_to_complete_try),
      alert: toNumber(fac?.cost_to_complete_try) > toNumber(fac?.revised_budget_try) ? "amber" : null,
      kpi: { title: "Tamamlamaya Kalan Maliyet", value: formatCurrency(fac?.cost_to_complete_try), accentColor: "#D97706",
        description: "İşi tamamlamak için gereken tahmini kalan maliyet (tahmini final maliyet eksi bugüne kadar gerçekleşen)." },
    },
    {
      label: "Tahmini Final Maliyet", tryValue: fac?.forecast_final_cost_try, pct: shareOf(revised, fac?.forecast_final_cost_try), alert: fac?.over_budget ? "red" : null,
      kpi: { title: "Tahmini Final Maliyet", value: formatCurrency(fac?.forecast_final_cost_try), accentColor: "#7C3AED",
        description: "Mevcut gidişata göre projenin tahmini toplam final maliyeti. Revize bütçeyi aşarsa kırmızı uyarı verir." },
    },
  ];

  const profitRows: MetricRowDef[] = [
    {
      label: "Güncel Kar Marjı", pct: margin, alert: margin < 5 ? "red" : margin < 10 ? "amber" : null,
      kpi: { title: "Güncel Kar Marjı", value: formatPct(f?.margin_pct), valueKind: "percent", accentColor: "#059669",
        description: "Sözleşme bedeline göre güncel (gerçekleşen) kar marjı. %10 altında izlenmeli, %5 altında riskli kabul edilir." },
    },
    ...(p?.target_margin_pct != null ? [{
      label: "Hedef Marj", pct: toNumber(p.target_margin_pct),
      kpi: { title: "Hedef Marj", value: formatPct(p.target_margin_pct), valueKind: "percent" as const, accentColor: "#2563EB",
        description: "Bu proje için belirlenen hedef kar marjı. Güncel ve tahmini marjı bu hedefle karşılaştırın." },
    }] : []),
    {
      label: financingOn && includeFinancing ? "Tahmini Final Marj (fin. dahil)" : "Tahmini Final Marj",
      pct: toNumber(shownForecastMargin), alert: toNumber(shownForecastMargin) < 5 ? "red" : toNumber(shownForecastMargin) < 10 ? "amber" : null,
      kpi: { title: "Tahmini Final Marj", value: formatPct(shownForecastMargin), valueKind: "percent", accentColor: "#059669",
        description: financingOn && includeFinancing
          ? "Tahmini finansman maliyeti DAHİL beklenen kar marjı (modellenmiş tahmin — gerçek maliyet değildir). Üstteki kutudan hariç tutabilirsiniz."
          : "Tahmini final maliyete göre beklenen kar marjı. %10 altında izlenmeli, %5 altında riskli." },
    },
  ];

  // CR-019-C: when milestones exist, the weighted schedule-progress % is the
  // objective "% Tamamlandı"; otherwise fall back to the manual completion_pct.
  // `hasMilestones` also makes a 0% an objective value (not a blank default).
  const milestones = data?.milestones;
  const hasMilestones = (milestones?.total ?? 0) > 0;
  const milestoneProgress = milestones?.schedule_progress_pct != null ? toNumber(milestones.schedule_progress_pct) : null;
  const milestoneBased = hasMilestones && milestoneProgress != null;
  const completionForHealth = milestoneBased ? milestoneProgress! : toNumber(f?.completion_pct);

  // Proje Sağlığı — completion vs cost-burn vs schedule-elapsed.
  const health = computeProjectHealth({
    completionPct: completionForHealth,
    hasMilestones,
    actualCostTry: toNumber(f?.total_actual_with_vat_try),
    revisedBudgetTry: revised,
    startDate: p?.start_date,
    plannedEndDate: p?.planned_end_date,
  });
  const [healthOpen, setHealthOpen] = useState(false);

  if (error && !loading) {
    return (
      <div>
        <PageHeader title="Proje Özeti" />
        <LoadError onRetry={refetch} />
      </div>
    );
  }

  return (
    <div>
      {/* Header: project title (left) + compact AI summary (right) */}
      <div className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-primary">{p?.name ?? "Proje Özeti"}</h1>
            {f && <RAGIndicator status={f.rag_status} label={f.rag_label_tr} reason={f.rag_reason_tr} />}
          </div>
          {p && <p className="mt-0.5 text-sm text-text-secondary">{p.client_name} · {p.project_code}</p>}
        </div>

        <div
          role="button"
          tabIndex={0}
          onClick={() => setAiOpen(true)}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setAiOpen(true)}
          title="Detaylı özeti aç"
          className="group w-full shrink-0 cursor-pointer overflow-hidden rounded-xl border border-border bg-surface shadow-sm transition-colors hover:border-brand lg:w-[640px]"
        >
          <div className="flex items-center justify-between gap-2 px-3 pb-1 pt-2">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-primary">
              <Sparkles className="h-3.5 w-3.5 text-brand" /> AI Proje Özeti
            </span>
            <div className="flex items-center gap-2">
              {narrCachedAt && <span className="hidden text-[10px] italic text-text-disabled sm:inline">{formatDateTime(narrCachedAt)}</span>}
              <button onClick={(e) => { e.stopPropagation(); refreshNarrative(); }} disabled={narrLoading} title="Yenile" aria-label="Yenile" className="text-text-secondary hover:text-primary disabled:opacity-50">
                <RefreshCw className={`h-3.5 w-3.5 ${narrLoading ? "animate-spin" : ""}`} />
              </button>
              <span className="text-[10px] font-medium text-brand opacity-0 transition-opacity group-hover:opacity-100">Detay →</span>
            </div>
          </div>
          <p className="line-clamp-2 px-3 pb-2 text-xs leading-snug text-text-secondary">
            {narrative?.narrative ?? (narrLoading ? "AI özeti hazırlanıyor…" : "Özet bulunamadı.")}
          </p>
        </div>
      </div>

      <Modal open={aiOpen} title="AI Proje Özeti" onClose={() => setAiOpen(false)} size="lg">
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-text-secondary">{narrCachedAt ? `Son güncelleme: ${formatDateTime(narrCachedAt)}` : ""}</span>
            <Button variant="ghost" className="px-2 py-1 text-xs" loading={narrLoading} onClick={refreshNarrative}>
              <RefreshCw className="h-3.5 w-3.5" /> Yenile
            </Button>
          </div>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-text-primary">
            {narrative?.narrative ?? (narrLoading ? "AI özeti hazırlanıyor…" : "Özet bulunamadı.")}
          </p>
          {!narrLoading && narrative?.narrative && <AIDisclaimer />}
        </div>
      </Modal>

      {/* CR: date-range filter — only "Dönem Özeti" + the time-series charts below
          respond to it. The headline KPIs stay full-project. */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1 rounded-md border border-border p-0.5">
          {DASH_PRESETS.map((pr) => (
            <button
              key={pr.key}
              onClick={() => setPreset(pr.key)}
              className={cn("rounded px-3 py-1 text-sm", preset === pr.key ? "bg-primary text-white" : "text-text-secondary")}
            >
              {pr.label}
            </button>
          ))}
        </div>
        {preset === "custom" && (
          <div className="flex items-center gap-2 text-sm">
            <input type="month" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)}
              className="rounded-md border border-border bg-surface px-2 py-1" aria-label="Başlangıç ayı" />
            <span className="text-text-secondary">→</span>
            <input type="month" value={customTo} onChange={(e) => setCustomTo(e.target.value)}
              className="rounded-md border border-border bg-surface px-2 py-1" aria-label="Bitiş ayı" />
            {customInvalid && <span className="text-xs text-danger">Başlangıç bitişten sonra olamaz</span>}
          </div>
        )}
      </div>
      <p className="mb-4 text-xs text-text-secondary">
        Ana göstergeler (Sözleşme, Kâr Marjı, Tamamlanmada Tahmin) <b>tüm projeyi</b> gösterir;
        yalnızca <b>Dönem Özeti</b> ve grafikler seçili dönemi yansıtır.
      </p>

      {/* Dönem Özeti — period activity totals (responds to the range). */}
      <div className="mb-4 rounded-xl border border-border bg-surface shadow-sm">
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <span className="text-sm font-semibold text-primary">Dönem Özeti — {rangeLabel}</span>
          {ps && (ps.usd_missing_count ?? 0) > 0 && <UsdMissingNote count={ps.usd_missing_count} />}
        </div>
        {period.error && !period.loading ? (
          <LoadError message="Dönem özeti yüklenemedi." onRetry={period.refetch} />
        ) : (
          <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
            <PeriodStat label="Maliyet (dönem)" try_={ps?.cost_incurred_try} usd={ps?.cost_incurred_usd} showUsd={showUsd} count={ps?.cost_count} loading={period.loading} />
            <PeriodStat label="Faturalanan (dönem)" try_={ps?.invoiced_try} usd={ps?.invoiced_usd} showUsd={showUsd} count={ps?.invoice_count} loading={period.loading} />
            <PeriodStat label="Tahsil Edilen (dönem)" try_={ps?.collected_try} usd={ps?.collected_usd} showUsd={showUsd} count={ps?.collected_count} loading={period.loading} />
            <PeriodStat label="Net (Tahsilat − Maliyet)" try_={ps?.net_try} showUsd={false} loading={period.loading} negative={toNumber(ps?.net_try) < 0} />
          </div>
        )}
      </div>

      {/* CR-014-D: USD snapshot totals (point-in-time) + ₺/$/İkisi de toggle.
          USD is a derived snapshot sum, NOT a live conversion. "—"/warning when
          rates are missing (e.g. before the USD backfill runs). */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {showUsd && (
            <>
              <span className="inline-flex items-center rounded-lg border border-border bg-surface px-3 py-1.5">
                <span className="text-text-secondary">Maliyet (USD):&nbsp;</span>
                <span className="tabular font-semibold text-primary">{formatUSD(data?.usd?.costs.amount_usd)}</span>
                <UsdMissingNote count={data?.usd?.costs.usd_missing_count} />
              </span>
              <span className="inline-flex items-center rounded-lg border border-border bg-surface px-3 py-1.5">
                <span className="text-text-secondary">Faturalanan (USD):&nbsp;</span>
                <span className="tabular font-semibold text-primary">{formatUSD(data?.usd?.invoices.amount_usd)}</span>
                <UsdMissingNote count={data?.usd?.invoices.usd_missing_count} />
              </span>
            </>
          )}
        </div>
        <CurrencyToggle />
      </div>

      {/* Three condensed "story" tables — whole-project (the date range above does
          not affect them). Each row → KpiDetailModal. */}
      {loading ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="rounded-xl border border-border bg-surface p-4 shadow-sm">
              <Skeleton className="mb-3 h-4 w-32" />
              {[0, 1, 2, 3].map((j) => <Skeleton key={j} className="mb-2 h-5 w-full" />)}
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3 lg:items-start">
          <MetricTable title="Gelir & Tahsilat" mode="money" showUsd={showUsd} rows={revenueRows} onRowClick={setKpiDetail} />
          <MetricTable title="Bütçe & Maliyet" mode="money" showUsd={showUsd} rows={budgetRows} onRowClick={setKpiDetail} />
          <MetricTable
            title="Kârlılık"
            mode="percent"
            showUsd={showUsd}
            rows={profitRows}
            onRowClick={setKpiDetail}
            headerExtra={financingOn ? (
              <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-text-secondary">
                <input type="checkbox" className="h-3 w-3 accent-[var(--color-primary)]" checked={includeFinancing} onChange={(e) => setIncludeFinancing(e.target.checked)} />
                Finansmanı dahil et
              </label>
            ) : undefined}
          />
        </div>
      )}

      {id && <CostEntriesDrawer open={costDrawer} onClose={() => setCostDrawer(false)} projectId={id} highlightId={highlightCostId} />}
      <KpiDetailModal open={!!kpiDetail} onClose={() => setKpiDetail(null)} kpi={kpiDetail} />

      {/* Proje Sağlığı — completion vs cost-burn vs schedule (on-track signal). */}
      {!loading && f && (
        <ProjectHealthCard health={health} milestoneBased={milestoneBased} onOpen={() => setHealthOpen(true)} />
      )}
      <Modal open={healthOpen} title="Proje Sağlığı" onClose={() => setHealthOpen(false)} size="md">
        <div className="space-y-4">
          <div className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", HEALTH_SIGNAL_META[health.signal].bg)}>
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: HEALTH_SIGNAL_META[health.signal].color }} />
            {HEALTH_SIGNAL_META[health.signal].label}
          </div>
          <div className="space-y-3">
            <HealthBar label={milestoneBased ? "% Tamamlandı (kilometre taşı)" : "% Tamamlandı"} pct={health.completionKnown ? health.completionPct : null} color="#2563EB" emptyNote="Yeterli veri yok" />
            <HealthBar label="% Bütçe Harcandı" pct={health.costPct} color={HEALTH_SIGNAL_META[health.signal].color} emptyNote="Bütçe girilmemiş" />
            <HealthBar label="% Süre Geçti" pct={health.timePct} color="#64748B" emptyNote="Tarih girilmemiş" />
          </div>
          {milestoneBased && (
            <p className="text-xs italic text-text-secondary">İlerleme, kilometre taşlarının ağırlıklı tamamlanmasından hesaplanır.</p>
          )}
          <div className="rounded-lg bg-bg p-3 text-sm text-text-secondary">
            <p className="mb-1"><b className="text-text-primary">% Tamamlandı:</b> {milestoneBased ? "kilometre taşlarının ağırlıklı tamamlanma oranı." : "işin fiziksel ilerleme oranı (elle girilen)."}</p>
            <p className="mb-1"><b className="text-text-primary">% Bütçe Harcandı:</b> gerçekleşen maliyetin revize bütçeye oranı.</p>
            <p><b className="text-text-primary">% Süre Geçti:</b> planlanan takvimin bugüne kadar geçen oranı.</p>
          </div>
          {/* Variance rows render only for indicators that exist (no false figures). */}
          {(health.costGap != null || health.timeGap != null) && (
            <div className="rounded-lg border border-border p-3 text-sm">
              {health.costGap != null && (
                <div className="mb-1 flex justify-between"><span className="text-text-secondary">Maliyet − İlerleme farkı</span>
                  <span className={cn("tabular font-medium", health.costGap > 5 ? "text-danger" : "text-text-primary")}>{health.costGap >= 0 ? "+" : ""}{health.costGap.toFixed(1)} puan</span></div>
              )}
              {health.timeGap != null && (
                <div className="flex justify-between"><span className="text-text-secondary">Süre − İlerleme farkı</span>
                  <span className={cn("tabular font-medium", health.timeGap > 5 ? "text-danger" : "text-text-primary")}>{health.timeGap >= 0 ? "+" : ""}{health.timeGap.toFixed(1)} puan</span></div>
              )}
            </div>
          )}
          <p className="text-sm leading-relaxed text-text-primary">{healthExplanation(health)}</p>
        </div>
      </Modal>

      {/* CR-019-C: Aşamalar & Kilometre Taşları (SCHEDULE lane — never money). */}
      {id && !loading && (
        <MilestonesCard projectId={id} block={data?.milestones} canManage={canManageMilestones} onChanged={refetch} />
      )}

      {/* Maliyet Dağılımı — top cost categories + drill-down modal (CR-018-B). */}
      {id && !loading && <CostBreakdownCard projectId={id} showUsd={showUsd} />}

      {/* CR-015-C: modeled financing cost — a forecast overlay, NOT an actual cost.
          Only rendered when enabled (effective toggle on + a positive accrual). */}
      {financingOn && financing && (
        <div className="mt-4 rounded-xl border border-border bg-surface shadow-sm">
          <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-primary">
              <Coins className="h-4 w-4 text-accent" /> Tahmini Finansman Maliyeti
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-warning">Modellenmiş tahmin — gerçek maliyet değildir</span>
            </span>
            {isDirector && (
              <Button variant="ghost" className="px-2 py-1 text-xs" onClick={openFinEdit}>
                <Pencil className="h-3.5 w-3.5" /> Ayar
              </Button>
            )}
          </div>
          <div className="space-y-3 p-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-sm">
              <FinStat label="Toplam (₺)" value={formatCurrency(financing.total_try)} />
              <FinStat label="Toplam ($)" value={formatUSD(financing.total_usd)} />
              <FinStat label="Yıllık Oran" value={financing.annual_rate_pct != null ? `%${financing.annual_rate_pct}` : "—"} />
              <FinStat label="Baz" value={financing.basis === "net" ? "Aylık net" : "Kümülatif"} />
            </div>

            <p className="text-xs italic text-text-secondary">
              Tahmini — gelecek aylar planlanan nakit akışına dayanır; gerçekleşmelerle değişir.
              Forecast (tahmini) marja işlenir; gerçekleşen maliyet ve gerçek marj değişmez.
            </p>

            {financing.months.length > 0 && (
              <div>
                <button className="flex items-center gap-1 text-xs font-medium text-brand" onClick={() => setFinMonthsOpen((v) => !v)}>
                  <span className="inline-block w-3">{finMonthsOpen ? "▾" : "▸"}</span>
                  Aylık dağılım ({financing.months.length} ay)
                </button>
                {finMonthsOpen && (
                  <div className="mt-2 overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border text-left text-xs text-text-secondary">
                          <th className="py-1.5 pr-3 font-medium">Ay</th>
                          <th className="py-1.5 pr-3 text-right font-medium">Finanse Edilen (₺)</th>
                          <th className="py-1.5 pr-3 text-right font-medium">Kur</th>
                          <th className="py-1.5 pr-3 text-right font-medium">Faiz ($)</th>
                          <th className="py-1.5 text-right font-medium">Faiz (₺)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {financing.months.map((m) => (
                          <tr key={m.month} className="border-b border-border/60">
                            <td className="py-1.5 pr-3">{m.month}</td>
                            <td className="py-1.5 pr-3 text-right tabular">{formatCurrency(m.financed_try)}</td>
                            <td className="py-1.5 pr-3 text-right tabular">{toNumber(m.rate).toLocaleString("tr-TR", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}</td>
                            <td className="py-1.5 pr-3 text-right tabular">{formatUSD(m.interest_usd)}</td>
                            <td className="py-1.5 text-right tabular">{formatCurrency(m.interest_try)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Discoverability: financing is off -> tell the director where to enable it
          (the dashboard card only appears once it's on). */}
      {shouldShowFinancingHint(isDirector, financing) && (
        <div className="mt-4 flex items-center gap-2 rounded-md border border-dashed border-border bg-bg px-4 py-2.5 text-sm text-text-secondary">
          <Coins className="h-4 w-4 shrink-0 text-text-disabled" />
          <span>
            Tahmini finansman maliyeti kapalı.{" "}
            <button onClick={() => navigate("/settings")} className="font-medium text-brand hover:underline">
              Ayarlar → Şirket
            </button>{" "}
            bölümünden açabilirsiniz.
          </span>
        </div>
      )}

      {/* CR-015-C: project-level financing override (director-only) */}
      <Modal open={finEditOpen} title="Proje Finansman Ayarı" onClose={() => setFinEditOpen(false)} size="md">
        <div className="space-y-3">
          <p className="text-xs text-text-secondary">Bu proje için şirket varsayılanını geçersiz kılabilirsiniz.</p>
          <div>
            <label className="text-xs text-text-secondary">Durum</label>
            <select className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm" value={finForm.mode} onChange={(e) => setFinForm((s) => ({ ...s, mode: e.target.value }))}>
              <option value="inherit">Şirket ayarını kullan</option>
              <option value="on">Bu projede aç</option>
              <option value="off">Bu projede kapat</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-text-secondary">Yıllık USD oran % (boş = şirket oranı)</label>
            <input type="number" className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm" value={finForm.rate} onChange={(e) => setFinForm((s) => ({ ...s, rate: e.target.value }))} placeholder="örn. 10" />
          </div>
          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <Button variant="ghost" onClick={() => setFinEditOpen(false)}>İptal</Button>
            <Button loading={finSaving} onClick={saveFinancing}>Kaydet</Button>
          </div>
        </div>
      </Modal>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-stretch">
        <DashboardSection title="S-Eğrisi (Kümülatif Maliyet)">
          <div className="px-4 pb-4">
            {cfError ? (
              <LoadError message="Dönem grafiği yüklenemedi." onRetry={cfRange.refetch} />
            ) : sCurve.length ? (
              <SCurveChart data={sCurve} />
            ) : (
              <EmptyState message="Henüz maliyet verisi yok." />
            )}
          </div>
        </DashboardSection>
        <DashboardSection title="Aylık Nakit Akışı">
          <div className="px-4 pb-4">
            {cfError ? (
              <LoadError message="Dönem grafiği yüklenemedi." onRetry={cfRange.refetch} />
            ) : cashflow.length ? (
              <CashFlowChart data={cashflow} />
            ) : (
              <EmptyState message="Henüz nakit hareketi yok." />
            )}
          </div>
        </DashboardSection>
      </div>

      {/* CR-003-G: Margin Bridge */}
      <DashboardSection className="mt-4" title="Marj Hareketi — Neden Değişti?">
        <div className="px-4 pb-4">{data?.margin_bridge ? <MarginBridgeChart bridge={data.margin_bridge} /> : <EmptyState message="Marj verisi yok." />}</div>
      </DashboardSection>

      {f?.estimated_finish_date && (
        <div className="mt-4 rounded-md bg-amber-50 px-4 py-3 text-sm text-text-primary">
          Mevcut harcama hızına göre tahmini bitiş: <b>{formatDate(f.estimated_finish_date)}</b> (planlanan: {formatDate(p?.planned_end_date)})
        </div>
      )}

      {/* CR-016-C: residential details (İnşaat m² + daire dağılımı) */}
      {isResidential && (
        <div className="mt-4 rounded-xl border border-border bg-surface shadow-sm">
          <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-primary">
              <Building2 className="h-4 w-4 text-brand" /> Konut Detayları
            </span>
            {isDirector && (
              <Button variant="ghost" className="px-2 py-1 text-xs" onClick={openResEdit}>
                <Pencil className="h-3.5 w-3.5" /> Düzenle
              </Button>
            )}
          </div>
          <div className="space-y-4 p-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-sm">
              <ResStat label="İnşaat Brüt m²" value={p?.construction_gross_m2 ? `${toNumber(p.construction_gross_m2).toLocaleString("tr-TR")} m²` : "—"} />
              <ResStat label="İnşaat Net m²" value={p?.construction_net_m2 ? `${toNumber(p.construction_net_m2).toLocaleString("tr-TR")} m²` : "—"} />
              <ResStat label="Toplam Daire" value={String(data?.residential?.total_units ?? 0)} />
              <ResStat label="Tahmini Toplam Satış" value={data?.residential?.total_estimated_sales_try ? formatCurrency(data.residential.total_estimated_sales_try) : "—"} />
            </div>

            {(p?.units?.length ?? 0) > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-text-secondary">
                      <th className="py-1.5 pr-3 font-medium">Daire Tipi</th>
                      <th className="py-1.5 pr-3 text-right font-medium">Adet</th>
                      <th className="py-1.5 pr-3 text-right font-medium">Brüt m²/adet</th>
                      <th className="py-1.5 pr-3 text-right font-medium">Net m²/adet</th>
                      <th className="py-1.5 text-right font-medium">Satış Fiyatı</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p!.units.map((u) => (
                      <tr key={u.id} className="border-b border-border/60">
                        <td className="py-1.5 pr-3">{u.unit_type === "other" ? (u.custom_label || "Diğer") : (UNIT_TYPES[u.unit_type] ?? u.unit_type)}</td>
                        <td className="py-1.5 pr-3 text-right tabular">{u.count}</td>
                        <td className="py-1.5 pr-3 text-right tabular">{toNumber(u.gross_m2_each).toLocaleString("tr-TR")}</td>
                        <td className="py-1.5 pr-3 text-right tabular">{u.net_m2_each ? toNumber(u.net_m2_each).toLocaleString("tr-TR") : "—"}</td>
                        <td className="py-1.5 text-right tabular">{u.sale_price_try ? formatCurrency(u.sale_price_try) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="text-xs font-semibold text-primary">
                      <td className="py-1.5 pr-3">Toplam Satılabilir</td>
                      <td className="py-1.5 pr-3 text-right tabular">{data?.residential?.total_units ?? 0}</td>
                      <td className="py-1.5 pr-3 text-right tabular" colSpan={2}>
                        Brüt {toNumber(data?.residential?.total_sellable_gross_m2).toLocaleString("tr-TR")} m² · Net {toNumber(data?.residential?.total_sellable_net_m2).toLocaleString("tr-TR")} m²
                      </td>
                      <td className="py-1.5 text-right tabular">{data?.residential?.total_estimated_sales_try ? formatCurrency(data.residential.total_estimated_sales_try) : "—"}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            ) : (
              <p className="text-sm text-text-secondary">
                Henüz daire dağılımı girilmemiş.{isDirector ? " “Düzenle” ile ekleyebilirsiniz." : ""}
              </p>
            )}
          </div>
        </div>
      )}

      <Modal open={resEdit} title="Konut Detaylarını Düzenle" onClose={() => setResEdit(false)} size="lg">
        <div className="space-y-4">
          <ResidentialDetailsEditor
            grossM2={resGross}
            netM2={resNet}
            units={resUnits}
            onGrossChange={setResGross}
            onNetChange={setResNet}
            onUnitsChange={setResUnits}
          />
          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <Button variant="ghost" onClick={() => setResEdit(false)}>İptal</Button>
            <Button loading={resSaving} onClick={saveResidential}>Kaydet</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function ResStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-text-secondary">{label}</div>
      <div className="font-semibold text-primary">{value}</div>
    </div>
  );
}

// CR: compact stat for the Dönem Özeti card (TRY + optional USD + entry count).
function PeriodStat({ label, try_, usd, showUsd, count, loading, negative }: {
  label: string; try_?: string; usd?: string; showUsd?: boolean; count?: number; loading?: boolean; negative?: boolean;
}) {
  return (
    <div>
      <div className="text-[11px] text-text-secondary">{label}</div>
      <div className={cn("font-semibold tabular", negative ? "text-danger" : "text-primary")}>
        {loading ? "…" : formatCurrency(try_)}
      </div>
      {showUsd && !loading && usd != null && <div className="text-[11px] tabular text-text-secondary">{formatUSD(usd)}</div>}
      {count != null && !loading && <div className="text-[10px] text-text-disabled">{count} kayıt</div>}
    </div>
  );
}

// CR-015-C: compact stat for the financing card.
function FinStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-text-secondary">{label}</div>
      <div className="font-semibold text-primary">{value}</div>
    </div>
  );
}

// A condensed "story" table: each row is a clickable (keyboard-accessible) metric
// opening the KpiDetailModal. money mode → ₺/USD/% (proportion); percent mode →
// the % value itself (₺/USD shown as "—").
function MetricTable({ title, rows, mode, showUsd, onRowClick, headerExtra }: {
  title: string;
  rows: MetricRowDef[];
  mode: "money" | "percent";
  showUsd: boolean;
  onRowClick: (kpi: KpiInfo) => void;
  headerExtra?: React.ReactNode;
}) {
  const alertCls = (a?: "amber" | "red" | null) => (a === "red" ? "text-danger" : a === "amber" ? "text-warning" : "");
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <h2 className="text-sm font-semibold text-primary">{title}</h2>
        {headerExtra}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-secondary">
              <th className="px-4 py-1.5 font-medium">Metrik</th>
              <th className="px-2 py-1.5 text-right font-medium">Tutar (₺)</th>
              {showUsd && <th className="px-2 py-1.5 text-right font-medium">USD</th>}
              <th className="px-2 py-1.5 text-right font-medium">%</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              // null pct = no valid denominator → show "—" + an empty bar.
              const barW = r.pct == null ? 0 : Math.max(0, Math.min(100, r.pct));
              const onActivate = () => onRowClick(r.kpi);
              return (
                <tr
                  key={r.label}
                  role="button"
                  tabIndex={0}
                  onClick={onActivate}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(); } }}
                  title="Detayını aç"
                  className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-navy-50 focus:bg-navy-50 focus:outline-none"
                >
                  <td className="px-4 py-2 font-medium text-text-primary">{r.label}</td>
                  <td className={cn("px-2 py-2 text-right tabular", mode === "money" && alertCls(r.alert))}>
                    {mode === "percent" ? "—" : (r.tryValue != null ? formatCurrency(r.tryValue) : "—")}
                  </td>
                  {showUsd && (
                    <td className="px-2 py-2 text-right tabular text-text-secondary">
                      {mode === "percent" ? "—" : formatUSD(r.usdValue ?? undefined)}
                    </td>
                  )}
                  <td className="px-2 py-2">
                    <div className="flex items-center justify-end gap-2">
                      <div className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-bg sm:block">
                        <div className="h-full rounded-full bg-brand" style={{ width: `${barW}%` }} />
                      </div>
                      <span className={cn("tabular w-14 text-right", mode === "percent" ? alertCls(r.alert) || "text-text-primary" : "text-text-secondary")}>
                        {r.pct == null ? "—" : formatPct(r.pct)}
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// One labeled progress bar for the Proje Sağlığı card/modal. A null pct means the
// value can't be computed (no budget / no dates / no progress data) → show "—" and
// a neutral note instead of a confident "%0,0".
function HealthBar({ label, pct, color, emptyNote }: { label: string; pct: number | null; color: string; emptyNote?: string }) {
  if (pct == null) {
    return (
      <div>
        <div className="mb-1 flex items-center justify-between text-xs">
          <span className="text-text-secondary">{label}</span>
          <span className="tabular font-medium text-text-disabled">—</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-bg" />
        {emptyNote && <p className="mt-0.5 text-[10px] italic text-text-disabled">{emptyNote}</p>}
      </div>
    );
  }
  const w = Math.max(0, Math.min(100, pct));
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className="tabular font-medium text-text-primary">{formatPct(pct)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-bg">
        <div className="h-full rounded-full" style={{ width: `${w}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

// Proje Sağlığı — clickable on-track card (opens the detail modal).
function ProjectHealthCard({ health, milestoneBased, onOpen }: { health: ProjectHealth; milestoneBased?: boolean; onOpen: () => void }) {
  const meta = HEALTH_SIGNAL_META[health.signal];
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } }}
      className="group mt-4 cursor-pointer rounded-xl border border-border bg-surface shadow-sm transition-colors hover:border-brand focus:border-brand focus:outline-none"
    >
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <span className="flex items-center gap-1.5 text-sm font-semibold text-primary">
          <Activity className="h-4 w-4 text-brand" /> Proje Sağlığı
        </span>
        <div className="flex items-center gap-2">
          <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium", meta.bg)}>
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: meta.color }} /> {meta.label}
          </span>
          <span className="hidden items-center text-[11px] font-medium text-brand opacity-0 transition-opacity group-hover:opacity-100 sm:inline-flex">Detay <ChevronRight className="h-3.5 w-3.5" /></span>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-3">
        <HealthBar label={milestoneBased ? "% Tamamlandı (kilometre taşı)" : "% Tamamlandı"} pct={health.completionKnown ? health.completionPct : null} color="#2563EB" emptyNote="Yeterli veri yok" />
        <HealthBar label="% Bütçe Harcandı" pct={health.costPct} color={meta.color} emptyNote="Bütçe girilmemiş" />
        <HealthBar label="% Süre Geçti" pct={health.timePct} color="#64748B" emptyNote="Tarih girilmemiş" />
      </div>
      <p className="px-4 pb-1 text-xs leading-snug text-text-secondary">{healthExplanation(health)}</p>
      {milestoneBased && <p className="px-4 pb-3 text-[11px] italic text-text-disabled">İlerleme kilometre taşlarından hesaplanır.</p>}
    </div>
  );
}

// CR-018-B rollups for the cost-breakdown section.
interface SubRollup { subcategory: string; amount_try: string; total_with_vat_try: string }
interface CatRollup { cost_category: string; label_tr: string; amount_try: string; total_with_vat_try: string; subcategories: SubRollup[] }

// Maliyet Dağılımı — top cost categories (share of total) + a drill-down modal
// with the full category → subcategory breakdown. Uses the existing CR-018-B
// endpoint; USD isn't returned per-category so it shows "—".
function CostBreakdownCard({ projectId, showUsd }: { projectId: string; showUsd: boolean }) {
  const { data, loading, error, refetch } = useFetch<{ categories: CatRollup[] }>(`/projects/${projectId}/costs/by-subcategory`);
  const [open, setOpen] = useState(false);
  const cats = data?.categories ?? [];
  const total = cats.reduce((s, c) => s + toNumber(c.total_with_vat_try), 0);
  const sorted = [...cats].sort((a, b) => toNumber(b.total_with_vat_try) - toNumber(a.total_with_vat_try));
  const top = sorted.slice(0, 5);
  const share = (v?: string) => (total > 0 ? (toNumber(v) / total) * 100 : 0);

  if (loading) {
    return (
      <div className="mt-4 rounded-xl border border-border bg-surface p-4 shadow-sm">
        <Skeleton className="mb-3 h-4 w-32" />
        {[0, 1, 2].map((i) => <Skeleton key={i} className="mb-2 h-5 w-full" />)}
      </div>
    );
  }
  if (error) {
    return (
      <div className="mt-4 rounded-xl border border-border bg-surface shadow-sm">
        <LoadError message="Maliyet dağılımı yüklenemedi." onRetry={refetch} />
      </div>
    );
  }
  if (cats.length === 0) return null;

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(true)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(true); } }}
        className="group mt-4 cursor-pointer rounded-xl border border-border bg-surface shadow-sm transition-colors hover:border-brand focus:border-brand focus:outline-none"
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <span className="flex items-center gap-1.5 text-sm font-semibold text-primary">
            <PieChart className="h-4 w-4 text-brand" /> Maliyet Dağılımı
          </span>
          <span className="hidden items-center text-[11px] font-medium text-brand opacity-0 transition-opacity group-hover:opacity-100 sm:inline-flex">Tüm dağılım <ChevronRight className="h-3.5 w-3.5" /></span>
        </div>
        <div className="space-y-2.5 p-4">
          {top.map((c) => {
            const pct = share(c.total_with_vat_try);
            return (
              <div key={c.cost_category}>
                <div className="mb-1 flex items-center justify-between gap-2 text-sm">
                  <span className="min-w-0 truncate text-text-primary" title={c.label_tr}>{c.label_tr}</span>
                  <span className="shrink-0 text-text-secondary">
                    <span className="tabular font-medium text-text-primary">{formatCurrency(c.total_with_vat_try)}</span>
                    <span className="tabular ml-2 text-xs">{formatPct(pct)}</span>
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-bg">
                  <div className="h-full rounded-full bg-brand" style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <Modal open={open} title="Maliyet Dağılımı" onClose={() => setOpen(false)} size="lg">
        <div className="space-y-4">
          <p className="text-xs text-text-secondary">Kategori ve alt kategori bazında toplam maliyet (KDV dahil). Yüzdeler toplam maliyete oranı gösterir.</p>
          {sorted.map((c) => (
            <div key={c.cost_category} className="rounded-lg border border-border">
              <div className="flex items-center justify-between gap-2 border-b border-border bg-bg px-3 py-2">
                <span className="font-medium text-primary">{c.label_tr}</span>
                <span className="tabular text-sm font-semibold text-primary">{formatCurrency(c.total_with_vat_try)} · {formatPct(share(c.total_with_vat_try))}</span>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-left text-[11px] uppercase tracking-wide text-text-secondary">
                    <th className="px-3 py-1.5 font-medium">Alt Kategori</th>
                    <th className="px-2 py-1.5 text-right font-medium">Tutar (₺)</th>
                    {showUsd && <th className="px-2 py-1.5 text-right font-medium">USD</th>}
                    <th className="px-2 py-1.5 text-right font-medium">%</th>
                  </tr>
                </thead>
                <tbody>
                  {c.subcategories.map((s) => (
                    <tr key={s.subcategory} className="border-b border-border/40 last:border-0">
                      <td className="px-3 py-1.5 text-text-primary">{s.subcategory}</td>
                      <td className="px-2 py-1.5 text-right tabular">{formatCurrency(s.total_with_vat_try)}</td>
                      {showUsd && <td className="px-2 py-1.5 text-right tabular text-text-secondary">—</td>}
                      <td className="px-2 py-1.5 text-right tabular text-text-secondary">{formatPct(share(s.total_with_vat_try))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </Modal>
    </>
  );
}
