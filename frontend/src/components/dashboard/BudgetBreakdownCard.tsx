import { BudgetBreakdownChart } from "@/components/charts";
import { Card, CardBody, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import { formatCurrency, formatCurrencyAbbrev, toNumber } from "@/utils/format";
import { Layers } from "lucide-react";
import { useState } from "react";

export interface BudgetBreakdownItem {
  category: string;
  label_tr: string;
  value_try: string;
  pct_of_total: string;
}

type View = "value" | "pct";

/**
 * Bütçe Dağılımı — horizontal-bar chart of revised budget by cost category.
 * The "Değer | Bütçe %" toggle switches the bar axis between TRY and percentage;
 * bars stay proportional either way. All aggregation is server-side
 * (/dashboard → budget_breakdown). This is the entered-line-items total and may
 * differ from the project-level "Revize Bütçe" (see footer label).
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
  const chartData = items.map((it) => ({
    label: it.label_tr,
    value: toNumber(it.value_try),
    pct: toNumber(it.pct_of_total),
  }));

  return (
    <Card>
      <CardBody>
        {hasData && (
          <div className="mb-2 flex items-center justify-end">
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
          <div className="space-y-3 py-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-5 w-full" />
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
          <>
            <BudgetBreakdownChart data={chartData} mode={view} />
            <div className="mt-2 flex items-center justify-between border-t-2 border-border pt-3">
              <span className="text-sm font-bold text-primary">Toplam (Bütçe Kalemleri)</span>
              <span className="flex items-baseline gap-2">
                <span className="tabular text-sm font-bold text-primary" title={formatCurrency(total)}>
                  {formatCurrencyAbbrev(total)}
                </span>
                <span className="tabular text-xs font-semibold text-text-secondary">100%</span>
              </span>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}
