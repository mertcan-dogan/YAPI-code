import { cn } from "@/lib/cn";
import { Info } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

/**
 * Consistent section header (title + optional subtitle / info tooltip / right
 * action) used across the Ana Sayfa dashboard so every block shares the same
 * typographic rhythm. Pure presentational — no data, no side effects.
 *
 * Spacing is left to the caller via `className` (e.g. "mt-8" for a top-level
 * section, none inside a grid cell) so it composes cleanly in grids.
 */
export function DashboardSection({
  title,
  subtitle,
  info,
  right,
  icon: Icon,
  children,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Native-tooltip text shown on a small info icon next to the title. */
  info?: string;
  /** Right-aligned slot in the header (badge, refresh button, timestamp…). */
  right?: ReactNode;
  icon?: ComponentType<{ className?: string }>;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn(className)}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-primary">
            {Icon && <Icon className="h-4 w-4 text-brand" />}
            <span className="truncate">{title}</span>
            {info && (
              <span title={info} className="cursor-help text-text-disabled transition-colors hover:text-text-secondary" aria-label={info}>
                <Info className="h-3.5 w-3.5" />
              </span>
            )}
          </h2>
          {subtitle && <p className="mt-1 text-xs text-text-secondary">{subtitle}</p>}
        </div>
        {right && <div className="shrink-0">{right}</div>}
      </div>
      {children}
    </section>
  );
}
