import { ExtractionConfidenceBadge } from "@/components/ai/ExtractionConfidenceBadge";
import { SideDrawer } from "@/components/SideDrawer";
import { StatusBadge } from "@/components/StatusBadge";
import { COST_CATEGORIES } from "@/constants";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatCurrency, formatDate, toNumber } from "@/utils/format";
import { useEffect, useRef, useState } from "react";

interface CostRow {
  id: string;
  entry_date: string;
  cost_category: string;
  supplier_name?: string | null;
  description?: string | null;
  total_with_vat_try: string;
  payment_status: string;
  extraction_confidence?: number | null; // CR-024: AI extraction confidence (0..1)
}

// CR-004-K: "Gerçekleşen Maliyet" drill-down — all cost entries for the project.
export function CostEntriesDrawer({
  open,
  onClose,
  projectId,
  highlightId,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  highlightId?: string | null; // CR-007-H: cited cost entry to scroll to + flash
}) {
  const [rows, setRows] = useState<CostRow[]>([]);
  const [loading, setLoading] = useState(false);
  const highlightRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !projectId) return;
    setLoading(true);
    apiGet<CostRow[]>(`/projects/${projectId}/costs`)
      .then((r) => setRows(r.data))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [open, projectId]);

  // CR-007-H: bring the cited entry into view once the rows are present.
  useEffect(() => {
    if (open && highlightId && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [open, highlightId, rows]);

  const total = rows.reduce((s, r) => s + toNumber(r.total_with_vat_try), 0);

  return (
    <SideDrawer open={open} onClose={onClose} title={`Maliyet Kayıtları — ${rows.length} adet`}>
      {loading ? (
        <p className="text-sm text-text-secondary">Yükleniyor…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-text-secondary">Bu projede maliyet kaydı bulunmuyor.</p>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => {
            const isHighlighted = highlightId != null && r.id === highlightId;
            return (
            <div
              key={r.id}
              ref={isHighlighted ? highlightRef : undefined}
              className={cn("rounded-md border border-border p-3 text-sm", isHighlighted && "yapi-row-flash")}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-primary">{COST_CATEGORIES[r.cost_category] ?? r.cost_category}</span>
                <span className="tabular font-semibold">{formatCurrency(r.total_with_vat_try)}</span>
              </div>
              <div className="mt-0.5 flex items-center justify-between text-xs text-text-secondary">
                <span>{r.supplier_name || r.description || "—"}</span>
                <span>{formatDate(r.entry_date)}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <StatusBadge status={r.payment_status} />
                {/* CR-024: AI-read rows carry a confidence pill (none on manual rows). */}
                <ExtractionConfidenceBadge confidence={r.extraction_confidence} />
              </div>
            </div>
            );
          })}
          <div className="flex items-center justify-between border-t border-border pt-2 text-sm font-semibold">
            <span>Toplam</span>
            <span className="tabular">{formatCurrency(total)}</span>
          </div>
        </div>
      )}
    </SideDrawer>
  );
}
