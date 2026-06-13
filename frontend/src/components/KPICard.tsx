import { cn } from "@/lib/cn";
import { ArrowDown, ArrowUp, ArrowUpRight, type LucideIcon } from "lucide-react";
import { Skeleton } from "./ui";

interface KPICardProps {
  label: string;
  value: string;
  valueTitle?: string; // exact (un-abbreviated) value shown on hover
  unit?: string;
  subtitle?: string;
  alert?: "red" | "amber" | null;
  loading?: boolean;
  icon?: LucideIcon; // top-right accent icon (shown when no delta yet)
  series?: number[]; // real recorded history for the sparkline
  delta?: number | null; // real % change vs window start
  invertDelta?: boolean; // for metrics where "up" is bad (e.g. overdue)
  onClick?: () => void; // CR-004-D / CR-004-K: clickable drill-down
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (!data || data.length < 2) return null;
  const w = 60, h = 22;
  const min = Math.min(...data), max = Math.max(...data), span = max - min || 1;
  const pts = data
    .map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * h}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-6 w-16 shrink-0" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// KPI Card — Section 6.5
export function KPICard({ label, value, valueTitle, unit, subtitle, alert, loading, icon: Icon, series, delta, invertDelta, onClick }: KPICardProps) {
  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-surface p-4 shadow-sm">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-8 w-32" />
        <Skeleton className="mt-3 h-3 w-20" />
      </div>
    );
  }
  const hasDelta = delta !== undefined && delta !== null;
  const good = hasDelta ? (delta! >= 0) !== !!invertDelta : true;
  const deltaColor = good ? "text-success" : "text-danger";
  const sparkColor = hasDelta ? (good ? "var(--color-success)" : "var(--color-danger)") : "var(--color-brand)";
  return (
    <div
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => (e.key === "Enter" || e.key === " ") && onClick() : undefined}
      className={cn(
        "group relative rounded-xl border border-border bg-surface p-4 shadow-sm transition-shadow hover:shadow-md",
        alert === "red" && "border-l-4 border-l-danger",
        alert === "amber" && "border-l-4 border-l-accent",
        onClick && "cursor-pointer hover:border-brand"
      )}
    >
      <div className="flex items-start justify-between">
        <span className="text-xs text-text-secondary">{label}</span>
        {hasDelta ? (
          <span className={cn("flex items-center gap-0.5 text-xs font-medium", deltaColor)}>
            {delta! >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
            {Math.abs(delta!).toFixed(1)}%
          </span>
        ) : (
          Icon && <Icon className="h-4 w-4 text-text-disabled" />
        )}
      </div>
      <div className="mt-1 flex min-w-0 items-end justify-between gap-2">
        <div className="flex min-w-0 items-baseline gap-1">
          <span
            title={valueTitle ?? value}
            className="tabular block truncate text-2xl font-bold leading-tight text-primary sm:text-[28px]"
          >
            {value}
          </span>
          {unit && <span className="shrink-0 text-base text-text-secondary">{unit}</span>}
        </div>
        {series && series.length >= 2 && <Sparkline data={series} color={sparkColor} />}
      </div>
      {subtitle && <p className="mt-2 text-xs text-text-secondary">{subtitle}</p>}
      {onClick && (
        <ArrowUpRight className="absolute bottom-2 right-2 h-3.5 w-3.5 text-text-secondary opacity-0 transition-opacity group-hover:opacity-100" />
      )}
    </div>
  );
}
