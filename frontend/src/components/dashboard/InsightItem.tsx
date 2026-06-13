import { cn } from "@/lib/cn";
import { AlarmClock, AlertTriangle, Info } from "lucide-react";

export interface BriefingItem {
  project_name: string;
  issue: string;
  recommended_action: string;
  severity: string;
}

function sevStyle(severity: string): { bg: string; fg: string; Icon: typeof AlertTriangle } {
  switch (severity) {
    case "high":
      return { bg: "bg-red-50", fg: "text-danger", Icon: AlertTriangle };
    case "medium":
      return { bg: "bg-amber-50", fg: "text-warning", Icon: AlarmClock };
    default:
      return { bg: "bg-navy-50", fg: "text-brand", Icon: Info };
  }
}

/**
 * A single "Bugün Ne Yapmalısın" AI-briefing row: severity icon, project,
 * issue, and recommended action. Pure presentational.
 */
export function InsightItem({ item }: { item: BriefingItem }) {
  const sv = sevStyle(item.severity);
  return (
    <div className="flex gap-3 border-b border-border pb-3 last:border-0 last:pb-0">
      <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", sv.bg, sv.fg)}>
        <sv.Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <span className="block truncate text-xs font-semibold text-text-secondary">{item.project_name}</span>
        <p className="mt-0.5 text-sm font-medium text-text-primary">{item.issue}</p>
        <p className="mt-0.5 text-xs text-text-secondary">→ {item.recommended_action}</p>
      </div>
    </div>
  );
}
