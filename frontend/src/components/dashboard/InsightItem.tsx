import { cn } from "@/lib/cn";
import { formatCurrencyAbbrev } from "@/utils/format";
import { Check } from "lucide-react";

export interface BriefingItem {
  project_name: string;
  issue: string;
  recommended_action: string;
  severity: string;
  /** Optional AI-estimated financial impact/saving (TRY). Omitted when unknown. */
  impact_try?: number | null;
  impact_label?: string | null;
}

const SEV_DOT: Record<string, string> = {
  high: "bg-danger",
  medium: "bg-warning",
};

/** Stable key for a briefing item (used to remember completed ones). */
export function briefingKey(item: BriefingItem): string {
  return `${item.project_name}|${item.issue}`;
}

/**
 * Compact AI-briefing row with a done-checkbox. Clicking the checkbox calls
 * onComplete (the parent confirms before removing). Pure presentational.
 */
export function InsightItem({ item, onComplete }: { item: BriefingItem; onComplete?: () => void }) {
  const dot = SEV_DOT[item.severity] ?? "bg-brand";
  const hasImpact = item.impact_try != null && item.impact_try !== 0;
  return (
    <div className="flex items-start gap-2 py-1.5">
      {onComplete && (
        <button
          onClick={onComplete}
          className="group mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border border-border text-transparent transition-colors hover:border-success hover:text-success"
          aria-label="Tamamlandı olarak işaretle"
          title="Tamamlandı olarak işaretle"
        >
          <Check className="h-3 w-3" />
        </button>
      )}
      <span className={cn("mt-1 h-1.5 w-1.5 shrink-0 rounded-full", dot)} />
      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 text-[13px] font-medium leading-snug text-text-primary">{item.issue}</p>
        <p className="truncate text-[11px] text-text-secondary">
          {item.project_name}
          {hasImpact && <span className="text-success"> · ~{formatCurrencyAbbrev(item.impact_try!)}</span>}
        </p>
      </div>
    </div>
  );
}
