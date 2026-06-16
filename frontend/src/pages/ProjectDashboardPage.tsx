import { CashFlowChart, MarginBridgeChart, SCurveChart } from "@/components/charts";
import { AIDisclaimer, Button, Modal } from "@/components/ui";
import { CostEntriesDrawer } from "@/components/dashboard/CostEntriesDrawer";
import { DashboardSection } from "@/components/dashboard/DashboardSection";
import { KpiDetailModal, type KpiInfo } from "@/components/dashboard/KpiDetailModal";
import { EmptyState, LoadError } from "@/components/EmptyState";
import { KPICard } from "@/components/KPICard";
import { PageHeader } from "@/components/layout/AppLayout";
import { RAGIndicator } from "@/components/RAGIndicator";
import { useFetch } from "@/hooks/useFetch";
import { apiPost } from "@/lib/api";
import { useAISummaryStore } from "@/store/aiSummary";
import type { ProjectFinancials, Project } from "@/types";
import { formatCurrency, formatCurrencyAbbrev, formatDate, formatDateTime, formatPct, toNumber } from "@/utils/format";
import { Banknote, Clock, Coins, FileText, Hammer, Layers, Percent, RefreshCw, Sparkles, Target, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

interface FAC {
  original_budget_try: string;
  revised_budget_try: string;
  cost_to_date_try: string;
  cost_to_complete_try: string;
  forecast_final_cost_try: string;
  forecast_final_margin_pct: string;
  over_budget: boolean;
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
  const { data, loading, error, refetch } = useFetch<{ project: Project; financials: ProjectFinancials; cashflow: any[]; forecast_at_completion: FAC; margin_bridge: Record<string, string> }>(
    `/projects/${id}/dashboard`
  );
  const p = data?.project;
  const f = data?.financials;
  const fac = data?.forecast_at_completion;

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

  // Build S-curve + monthly cashflow series from the returned rolling window.
  const cf = data?.cashflow ?? [];
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
        <h2 className="mb-3 text-sm font-semibold text-primary">Tamamlanmada Tahmin</h2>
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
          <KPICard loading={loading} label="Tahmini Final Marj" value={formatPct(fac?.forecast_final_margin_pct)} icon={Percent} accentColor="#059669" alert={facMargin < 5 ? "red" : facMargin < 10 ? "amber" : null}
            onClick={() => setKpiDetail({
              title: "Tahmini Final Marj", value: formatPct(fac?.forecast_final_margin_pct), valueKind: "percent", accentColor: "#059669",
              description: "Tahmini final maliyete göre beklenen kar marjı. %10 altında izlenmeli, %5 altında riskli.",
            })} />
        </div>
      </div>

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
    </div>
  );
}
