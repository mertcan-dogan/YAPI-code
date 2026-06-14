import { MetricLineChart } from "@/components/charts";
import { Button, Modal } from "@/components/ui";
import { cn } from "@/lib/cn";
import { ArrowDown, ArrowUp } from "lucide-react";

export interface KpiInfo {
  title: string;
  value: string;
  description: string;
  series?: number[];
  delta?: number | null;
  deltaUnit?: "%" | "pp";
  invertDelta?: boolean;
  accentColor?: string;
  /** Unit for the trend chart axis/tooltip. */
  valueKind?: "currency" | "percent";
  action?: { label: string; onClick: () => void };
}

/** Generic KPI drill-down: value, trend, explanation, optional action. */
export function KpiDetailModal({ open, onClose, kpi }: { open: boolean; onClose: () => void; kpi: KpiInfo | null }) {
  if (!kpi) return null;
  const hasDelta = kpi.delta != null;
  const good = hasDelta ? (kpi.delta! >= 0) !== !!kpi.invertDelta : true;
  const trend = (kpi.series ?? []).map((v, i) => ({ name: String(i + 1), value: v }));

  return (
    <Modal open={open} title={kpi.title} onClose={onClose} size="md">
      <div className="space-y-4">
        <div>
          <div className="tabular text-3xl font-bold text-primary">{kpi.value}</div>
          {hasDelta && (
            <div className={cn("mt-1 flex items-center gap-1 text-sm font-medium", good ? "text-success" : "text-danger")}>
              {kpi.delta! >= 0 ? <ArrowUp className="h-4 w-4" /> : <ArrowDown className="h-4 w-4" />}
              {Math.abs(kpi.delta!).toFixed(1)}
              {kpi.deltaUnit === "pp" ? " pp" : "%"}
              <span className="text-text-secondary">geçen aya göre</span>
            </div>
          )}
        </div>

        {trend.length >= 2 ? (
          <div className="rounded-lg border border-border p-2">
            <div className="mb-1 px-1 text-xs font-medium text-text-secondary">Eğilim (kayıtlı geçmiş)</div>
            <MetricLineChart data={trend} height={160} color={kpi.accentColor} hideXAxis unit={kpi.valueKind === "percent" ? "percent" : "currency"} />
          </div>
        ) : (
          <div className="rounded-lg bg-bg px-3 py-2 text-xs text-text-secondary">
            Eğilim verisi henüz yeterli değil — günlük anlık görüntüler biriktikçe burada görünecek.
          </div>
        )}

        <p className="text-sm leading-relaxed text-text-secondary">{kpi.description}</p>

        {kpi.action && (
          <div className="flex justify-end">
            <Button
              onClick={() => {
                onClose();
                kpi.action!.onClick();
              }}
            >
              {kpi.action.label}
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}
