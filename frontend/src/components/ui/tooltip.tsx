import { cn } from "@/lib/cn";
import { Info } from "lucide-react";
import * as React from "react";

// Lightweight hover/focus tooltip (CR-001-C). Positioned top, max-width 280px.
export function Tooltip({ text, children }: { text: string; children?: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      tabIndex={0}
    >
      {children}
      {open && (
        <span
          role="tooltip"
          className={cn(
            "absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2 rounded-md bg-primary px-3 py-2",
            "text-xs font-normal leading-snug text-white shadow-lg"
          )}
          style={{ width: "280px", maxWidth: "280px" }}
        >
          {text}
        </span>
      )}
    </span>
  );
}

// Convenience: an Info (i) icon that shows a tooltip on hover/focus.
export function InfoTooltip({ text }: { text: string }) {
  return (
    <Tooltip text={text}>
      <Info size={14} color="#64748B" className="cursor-help" aria-label="Bilgi" />
    </Tooltip>
  );
}
