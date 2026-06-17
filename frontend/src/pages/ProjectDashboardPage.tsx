import { CashFlowChart, MarginBridgeChart, SCurveChart } from "@/components/charts";
import { AIDisclaimer, Button, Modal } from "@/components/ui";
import { CostEntriesDrawer } from "@/components/dashboard/CostEntriesDrawer";
import { DashboardSection } from "@/components/dashboard/DashboardSection";
import { KpiDetailModal, type KpiInfo } from "@/components/dashboard/KpiDetailModal";
import { CurrencyToggle, UsdMissingNote, useShowUsd } from "@/components/currency";
import { EmptyState, LoadError } from "@/components/EmptyState";
import { KPICard } from "@/components/KPICard";
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
import { formatCurrency, formatCurrencyAbbrev, formatDate, formatDateTime, formatPct, formatUSD, toNumber } from "@/utils/format";
import { shouldShowFinancingHint } from "@/utils/financing";
import { dashRangeParams, type DashPreset } from "@/utils/dashboardRange";
import { cn } from "@/lib/cn";
import { Banknote, Building2, Clock, Coins, FileText, Hammer, Layers, Pencil, Percent, RefreshCw, Sparkles, Target, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

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
  const { data, loading, error, refetch } = useFetch<{ project: Project; financials: ProjectFinancials; cashflow: any[]; forecast_at_completion: FAC; margin_bridge: Record<string, string>; usd?: UsdBlock; residential?: ResidentialAggregates; financing?: FinancingBlock }>(
    `/projects/${id}/dashboard`
  );
  const showUsd = useShowUsd(); // CR-014-D
  const p = data?.project;
  const f = data?.financials;
  const fac = data?.forecast_at_completion;

  // CR-016-C: residential details (m² + daire dağılımı). Visible for residential
  // project types or any project that already carries a schedule / construction m².
  const isDirector = useAuth((s) => s.user?.role === "director");
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

  const facMargin = toNumber(fac?.forecast_final_margin_pct);

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

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KPICard loading={loading} label="Sözleşme Değeri" value={formatCurrencyAbbrev(f?.contract_value_try)} valueTitle={formatCurrency(f?.contract_value_try)} icon={Wallet} accentColor="#2563EB"
          onClick={() => setKpiDetail({
            title: "Sözleşme Değeri", value: formatCurrency(f?.contract_value_try), accentColor: "#2563EB",
            description: "Proje sözleşme bedeli — işverenle anlaşılan toplam gelir (KDV hariç).",
          })} />
        <KPICard loading={loading} label="Gerçekleşen Maliyet" value={formatCurrencyAbbrev(f?.total_actual_with_vat_try)} valueTitle={formatCurrency(f?.total_actual_with_vat_try)} icon={Hammer} accentColor="#F59E0B" alert={actualVsBudget > 0.8 ? "amber" : null}
          onClick={() => setKpiDetail({
            title: "Gerçekleşen Maliyet", value: formatCurrency(f?.total_actual_with_vat_try), accentColor: "#F59E0B",
            description: "Bu projede bugüne kadar gerçekleşen toplam maliyet (KDV dahil). Revize bütçenin %80'ini aşınca uyarı verir.",
            action: { label: "Maliyet kayıtlarını gör", onClick: () => setCostDrawer(true) },
          })} />
        <KPICard loading={loading} label="Kalan Bütçe" value={formatCurrencyAbbrev(f?.remaining_budget_try)} valueTitle={formatCurrency(f?.remaining_budget_try)} icon={Coins} accentColor="#06B6D4" alert={remaining < 0 ? "red" : null}
          onClick={() => setKpiDetail({
            title: "Kalan Bütçe", value: formatCurrency(f?.remaining_budget_try), accentColor: "#06B6D4",
            description: "Revize bütçeden bugüne kadar harcanan tutar düşüldükten sonra kalan bakiye. Negatif değer bütçe aşımını gösterir.",
            action: { label: "Bütçeye git", onClick: () => navigate(`/projects/${id}/budget`) },
          })} />
        <KPICard loading={loading} label="Güncel Kar Marjı" value={formatPct(f?.margin_pct)} icon={Percent} accentColor="#059669" alert={margin < 5 ? "red" : margin < 10 ? "amber" : null}
          onClick={() => setKpiDetail({
            title: "Güncel Kar Marjı", value: formatPct(f?.margin_pct), valueKind: "percent", accentColor: "#059669",
            description: "Sözleşme bedeline göre güncel (gerçekleşen) kar marjı. %10 altında izlenmeli, %5 altında riskli kabul edilir.",
          })} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KPICard loading={loading} label="İşverene Faturalanan" value={formatCurrencyAbbrev(f?.total_invoiced_try)} valueTitle={formatCurrency(f?.total_invoiced_try)} icon={FileText} accentColor="#2563EB"
          onClick={() => setKpiDetail({
            title: "İşverene Faturalanan", value: formatCurrency(f?.total_invoiced_try), accentColor: "#2563EB",
            description: "İşverene kesilen hakediş ve faturaların toplam tutarı.",
            action: { label: "Faturalara git", onClick: () => navigate(`/projects/${id}/invoices`) },
          })} />
        <KPICard loading={loading} label="Tahsil Edilen" value={formatCurrencyAbbrev(f?.total_collected_try)} valueTitle={formatCurrency(f?.total_collected_try)} icon={Banknote} accentColor="#059669"
          onClick={() => setKpiDetail({
            title: "Tahsil Edilen", value: formatCurrency(f?.total_collected_try), accentColor: "#059669",
            description: "İşverenden bugüne kadar tahsil edilen toplam tutar.",
            action: { label: "Faturalara git", onClick: () => navigate(`/projects/${id}/invoices`) },
          })} />
        <KPICard loading={loading} label="Bekleyen Tahsilat" value={formatCurrencyAbbrev(f?.total_outstanding_try)} valueTitle={formatCurrency(f?.total_outstanding_try)} icon={Clock} accentColor="#D97706"
          onClick={() => setKpiDetail({
            title: "Bekleyen Tahsilat", value: formatCurrency(f?.total_outstanding_try), accentColor: "#D97706",
            description: "Faturalanan ancak henüz tahsil edilmemiş tutar — açık alacaklar.",
            action: { label: "Faturalara git", onClick: () => navigate(`/projects/${id}/invoices`) },
          })} />
        <KPICard loading={loading} label="Hakediş Kesintisi" value={formatCurrencyAbbrev(f?.total_retention_try)} valueTitle={formatCurrency(f?.total_retention_try)} icon={Layers} accentColor="#0E1525"
          onClick={() => setKpiDetail({
            title: "Hakediş Kesintisi", value: formatCurrency(f?.total_retention_try), accentColor: "#0E1525",
            description: "Hakedişlerden kesilen teminat (stopaj/teminat) toplamı.",
            action: { label: "Faturalara git", onClick: () => navigate(`/projects/${id}/invoices`) },
          })} />
      </div>

      {id && <CostEntriesDrawer open={costDrawer} onClose={() => setCostDrawer(false)} projectId={id} highlightId={highlightCostId} />}
      <KpiDetailModal open={!!kpiDetail} onClose={() => setKpiDetail(null)} kpi={kpiDetail} />

      {/* CR-003-F: Forecast-at-Completion */}
      <div className="mt-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-primary">Tamamlanmada Tahmin</h2>
          {financingOn && (
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-text-secondary">
              <input type="checkbox" className="h-3.5 w-3.5 accent-[var(--color-primary)]" checked={includeFinancing} onChange={(e) => setIncludeFinancing(e.target.checked)} />
              Tahmini finansman maliyetini marja dahil et
            </label>
          )}
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
          <KPICard loading={loading} label="Orijinal Bütçe" value={formatCurrencyAbbrev(fac?.original_budget_try)} valueTitle={formatCurrency(fac?.original_budget_try)} icon={Target} accentColor="#2563EB"
            onClick={() => setKpiDetail({
              title: "Orijinal Bütçe", value: formatCurrency(fac?.original_budget_try), accentColor: "#2563EB",
              description: "Projenin başlangıçtaki onaylı bütçesi (ek işler hariç).",
            })} />
          <KPICard loading={loading} label="Revize Bütçe" value={formatCurrencyAbbrev(fac?.revised_budget_try)} valueTitle={formatCurrency(fac?.revised_budget_try)} icon={Layers} accentColor="#06B6D4"
            onClick={() => setKpiDetail({
              title: "Revize Bütçe", value: formatCurrency(fac?.revised_budget_try), accentColor: "#06B6D4",
              description: "Onaylı ek işler eklendikten sonraki güncel bütçe.",
            })} />
          <KPICard loading={loading} label="Bugüne Kadar Maliyet" value={formatCurrencyAbbrev(fac?.cost_to_date_try)} valueTitle={formatCurrency(fac?.cost_to_date_try)} icon={Hammer} accentColor="#F59E0B"
            onClick={() => setKpiDetail({
              title: "Bugüne Kadar Maliyet", value: formatCurrency(fac?.cost_to_date_try), accentColor: "#F59E0B",
              description: "Bugüne kadar bu projede gerçekleşen toplam maliyet.",
            })} />
          <KPICard loading={loading} label="Tamamlamaya Kalan Maliyet" value={formatCurrencyAbbrev(fac?.cost_to_complete_try)} valueTitle={formatCurrency(fac?.cost_to_complete_try)} icon={Hammer} accentColor="#D97706" alert={toNumber(fac?.cost_to_complete_try) > toNumber(fac?.revised_budget_try) ? "amber" : null}
            onClick={() => setKpiDetail({
              title: "Tamamlamaya Kalan Maliyet", value: formatCurrency(fac?.cost_to_complete_try), accentColor: "#D97706",
              description: "İşi tamamlamak için gereken tahmini kalan maliyet (tahmini final maliyet eksi bugüne kadar gerçekleşen).",
            })} />
          <KPICard loading={loading} label="Tahmini Final Maliyet" value={formatCurrencyAbbrev(fac?.forecast_final_cost_try)} valueTitle={formatCurrency(fac?.forecast_final_cost_try)} icon={Target} accentColor="#7C3AED" alert={fac?.over_budget ? "red" : null}
            onClick={() => setKpiDetail({
              title: "Tahmini Final Maliyet", value: formatCurrency(fac?.forecast_final_cost_try), accentColor: "#7C3AED",
              description: "Mevcut gidişata göre projenin tahmini toplam final maliyeti. Revize bütçeyi aşarsa kırmızı uyarı verir.",
            })} />
          <KPICard loading={loading} label={financingOn && includeFinancing ? "Tahmini Final Marj (finansman dahil)" : "Tahmini Final Marj"} value={formatPct(shownForecastMargin)} icon={Percent} accentColor="#059669" alert={toNumber(shownForecastMargin) < 5 ? "red" : toNumber(shownForecastMargin) < 10 ? "amber" : null}
            onClick={() => setKpiDetail({
              title: "Tahmini Final Marj", value: formatPct(shownForecastMargin), valueKind: "percent", accentColor: "#059669",
              description: financingOn && includeFinancing
                ? "Tahmini finansman maliyeti DAHİL beklenen kar marjı (modellenmiş tahmin — gerçek maliyet değildir). Üstteki kutudan hariç tutabilirsiniz."
                : "Tahmini final maliyete göre beklenen kar marjı. %10 altında izlenmeli, %5 altında riskli.",
            })} />
        </div>
      </div>

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
          <div className="px-4 pb-4">{sCurve.length ? <SCurveChart data={sCurve} /> : <EmptyState message="Henüz maliyet verisi yok." />}</div>
        </DashboardSection>
        <DashboardSection title="Aylık Nakit Akışı">
          <div className="px-4 pb-4">{cashflow.length ? <CashFlowChart data={cashflow} /> : <EmptyState message="Henüz nakit hareketi yok." />}</div>
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
