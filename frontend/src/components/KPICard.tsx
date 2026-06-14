import { cn } from "@/lib/cn";
import { ArrowDown, ArrowUp, type LucideIcon } from "lucide-react";
import { Skeleton } from "./ui";

interface KPICardProps {
  label: string;
  value: string;
  valueTitle?: string; // exact (un-abbreviated) value shown on hover
  unit?: string;
  subtitle?: string;
  alert?: "red" | "amber" | null;
  loading?: boolean;
  icon?: LucideIcon; // circular accent symbol (top-right)
  series?: number[]; // real recorded history for the sparkline
  delta?: number | null; // real change vs window start
  deltaUnit?: "%" | "pp"; // "%" = relative change (default); "pp" = percentage points (e.g. margin)
  invertDelta?: boolean; // for metrics where "up" is bad (e.g. overdue)
  onClick?: () => void; // CR-004-D / CR-004-K: clickable drill-down
  accentColor?: string; // hex; unique sparkline + icon colour per card
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (!data || data.length < 2) return null;
  const w = 64, h = 20;
  const min = Math.min(...data), max = Math.max(...data), span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * h}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-5 w-16 shrink-0" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// KPI Card — Section 6.5
export function KPICard({ label, value, valueTitle, unit, subtitle, alert, loading, icon: Icon, series, delta, deltaUnit = "%", invertDelta, onClick, accentColor = "#2563EB" }: KPICardProps) {
  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-surface p-4 shadow-sm">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-8 w-28" />
        <Skeleton className="mt-3 h-3 w-20" />
      </div>
    );
  }
  const hasDelta = delta !== undefined && delta !== null;
  const good = hasDelta ? (delta! >= 0) !== !!invertDelta : true;
  const deltaColor = good ? "text-success" : "text-danger";
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
      {/* Title (wraps fully) + circular accent symbol */}
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs leading-snug text-text-secondary">{label}</span>
        {Icon && (
          <span
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
            style={{ backgroundColor: `${accentColor}1A`, color: accentColor }}
          >
            <Icon className="h-4 w-4" />
          </span>
        )}
      </div>

      {/* Value — smaller, kept on a single line with its currency symbol */}
      <div className="mt-2 flex items-baseline gap-1">
        <span title={valueTitle ?? value} className="tabular whitespace-nowrap text-lg font-bold leading-tight text-primary">{value}</span>
        {unit && <span className="shrink-0 text-sm text-text-secondary">{unit}</span>}
      </div>

      {/* Delta + "geçen aya göre" (left); sparkline pinned to the card's bottom-right */}
      <div className="mt-2 flex items-center gap-1 pr-[72px] text-xs">
        {hasDelta ? (
          <>
            <span className={cn("flex items-center gap-0.5 font-medium", deltaColor)}>
              {delta! >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
              {Math.abs(delta!).toFixed(1)}
              {deltaUnit === "pp" ? " pp" : "%"}
            </span>
            <span className="truncate text-text-disabled">geçen aya göre</span>
          </>
        ) : (
          <span className="text-text-disabled">{subtitle ?? "—"}</span>
        )}
      </div>
      {series && series.length >= 2 && (
        <div className="absolute bottom-3 right-3">
          <Sparkline data={series} color={accentColor} />
        </div>
      )}
    </div>
  );
}
