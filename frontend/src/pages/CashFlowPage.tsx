import { CashFlowChart } from "@/components/charts";
import { Button, Card, CardBody } from "@/components/ui";
import { ExportMenu, type ExportColumn } from "@/components/ExportMenu";
import { DashboardSection } from "@/components/dashboard/DashboardSection";
import { LoadError } from "@/components/EmptyState";
import { CashFlowMonthDrawer } from "@/components/cashflow/CashFlowMonthDrawer";
import { PageHeader } from "@/components/layout/AppLayout";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useFetch } from "@/hooks/useFetch";
import { toast } from "@/store/toast";
import { formatCurrency, toNumber } from "@/utils/format";
import { Download } from "lucide-react";
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

type Preset = "all" | "3m" | "6m" | "12m" | "year" | "custom";

const PRESETS: { key: Preset; label: string }[] = [
  { key: "3m", label: "Son 3 Ay" },
  { key: "6m", label: "Son 6 Ay" },
  { key: "12m", label: "Son 12 Ay" },
  { key: "year", label: "Bu Yıl" },
  { key: "all", label: "Tümü" },
  { key: "custom", label: "Özel" },
];

const monthKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;

export default function CashFlowPage() {
  const { id } = useParams();
  // CR: date-range filter. "Tümü" = the default rolling window (no params, no
  // regression); presets/custom send from_month/to_month (YYYY-MM).
  const [preset, setPreset] = useState<Preset>("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  const now = new Date();
  const back = (n: number) => monthKey(new Date(now.getFullYear(), now.getMonth() - n, 1));
  const thisMonth = monthKey(now);
  let from_month: string | undefined;
  let to_month: string | undefined;
  if (preset === "3m") [from_month, to_month] = [back(2), thisMonth];
  else if (preset === "6m") [from_month, to_month] = [back(5), thisMonth];
  else if (preset === "12m") [from_month, to_month] = [back(11), thisMonth];
  else if (preset === "year") [from_month, to_month] = [`${now.getFullYear()}-01`, thisMonth];
  else if (preset === "custom") [from_month, to_month] = [customFrom || undefined, customTo || undefined];
  // Custom range incomplete or inverted -> don't fetch an invalid window.
  const customInvalid = preset === "custom" && !!from_month && !!to_month && from_month > to_month;
  if (preset === "custom" && (!from_month || !to_month || customInvalid)) {
    from_month = undefined;
    to_month = undefined;
  }

  const { data, meta, loading, error, refetch } = useFetch<Row[]>(`/projects/${id}/cashflow`, { from_month, to_month });
  const { data: risk, error: riskError, refetch: refetchRisk } = useFetch<RiskWindow[]>(`/projects/${id}/cashflow/risk`);
  const [view, setView] = useState<"both" | "planned" | "actual">("both");
  const [monthDetail, setMonthDetail] = useState<string | null>(null);
  const rows = data ?? [];
  const opening = meta?.opening_balance_try;
  const ranged = !!meta?.from_month && !!meta?.to_month;
  const showOpening = ranged && opening != null && toNumber(opening) !== 0;

  const chart = rows.map((r) => {
    const inV = r.is_past || r.is_current ? toNumber(r.actual_in_try) : toNumber(r.planned_in_try);
    const outV = r.is_past || r.is_current ? toNumber(r.actual_out_try) : toNumber(r.planned_out_try);
    return { month: r.month, in: inV, out: outV, cumulative: toNumber(r.cumulative_try) };
  });

  const showOut = (r: Row) => (view === "planned" ? r.planned_out_try : view === "actual" ? r.actual_out_try : r.is_past || r.is_current ? r.actual_out_try : r.planned_out_try);
  const showIn = (r: Row) => (view === "planned" ? r.planned_in_try : view === "actual" ? r.actual_in_try : r.is_past || r.is_current ? r.actual_in_try : r.planned_in_try);

  // Export respects the active Planlanan/Gerçekleşen/İkisi de view. This feeds the
  // secondary "Ham veri (CSV)" option only — the primary export is the backend
  // decision-grade workbook (below).
  const exportColumns: ExportColumn<Row>[] = [
    { header: "Ay", value: (r) => r.month },
    { header: "Gider", value: (r) => toNumber(showOut(r)) },
    { header: "Gelir", value: (r) => toNumber(showIn(r)) },
    { header: "Net Aylık", value: (r) => toNumber(r.net_try) },
    { header: "Kümülatif", value: (r) => toNumber(r.cumulative_try) },
  ];

  // CR-054 — the primary "Dışa Aktar" downloads the CR-048 decision-grade workbook
  // (Özet KPIs + ₺-formatted table + cumulative line) from the existing backend
  // endpoint, not the raw client-side "Veri" dump. Mirrors the Raporlar download.
  const [exporting, setExporting] = useState(false);
  const exportWorkbook = async () => {
    if (!id) return;
    setExporting(true);
    try {
      const res = await api.get(`/reports/cashflow/${id}`, { responseType: "blob", params: { fmt: "xlsx" } });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "nakit-akis-raporu.xlsx";
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Rapor indirildi");
    } catch (e: any) {
      toast.error(e?.message ?? "Rapor oluşturulamadı");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Nakit Akışı"
        action={
          <div className="flex items-center gap-2">
            <div className="flex gap-1 rounded-md border border-border p-0.5">
              {(["both", "planned", "actual"] as const).map((v) => (
                <button key={v} onClick={() => setView(v)} className={cn("rounded px-3 py-1 text-sm", view === v ? "bg-primary text-white" : "text-text-secondary")}>
                  {v === "both" ? "İkisi de" : v === "planned" ? "Planlanan" : "Gerçekleşen"}
                </button>
              ))}
            </div>
            <Button loading={exporting} disabled={!id} onClick={exportWorkbook}>
              <Download className="h-4 w-4" /> Dışa Aktar
            </Button>
            <ExportMenu rows={rows} columns={exportColumns} filename="nakit-akisi" csvOnly triggerLabel="Ham veri (CSV)" />
          </div>
        }
      />

      {/* CR: date-range filter (presets + custom month picker). The 30/60/90-day
          risk cards below stay anchored to today, not the range. */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1 rounded-md border border-border p-0.5">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPreset(p.key)}
              className={cn("rounded px-3 py-1 text-sm", preset === p.key ? "bg-primary text-white" : "text-text-secondary")}
            >
              {p.label}
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

      {/* CR-004-M: 30/60/90-day cash-need cards */}
      {riskError ? (
        <Card className="mb-4"><CardBody><LoadError message="Nakit ihtiyacı kartları yüklenemedi." onRetry={refetchRisk} /></CardBody></Card>
      ) : (
      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
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
      )}

      {error && !loading ? (
        <Card className="mb-4"><CardBody><LoadError onRetry={refetch} /></CardBody></Card>
      ) : (
      <>
      <DashboardSection className="mb-4" title="Nakit Akış Grafiği">
        <div className="px-4 pb-4"><CashFlowChart data={chart} height={300} /></div>
      </DashboardSection>

      <DashboardSection title="Aylık Detay">
      <div className="overflow-x-auto">
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
            {/* CR: carried-in opening balance so the period's cumulative isn't read as starting at zero. */}
            {!loading && showOpening && (
              <tr className="border-b border-border bg-bg italic text-text-secondary">
                <td className="px-3 py-2">Devreden bakiye (dönem başı)</td>
                <td className="px-3 py-2" /><td className="px-3 py-2" /><td className="px-3 py-2" />
                <td className={cn("px-3 py-2 text-right tabular", toNumber(opening) < 0 && "text-danger")}>{formatCurrency(opening)}</td>
              </tr>
            )}
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
      </DashboardSection>
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
