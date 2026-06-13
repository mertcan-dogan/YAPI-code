import { Card, CardBody, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import { formatCurrency, formatCurrencyAbbrev, formatPct, toNumber } from "@/utils/format";
import { Layers } from "lucide-react";
import { useState } from "react";

export interface BudgetBreakdownItem {
  category: string;
  label_tr: string;
  value_try: string;
  pct_of_total: string;
}

/** Calm, cycling bar palette (token colors) — not a rainbow. */
const BAR_COLORS = ["bg-brand", "bg-brand-2", "bg-accent", "bg-success", "bg-primary"];

type View = "value" | "pct";

/**
 * Bütçe Dağılımı — horizontal-bar breakdown of revised budget by cost category.
 * Bars are always proportional to `pct_of_total`; the "Değer | Bütçe %" toggle
 * only switches the right-hand number. Pure presentational; all aggregation is
 * done server-side (/dashboard → budget_breakdown).
 */
export function BudgetBreakdownCard({
  items,
  total,
  loading,
}: {
  items: BudgetBreakdownItem[];
  total: string;
  loading?: boolean;
}) {
  const [view, setView] = useState<View>("value");
  const hasData = !loading && items.length > 0;

  return (
    <Card>
      <CardBody>
        {hasData && (
          <div className="mb-3 flex items-center justify-end">
            <div className="inline-flex rounded-lg border border-border bg-bg p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setView("value")}
                className={cn(
                  "rounded-md px-2.5 py-1 transition-colors",
                  view === "value" ? "bg-surface font-medium text-primary shadow-sm" : "text-text-secondary hover:text-text-primary"
                )}
              >
                Değer
              </button>
              <button
                type="button"
                onClick={() => setView("pct")}
                className={cn(
                  "rounded-md px-2.5 py-1 transition-colors",
                  view === "pct" ? "bg-surface font-medium text-primary shadow-sm" : "text-text-secondary hover:text-text-primary"
                )}
              >
                Bütçe %
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div>
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 py-2.5">
                <Skeleton className="h-3 w-6" />
                <div className="flex-1">
                  <Skeleton className="h-3 w-1/3" />
                  <Skeleton className="mt-2 h-2 w-full" />
                </div>
              </div>
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bg">
              <Layers className="h-5 w-5 text-text-disabled" />
            </div>
            <p className="text-sm font-medium text-text-primary">Henüz bütçe kalemi yok</p>
            <p className="max-w-xs text-xs text-text-secondary">
              Proje bütçelerini girdiğinizde maliyet kategorisi dağılımı burada görünecek.
            </p>
          </div>
        ) : (
          <div>
            {items.map((it, i) => (
              <div key={it.category} className="flex items-center gap-3 border-b border-border py-2.5 last:border-0">
                <span className="tabular w-6 shrink-0 text-xs font-medium text-text-disabled">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium text-text-primary" title={it.label_tr}>
                      {it.label_tr}
                    </span>
                    <span className="tabular shrink-0 text-sm font-semibold text-text-primary" title={formatCurrency(it.value_try)}>
                      {view === "value" ? formatCurrencyAbbrev(it.value_try) : formatPct(it.pct_of_total)}
                    </span>
                  </div>
                  <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-bg">
                    <div
                      className={cn("h-full rounded-full", BAR_COLORS[i % BAR_COLORS.length])}
                      style={{ width: `${Math.min(toNumber(it.pct_of_total), 100)}%` }}
                    />
                  </div>
                </div>
              </div>
            ))}

            <div className="mt-1 flex items-center justify-between border-t-2 border-border pt-3">
              <span className="text-sm font-bold text-primary">Toplam (Bütçe Kalemleri)</span>
              <span className="flex items-baseline gap-2">
                <span className="tabular text-sm font-bold text-primary" title={formatCurrency(total)}>
                  {formatCurrencyAbbrev(total)}
                </span>
                <span className="tabular text-xs font-semibold text-text-secondary">100%</span>
              </span>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
