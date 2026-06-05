import { CashFlowChart } from "@/components/charts";
import { Card, CardBody } from "@/components/ui";
import { PageHeader } from "@/components/layout/AppLayout";
import { cn } from "@/lib/cn";
import { useFetch } from "@/hooks/useFetch";
import { formatCurrency, toNumber } from "@/utils/format";
import { useState } from "react";
import { useParams } from "react-router-dom";

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
  const { data, loading } = useFetch<Row[]>(`/projects/${id}/cashflow`);
  const [view, setView] = useState<"both" | "planned" | "actual">("both");
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
      <Card className="mb-6"><CardBody><CashFlowChart data={chart} height={300} /></CardBody></Card>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-primary text-white">
            <tr>
              <th className="px-3 py-2 text-left text-xs">Ay</th>
              <th className="px-3 py-2 text-right text-xs">Gider</th>
              <th className="px-3 py-2 text-right text-xs">Gelir</th>
              <th className="px-3 py-2 text-right text-xs">Net Aylık</th>
              <th className="px-3 py-2 text-right text-xs">Kümülatif</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-text-secondary">Yükleniyor...</td></tr>
            ) : (
              rows.map((r) => {
                const cumNeg = toNumber(r.cumulative_try) < 0;
                return (
                  <tr key={r.month} className={cn("border-b border-border", r.is_current && "bg-amber-50")}>
                    <td className="px-3 py-2">{r.month}{r.is_current && " (bu ay)"}</td>
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
    </div>
  );
}
