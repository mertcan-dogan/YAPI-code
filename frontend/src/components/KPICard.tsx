import { cn } from "@/lib/cn";
import { ArrowDown, ArrowUp, ArrowUpRight, type LucideIcon } from "lucide-react";
import { Skeleton } from "./ui";

interface KPICardProps {
  label: string;
  value: string;
  valueTitle?: string; // exact (un-abbreviated) value shown on hover
  unit?: string;
  subtitle?: string;
  trend?: number; // percentage change
  alert?: "red" | "amber" | null;
  loading?: boolean;
  icon?: LucideIcon; // top-right accent icon
  onClick?: () => void; // CR-004-D / CR-004-K: clickable drill-down
}

// KPI Card — Section 6.5
export function KPICard({ label, value, valueTitle, unit, subtitle, trend, alert, loading, icon: Icon, onClick }: KPICardProps) {
  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-surface p-4 shadow-sm">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-8 w-32" />
        <Skeleton className="mt-3 h-3 w-20" />
      </div>
    );
  }
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
        {Icon && trend === undefined && <Icon className="h-4 w-4 text-text-disabled" />}
        {trend !== undefined && (
          <span className={cn("flex items-center text-xs", trend >= 0 ? "text-success" : "text-danger")}>
            {trend >= 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
            {Math.abs(trend).toFixed(1)}%
          </span>
        )}
      </div>
      <div className="mt-1 flex min-w-0 items-baseline gap-1">
        <span
          title={valueTitle ?? value}
          className="tabular block truncate text-2xl font-bold leading-tight text-primary sm:text-[28px]"
        >
          {value}
        </span>
        {unit && <span className="shrink-0 text-base text-text-secondary">{unit}</span>}
      </div>
      {subtitle && <p className="mt-2 text-xs text-text-secondary">{subtitle}</p>}
      {onClick && (
        <ArrowUpRight className="absolute bottom-2 right-2 h-3.5 w-3.5 text-text-secondary opacity-0 transition-opacity group-hover:opacity-100" />
      )}
    </div>
  );
}
