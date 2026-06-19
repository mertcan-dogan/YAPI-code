import { Badge, Menu, MenuItem, Pagination, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import type { AIAlert } from "@/types";
import { formatCurrencyAbbrev, formatPct, toNumber } from "@/utils/format";
import { GripVertical, Info, MoreVertical } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

// CR-029-E §9: Project Risk & Performance. Bespoke dense table (the mockup's
// 11-col card with in-card header/footer, per-row status indicator + pagination
// doesn't fit DataTable's self-contained card API) styled with the design tokens.
// All columns are real data; Taahhüt = honest CR-023 placeholder ("—").
const PAGE_SIZE = 5;
const RAG: Record<string, { label: string; variant: "success" | "warning" | "danger" | "neutral"; bar: string }> = {
  green: { label: "Sağlıklı", variant: "success", bar: "var(--color-success)" },
  amber: { label: "İzle", variant: "warning", bar: "var(--color-warning)" },
  red: { label: "Kritik", variant: "danger", bar: "var(--color-danger)" },
};

export function ProjectRiskTable({
  projects,
  performance,
  marginFade,
  alerts,
  loading,
}: {
  projects: any[];
  performance: { project: string; contract_try: string; actual_try: string; forecast_final_try: string }[];
  marginFade: { name: string; target_pct: string; current_pct: string }[];
  alerts: AIAlert[];
  loading?: boolean;
}) {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);

  const rows = useMemo(() => {
    const perfByName = new Map(performance.map((p) => [p.project, p]));
    const targetByName = new Map(marginFade.map((m) => [m.name, m]));
    return (projects ?? []).map((p) => {
      const perf = perfByName.get(p.name);
      const tgt = targetByName.get(p.name);
      const margin = toNumber(p.margin_pct);
      const target = tgt ? toNumber(tgt.target_pct) : null;
      const pp = target != null ? margin - target : null;
      const insight = alerts.find((a) => a.project_id === p.id);
      return {
        id: p.id as string,
        name: p.name as string,
        progress: Math.max(0, Math.min(100, Math.round(toNumber(p.completion_pct)))),
        contract: p.contract_value_try,
        actual: perf?.actual_try,
        forecast: perf?.forecast_final_try,
        margin,
        target,
        pp,
        netCash: toNumber(p.net_cash_position_try),
        insight: insight?.title_tr ?? insight?.body_tr ?? null,
        rag: RAG[p.rag_status] ?? RAG.green,
      };
    });
  }, [projects, performance, marginFade, alerts]);

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const start = (page - 1) * PAGE_SIZE;
  const pageRows = rows.slice(start, start + PAGE_SIZE);

  const stub = (w: string) => toast.info(`${w} — yakında`);

  return (
    <div className="rounded-card border border-border bg-surface shadow-card">
      <div className="flex items-center gap-2 px-3.5 py-3">
        <GripVertical className="h-[15px] w-[15px] cursor-grab text-text-faint" />
        <span className="text-[13px] font-semibold">Proje Risk &amp; Performans</span>
        <span title="Aktif projelerin maliyet, marj ve nakit risk görünümü."><Info className="h-[15px] w-[15px] cursor-help text-text-faint" /></span>
        <div className="ml-auto">
          <Menu align="right" triggerLabel="Tablo menüsü" trigger={<MoreVertical className="h-[15px] w-[15px] text-text-faint" />}>
            {(close) => (
              <>
                <MenuItem onClick={() => { close(); stub("Sütunlar"); }}>Sütunlar</MenuItem>
                <MenuItem onClick={() => { close(); stub("Ayarlar"); }}>Ayarlar</MenuItem>
                <MenuItem onClick={() => { close(); stub("Özelleştir"); }}>Özelleştir</MenuItem>
              </>
            )}
          </Menu>
        </div>
      </div>

      <div className="overflow-x-auto">
        {loading ? (
          <div className="space-y-2 p-3.5">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-6 w-full" />)}
          </div>
        ) : rows.length === 0 ? (
          <div className="px-3.5 py-10 text-center text-sm text-text-muted">Aktif proje bulunmuyor.</div>
        ) : (
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-text-muted">
                <th className="px-2 py-2 font-semibold">Proje</th>
                <th className="px-2 py-2 font-semibold">İlerleme</th>
                <th className="px-2 py-2 text-right font-semibold">Sözleşme</th>
                <th className="px-2 py-2 text-right font-semibold">Gerçekleşen</th>
                <th className="px-2 py-2 text-right font-semibold">Taahhüt</th>
                <th className="px-2 py-2 text-right font-semibold">Tahmini Mal.</th>
                <th className="px-2 py-2 text-right font-semibold">Hedef Marj</th>
                <th className="px-2 py-2 text-right font-semibold">Tahmini Marj</th>
                <th className="px-2 py-2 text-right font-semibold">Nakit Riski</th>
                <th className="px-2 py-2 font-semibold">AI İçgörü</th>
                <th className="px-2 py-2 font-semibold">Durum</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => navigate(`/projects/${r.id}/dashboard`)}
                  className="cursor-pointer border-b border-border text-[11.5px] transition-colors last:border-0 hover:bg-surface-hover"
                >
                  <td className="px-2 py-2 font-semibold" style={{ borderLeft: `3px solid ${r.rag.bar}` }}>{r.name}</td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-1.5">
                      <span className="h-[5px] w-[46px] overflow-hidden rounded-sm bg-surface-hover">
                        <span className="block h-full rounded-sm" style={{ width: `${r.progress}%`, background: r.rag.bar }} />
                      </span>
                      <span className="tabular text-text-secondary">{r.progress}%</span>
                    </div>
                  </td>
                  <td className="px-2 py-2 text-right tabular">{formatCurrencyAbbrev(r.contract)}</td>
                  <td className="px-2 py-2 text-right tabular">{r.actual != null ? formatCurrencyAbbrev(r.actual) : "—"}</td>
                  <td className="px-2 py-2 text-right tabular text-text-faint" title="CR-023 ile gelecek">—</td>
                  <td className="px-2 py-2 text-right tabular">{r.forecast != null ? formatCurrencyAbbrev(r.forecast) : "—"}</td>
                  <td className="px-2 py-2 text-right tabular">{r.target != null ? formatPct(r.target) : "—"}</td>
                  <td className="px-2 py-2 text-right tabular">
                    {formatPct(r.margin)}
                    {r.pp != null && (
                      <span className={cn("ml-1 text-[10px]", r.pp >= 0 ? "text-success" : "text-danger")}>
                        {r.pp >= 0 ? "↑" : "↓"} {Math.abs(r.pp).toFixed(1)} pp
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-right tabular">
                    <span className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" style={{ background: r.netCash < 0 ? "var(--color-danger)" : r.netCash < toNumber(r.contract) * 0.02 ? "var(--color-warning)" : "var(--color-success)" }} />
                    {formatCurrencyAbbrev(r.netCash)}
                  </td>
                  <td className="max-w-[200px] truncate px-2 py-2 text-text-secondary" title={r.insight ?? undefined}>{r.insight ?? "—"}</td>
                  <td className="px-2 py-2"><Badge variant={r.rag.variant}>{r.rag.label}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="flex items-center justify-between px-3.5 py-2.5 text-[11px] text-text-muted">
        <button onClick={() => navigate("/projects")} className="focus-ring font-medium text-brand hover:underline">Tüm projeleri gör</button>
        {rows.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="tabular">{start + 1}–{Math.min(start + PAGE_SIZE, rows.length)} / {rows.length} gösteriliyor</span>
            <Pagination page={page} pageCount={pageCount} onPage={setPage} />
          </div>
        )}
      </div>
    </div>
  );
}
