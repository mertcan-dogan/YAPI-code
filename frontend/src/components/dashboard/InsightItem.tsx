import { cn } from "@/lib/cn";
import { formatCurrencyAbbrev } from "@/utils/format";
import { AlarmClock, AlertTriangle, Info, TrendingDown } from "lucide-react";

export interface BriefingItem {
  project_name: string;
  issue: string;
  recommended_action: string;
  severity: string;
  /** Optional AI-estimated financial impact/saving (TRY). Omitted when unknown. */
  impact_try?: number | null;
  impact_label?: string | null;
}

function sevStyle(severity: string): { bg: string; fg: string; chip: string; label: string; Icon: typeof AlertTriangle } {
  switch (severity) {
    case "high":
      return { bg: "bg-red-50", fg: "text-danger", chip: "bg-red-50 text-danger", label: "Yüksek", Icon: AlertTriangle };
    case "medium":
      return { bg: "bg-amber-50", fg: "text-warning", chip: "bg-amber-50 text-warning", label: "Orta", Icon: AlarmClock };
    default:
      return { bg: "bg-navy-50", fg: "text-brand", chip: "bg-navy-50 text-brand", label: "Düşük", Icon: Info };
  }
}

/**
 * A single AI-briefing row: severity icon + chip, project, issue, recommended
 * action, and an optional estimated impact (₺). Pure presentational.
 */
export function InsightItem({ item }: { item: BriefingItem }) {
  const sv = sevStyle(item.severity);
  const hasImpact = item.impact_try != null && item.impact_try !== 0;
  return (
    <div className="flex gap-3 border-b border-border pb-3 last:border-0 last:pb-0">
      <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", sv.bg, sv.fg)}>
        <sv.Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-xs font-semibold text-text-secondary">{item.project_name}</span>
          <span className={cn("shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium", sv.chip)}>{sv.label}</span>
        </div>
        <p className="mt-0.5 text-sm font-medium text-text-primary">{item.issue}</p>
        <p className="mt-0.5 text-xs text-text-secondary">→ {item.recommended_action}</p>
        {hasImpact && (
          <span className="mt-1 inline-flex items-center gap-1 rounded-md bg-green-50 px-1.5 py-0.5 text-[11px] font-medium text-success">
            <TrendingDown className="h-3 w-3" />
            {item.impact_label ?? "Tahmini etki"}: ~{formatCurrencyAbbrev(item.impact_try!)}
          </span>
        )}
      </div>
    </div>
  );
}
