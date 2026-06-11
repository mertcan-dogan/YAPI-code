import { CashFlowChart, MarginBridgeChart, SCurveChart } from "@/components/charts";
import { AIDisclaimer, Button, Card, CardBody } from "@/components/ui";
import { CostEntriesDrawer } from "@/components/dashboard/CostEntriesDrawer";
import { EmptyState } from "@/components/EmptyState";
import { KPICard } from "@/components/KPICard";
import { PageHeader } from "@/components/layout/AppLayout";
import { RAGIndicator } from "@/components/RAGIndicator";
import { useFetch } from "@/hooks/useFetch";
import { apiPost } from "@/lib/api";
import { useAISummaryStore } from "@/store/aiSummary";
import type { ProjectFinancials, Project } from "@/types";
import { formatCurrency, formatDate, formatDateTime, formatPct, toNumber } from "@/utils/format";
import { RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

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
  const { data, loading } = useFetch<{ project: Project; financials: ProjectFinancials; cashflow: any[]; forecast_at_completion: FAC; margin_bridge: Record<string, string> }>(
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

  return (
    <div>
      <PageHeader
        title={p?.name ?? "Proje Özeti"}
        subtitle={p ? `${p.client_name} · ${p.project_code}` : undefined}
        action={f && <RAGIndicator status={f.rag_status} label={f.rag_label_tr} reason={f.rag_reason_tr} />}
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KPICard loading={loading} label="Sözleşme Değeri" value={formatCurrency(f?.contract_value_try)} />
        <KPICard loading={loading} label="Gerçekleşen Maliyet" value={formatCurrency(f?.total_actual_with_vat_try)} alert={actualVsBudget > 0.8 ? "amber" : null} onClick={() => setCostDrawer(true)} />
        <KPICard loading={loading} label="Kalan Bütçe" value={formatCurrency(f?.remaining_budget_try)} alert={remaining < 0 ? "red" : null} onClick={() => navigate(`/projects/${id}/budget`)} />
        <KPICard loading={loading} label="Güncel Kar Marjı" value={formatPct(f?.margin_pct)} alert={margin < 5 ? "red" : margin < 10 ? "amber" : null} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KPICard loading={loading} label="İşverene Faturalanan" value={formatCurrency(f?.total_invoiced_try)} onClick={() => navigate(`/projects/${id}/invoices`)} />
        <KPICard loading={loading} label="Tahsil Edilen" value={formatCurrency(f?.total_collected_try)} onClick={() => navigate(`/projects/${id}/invoices`)} />
        <KPICard loading={loading} label="Bekleyen Tahsilat" value={formatCurrency(f?.total_outstanding_try)} onClick={() => navigate(`/projects/${id}/invoices`)} />
        <KPICard loading={loading} label="Hakediş Kesintisi" value={formatCurrency(f?.total_retention_try)} onClick={() => navigate(`/projects/${id}/invoices`)} />
      </div>

      {id && <CostEntriesDrawer open={costDrawer} onClose={() => setCostDrawer(false)} projectId={id} />}

      {/* CR-003-F: Forecast-at-Completion */}
      <div className="mt-8">
        <h2 className="mb-3 text-lg font-semibold text-primary">Tamamlanmada Tahmin</h2>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
          <KPICard loading={loading} label="Orijinal Bütçe" value={formatCurrency(fac?.original_budget_try)} />
          <KPICard loading={loading} label="Revize Bütçe" value={formatCurrency(fac?.revised_budget_try)} />
          <KPICard loading={loading} label="Bugüne Kadar Maliyet" value={formatCurrency(fac?.cost_to_date_try)} />
          <KPICard loading={loading} label="Tamamlamaya Kalan Maliyet" value={formatCurrency(fac?.cost_to_complete_try)} alert={toNumber(fac?.cost_to_complete_try) > toNumber(fac?.revised_budget_try) ? "amber" : null} />
          <KPICard loading={loading} label="Tahmini Final Maliyet" value={formatCurrency(fac?.forecast_final_cost_try)} alert={fac?.over_budget ? "red" : null} />
          <KPICard loading={loading} label="Tahmini Final Marj" value={formatPct(fac?.forecast_final_margin_pct)} alert={facMargin < 5 ? "red" : facMargin < 10 ? "amber" : null} />
        </div>

        <Card className="mt-4">
          <CardBody>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-primary"><Sparkles className="h-4 w-4 text-accent" /> AI Proje Özeti</h3>
              <div className="flex items-center gap-2">
                {narrCachedAt && (
                  <span className="text-[11px] italic text-text-secondary">Son güncelleme: {formatDateTime(narrCachedAt)}</span>
                )}
                <Button variant="ghost" className="px-2 py-1 text-xs" loading={narrLoading} onClick={refreshNarrative}>
                  <RefreshCw className="h-3.5 w-3.5" /> Yenile
                </Button>
              </div>
            </div>
            <p className="text-sm text-text-primary">{narrative?.narrative ?? (narrLoading ? "AI özeti hazırlanıyor…" : "Özet bulunamadı.")}</p>
            {!narrLoading && narrative?.narrative && <AIDisclaimer />}
          </CardBody>
        </Card>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 text-lg font-semibold text-primary">S-Eğrisi (Kümülatif Maliyet)</h2>
          <Card><CardBody>{sCurve.length ? <SCurveChart data={sCurve} /> : <EmptyState message="Henüz maliyet verisi yok." />}</CardBody></Card>
        </div>
        <div>
          <h2 className="mb-3 text-lg font-semibold text-primary">Aylık Nakit Akışı</h2>
          <Card><CardBody>{cashflow.length ? <CashFlowChart data={cashflow} /> : <EmptyState message="Henüz nakit hareketi yok." />}</CardBody></Card>
        </div>
      </div>

      {/* CR-003-G: Margin Bridge */}
      <div className="mt-6">
        <h2 className="mb-3 text-lg font-semibold text-primary">Marj Hareketi — Neden Değişti?</h2>
        <Card>
          <CardBody>
            {data?.margin_bridge ? <MarginBridgeChart bridge={data.margin_bridge} /> : <EmptyState message="Marj verisi yok." />}
          </CardBody>
        </Card>
      </div>

      {f?.estimated_finish_date && (
        <div className="mt-4 rounded-md bg-amber-50 px-4 py-3 text-sm text-text-primary">
          Mevcut harcama hızına göre tahmini bitiş: <b>{formatDate(f.estimated_finish_date)}</b> (planlanan: {formatDate(p?.planned_end_date)})
        </div>
      )}
    </div>
  );
}
