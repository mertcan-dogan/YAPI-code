import { CashFlowChart } from "@/components/charts";
import { Card, CardBody } from "@/components/ui";
import { LoadError } from "@/components/EmptyState";
import { CashFlowMonthDrawer } from "@/components/cashflow/CashFlowMonthDrawer";
import { PageHeader } from "@/components/layout/AppLayout";
import { cn } from "@/lib/cn";
import { useFetch } from "@/hooks/useFetch";
import { formatCurrency, toNumber } from "@/utils/format";
import { useState } from "react";
import { useParams } from "react-router-dom";

interface RiskWindow {
  days: number;
  planned_out_try: string;
  expected_in_try: string;
  net_need_try: string;
  shortfall: boolean;
}

type Row = {
  month: string;
  planned_out_try: string;
  actual_out_try: string;
  planned_in_try: string;
  actual_in_try: string;
  net_try: string;
  cumulative_try: string;
  is_past: boolean;
  is_current: boolean;
};

export default function CashFlowPage() {
  const { id } = useParams();
  const { data, loading, error, refetch } = useFetch<Row[]>(`/projects/${id}/cashflow`);
  const { data: risk } = useFetch<RiskWindow[]>(`/projects/${id}/cashflow/risk`);
  const [view, setView] = useState<"both" | "planned" | "actual">("both");
  const [monthDetail, setMonthDetail] = useState<string | null>(null);
  const rows = data ?? [];

  const chart = rows.map((r) => {
    const inV = r.is_past || r.is_current ? toNumber(r.actual_in_try) : toNumber(r.planned_in_try);
    const outV = r.is_past || r.is_current ? toNumber(r.actual_out_try) : toNumber(r.planned_out_try);
    return { month: r.month, in: inV, out: outV, cumulative: toNumber(r.cumulative_try) };
  });

  const showOut = (r: Row) => (view === "planned" ? r.planned_out_try : view === "actual" ? r.actual_out_try : r.is_past || r.is_current ? r.actual_out_try : r.planned_out_try);
  const showIn = (r: Row) => (view === "planned" ? r.planned_in_try : view === "actual" ? r.actual_in_try : r.is_past || r.is_current ? r.actual_in_try : r.planned_in_try);

  return (
    <div>
      <PageHeader
        title="Nakit Akışı"
        action={
          <div className="flex gap-1 rounded-md border border-border p-0.5">
            {(["both", "planned", "actual"] as const).map((v) => (
              <button key={v} onClick={() => setView(v)} className={cn("rounded px-3 py-1 text-sm", view === v ? "bg-primary text-white" : "text-text-secondary")}>
                {v === "both" ? "İkisi de" : v === "planned" ? "Planlanan" : "Gerçekleşen"}
              </button>
            ))}
          </div>
        }
      />
      {/* CR-004-M: 30/60/90-day cash-need cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {(risk ?? []).map((w) => {
          const need = toNumber(w.net_need_try);
          const colour = w.shortfall ? "text-danger" : "text-success";
          return (
            <Card key={w.days} className={cn("border-l-4", w.shortfall ? "border-l-danger" : "border-l-success")}>
              <CardBody>
                <div className="text-xs text-text-secondary">{w.days} Gün Nakit İhtiyacı</div>
                <div className={cn("tabular mt-1 text-2xl font-bold", colour)}>{formatCurrency(Math.abs(need))}</div>
                <div className="mt-1 text-[11px] text-text-secondary">
                  {w.shortfall ? "Nakit açığı" : "Nakit fazlası"} · Gider {formatCurrency(w.planned_out_try)} − Tahsilat {formatCurrency(w.expected_in_try)}
                </div>
              </CardBody>
            </Card>
          );
        })}
      </div>

      {error && !loading ? (
        <Card className="mb-6"><CardBody><LoadError onRetry={refetch} /></CardBody></Card>
      ) : (
      <>
      <Card className="mb-6"><CardBody><CashFlowChart data={chart} height={300} /></CardBody></Card>

      <div className="overflow-x-auto rounded-xl border border-border bg-surface shadow-sm">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="border-b border-border bg-bg text-text-secondary">
            <tr>
              <th className="px-3 py-2.5 text-left text-xs font-medium">Ay</th>
              <th className="px-3 py-2.5 text-right text-xs font-medium">Gider</th>
              <th className="px-3 py-2.5 text-right text-xs font-medium">Gelir</th>
              <th className="px-3 py-2.5 text-right text-xs font-medium">Net Aylık</th>
              <th className="px-3 py-2.5 text-right text-xs font-medium">Kümülatif</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-text-secondary">Yükleniyor...</td></tr>
            ) : (
              rows.map((r) => {
                const cumNeg = toNumber(r.cumulative_try) < 0;
                return (
                  <tr key={r.month} onClick={() => setMonthDetail(r.month)} className={cn("cursor-pointer border-b border-border hover:bg-navy-50", r.is_current && "bg-amber-50")}>
                    <td className="px-3 py-2 font-medium text-brand hover:underline">{r.month}{r.is_current && " (bu ay)"}</td>
                    <td className="px-3 py-2 text-right tabular text-danger">{formatCurrency(showOut(r))}</td>
                    <td className="px-3 py-2 text-right tabular text-success">{formatCurrency(showIn(r))}</td>
                    <td className="px-3 py-2 text-right tabular">{formatCurrency(r.net_try)}</td>
                    <td className={cn("px-3 py-2 text-right tabular", cumNeg && "bg-red-50 text-danger")}>{formatCurrency(r.cumulative_try)}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      </>
      )}

      {id && (
        <CashFlowMonthDrawer
          open={!!monthDetail}
          month={monthDetail}
          projectId={id}
          cumulative={rows.find((r) => r.month === monthDetail)?.cumulative_try}
          onClose={() => setMonthDetail(null)}
        />
      )}
    </div>
  );
}
