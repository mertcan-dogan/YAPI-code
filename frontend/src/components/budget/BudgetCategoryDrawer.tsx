import { MiniBarChart } from "@/components/charts";
import { ExtractionConfidenceBadge } from "@/components/ai/ExtractionConfidenceBadge";
import { SideDrawer } from "@/components/SideDrawer";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui";
import { COST_CATEGORIES } from "@/constants";
import { apiGet } from "@/lib/api";
import type { BudgetCategoryRow, CostEntry } from "@/types";
import { formatCurrency, formatDate, formatPct, toNumber } from "@/utils/format";
import { Pencil } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

// CR-004-L: budget category detail drawer — summary band, record list, mini trend.
export function BudgetCategoryDrawer({
  open,
  onClose,
  projectId,
  row,
  onEdit,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  row: BudgetCategoryRow | null;
  onEdit: (c: CostEntry) => void;
}) {
  const [rows, setRows] = useState<CostEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const category = row?.cost_category;

  useEffect(() => {
    if (!open || !projectId || !category) return;
    setLoading(true);
    // CR-005-B: the costs endpoint caps per_page at 100; requesting 200 returned a
    // 422 that was swallowed, leaving the trend chart empty ("boş eksen, veri yok").
    apiGet<CostEntry[]>(`/projects/${projectId}/costs`, { category, per_page: 100 })
      .then((r) => setRows([...r.data].sort((a, b) => (a.entry_date < b.entry_date ? -1 : 1))))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [open, projectId, category]);

  // Last 6 months spend trend, bucketed by entry_date.
  const trend = useMemo(() => {
    const keys: string[] = [];
    const d = new Date();
    for (let i = 5; i >= 0; i--) {
      const dt = new Date(d.getFullYear(), d.getMonth() - i, 1);
      keys.push(`${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`);
    }
    const buckets: Record<string, number> = Object.fromEntries(keys.map((k) => [k, 0]));
    for (const r of rows) {
      const k = (r.entry_date ?? "").slice(0, 7);
      if (k in buckets) buckets[k] += toNumber(r.total_with_vat_try);
    }
    return keys.map((k) => ({ month: k, value: buckets[k] }));
  }, [rows]);

  // CR-005-B: only render the chart when there is real spend in the window —
  // otherwise show a "Veri yok" message instead of an empty axis.
  const trendHasData = useMemo(() => trend.some((t) => t.value > 0), [trend]);

  const total = rows.reduce((s, r) => s + toNumber(r.total_with_vat_try), 0);
  const label = row?.label_tr ?? (category ? COST_CATEGORIES[category] ?? category : "");

  return (
    <SideDrawer open={open} onClose={onClose} title={`${label} — Bütçe Detayı`}>
      {!row ? null : (
        <div className="space-y-4">
          {/* Summary band */}
          <div className="grid grid-cols-2 gap-2">
            <Chip label="Revize Bütçe" value={formatCurrency(row.revised_budget_try)} />
            <Chip label="Taahhüt" value={formatCurrency(row.committed_try)} />
            <Chip label="Faturalanan" value={formatCurrency(row.invoiced_try)} />
            <Chip label="Ödenen" value={formatCurrency(row.paid_try)} />
            <Chip
              label="Sapma"
              value={formatCurrency(row.variance_try)}
              color={toNumber(row.variance_try) > 0 ? "#EF4444" : toNumber(row.variance_try) < 0 ? "#10B981" : undefined}
            />
            <Chip label="% Harcanan" value={formatPct(row.pct_spent)} />
          </div>

          {/* Mini trend */}
          <div>
            <p className="mb-1 text-xs font-semibold text-text-secondary">Aylık Harcama (Son 6 Ay)</p>
            {loading ? (
              <p className="text-sm text-text-secondary">Yükleniyor…</p>
            ) : trendHasData ? (
              <MiniBarChart data={trend} height={200} />
            ) : (
              <div className="flex h-[200px] items-center justify-center rounded-md border border-dashed border-border text-sm text-text-secondary">
                Veri yok
              </div>
            )}
          </div>

          {/* Record list */}
          <div>
            <p className="mb-2 text-xs font-semibold text-text-secondary">Maliyet Kayıtları ({rows.length})</p>
            {loading ? (
              <p className="text-sm text-text-secondary">Yükleniyor…</p>
            ) : rows.length === 0 ? (
              <p className="text-sm text-text-secondary">Bu kategoride kayıt yok.</p>
            ) : (
              <div className="space-y-2">
                {rows.map((r) => (
                  <div key={r.id} className="rounded-md border border-border p-2 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{r.supplier_name || r.description || "—"}</span>
                      <div className="flex items-center gap-2">
                        <span className="tabular font-semibold">{formatCurrency(r.total_with_vat_try)}</span>
                        <button onClick={() => onEdit(r)} className="text-text-secondary hover:text-primary" aria-label="Düzenle">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                    <div className="mt-0.5 flex items-center justify-between text-xs text-text-secondary">
                      <span>{formatDate(r.entry_date)} · KDV %{toNumber(r.vat_rate)}</span>
                      <span>Vade: {formatDate(r.payment_due_date)}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <StatusBadge status={r.payment_status} />
                      {/* CR-024: AI-read rows carry a confidence pill (none on manual rows). */}
                      <ExtractionConfidenceBadge confidence={r.extraction_confidence} />
                    </div>
                  </div>
                ))}
                <div className="flex items-center justify-between border-t border-border pt-2 text-sm font-semibold">
                  <span>Toplam</span>
                  <span className="tabular">{formatCurrency(total)}</span>
                </div>
              </div>
            )}
          </div>

          <Button variant="ghost" className="w-full" onClick={onClose}>Kapat</Button>
        </div>
      )}
    </SideDrawer>
  );
}

function Chip({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-md border border-border bg-bg px-3 py-2">
      <div className="text-[11px] text-text-secondary">{label}</div>
      <div className="tabular text-sm font-bold" style={{ color: color ?? "var(--color-text-primary)" }}>{value}</div>
    </div>
  );
}
