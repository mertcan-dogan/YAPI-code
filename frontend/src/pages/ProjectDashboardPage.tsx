import { CashFlowChart, SCurveChart } from "@/components/charts";
import { Card, CardBody } from "@/components/ui";
import { EmptyState } from "@/components/EmptyState";
import { KPICard } from "@/components/KPICard";
import { PageHeader } from "@/components/layout/AppLayout";
import { RAGIndicator } from "@/components/RAGIndicator";
import { useFetch } from "@/hooks/useFetch";
import type { ProjectFinancials, Project } from "@/types";
import { formatCurrency, formatDate, formatPct, toNumber } from "@/utils/format";
import { useParams } from "react-router-dom";

export default function ProjectDashboardPage() {
  const { id } = useParams();
  const { data, loading } = useFetch<{ project: Project; financials: ProjectFinancials; cashflow: any[] }>(
    `/projects/${id}/dashboard`
  );
  const p = data?.project;
  const f = data?.financials;

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
        <KPICard loading={loading} label="Gerçekleşen Maliyet" value={formatCurrency(f?.total_actual_with_vat_try)} alert={actualVsBudget > 0.8 ? "amber" : null} />
        <KPICard loading={loading} label="Kalan Bütçe" value={formatCurrency(f?.remaining_budget_try)} alert={remaining < 0 ? "red" : null} />
        <KPICard loading={loading} label="Güncel Kar Marjı" value={formatPct(f?.margin_pct)} alert={margin < 5 ? "red" : margin < 10 ? "amber" : null} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KPICard loading={loading} label="İşverene Faturalanan" value={formatCurrency(f?.total_invoiced_try)} />
        <KPICard loading={loading} label="Tahsil Edilen" value={formatCurrency(f?.total_collected_try)} />
        <KPICard loading={loading} label="Bekleyen Tahsilat" value={formatCurrency(f?.total_outstanding_try)} />
        <KPICard loading={loading} label="Hakediş Kesintisi" value={formatCurrency(f?.total_retention_try)} />
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

      {f?.estimated_finish_date && (
        <div className="mt-4 rounded-md bg-amber-50 px-4 py-3 text-sm text-text-primary">
          Mevcut harcama hızına göre tahmini bitiş: <b>{formatDate(f.estimated_finish_date)}</b> (planlanan: {formatDate(p?.planned_end_date)})
        </div>
      )}
    </div>
  );
}
