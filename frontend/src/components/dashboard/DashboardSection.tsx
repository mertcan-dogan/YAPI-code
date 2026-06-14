import { Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { Info } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

/**
 * Dashboard section card: the title + subtitle live INSIDE the card wrapper
 * (like the KPI cards), at a compact font size. Children render below the header
 * and control their own padding (so full-bleed lists/feeds can sit flush).
 *
 * Spacing between sections is left to the caller via `className` (e.g. "mt-5").
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
  /** Right-aligned slot in the header (badge, link, …). */
  right?: ReactNode;
  icon?: ComponentType<{ className?: string }>;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn(className)}>
      <Card className="overflow-hidden">
        <div className="flex items-start justify-between gap-3 px-4 pb-3 pt-4">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-primary">
              {Icon && <Icon className="h-3.5 w-3.5 text-brand" />}
              <span>{title}</span>
              {info && (
                <span title={info} className="cursor-help text-text-disabled transition-colors hover:text-text-secondary" aria-label={info}>
                  <Info className="h-3 w-3" />
                </span>
              )}
            </h2>
            {subtitle && <p className="mt-0.5 text-[11px] leading-snug text-text-secondary">{subtitle}</p>}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </div>
        {children}
      </Card>
    </section>
  );
}
