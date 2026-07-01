import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import { Link } from "react-router-dom";

// CR-038 — extracted from the old AppLayout `NavItem` so the SAME row renders in
// the top-bar dropdowns, the contextual rails, and the mobile drawer. Behaviour
// is byte-for-byte the old one: active = blue-soft bg + brand text; comingSoon =
// muted + a "yakında" tag + a toast on click.
export const NAV_SOON_MSG = "Bu özellik yakında tüm kullanıcılara sunulacak.";

export interface NavItemRowProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  to: string;
  active?: boolean;
  comingSoon?: boolean;
  onNavigate?: () => void;
  right?: React.ReactNode;
  // When inside a top-bar dropdown the row is a `menuitem` with roving tabindex
  // (focus is managed by the parent menu); elsewhere it is a normal link.
  inMenu?: boolean;
}

export function NavItemRow({ icon: Icon, label, to, active, comingSoon, onNavigate, right, inMenu }: NavItemRowProps) {
  const menuProps = inMenu ? ({ role: "menuitem" as const, tabIndex: -1 }) : {};
  if (comingSoon) {
    return (
      <button
        type="button"
        onClick={() => toast.info(NAV_SOON_MSG)}
        title={NAV_SOON_MSG}
        {...menuProps}
        className="focus-ring flex h-10 w-full items-center gap-2.5 rounded-control px-3 text-[13px] text-text-faint transition-colors hover:bg-surface-hover"
      >
        <Icon className="h-[18px] w-[18px] shrink-0 text-text-faint" />
        <span className="flex-1 truncate text-left">{label}</span>
        <span className="rounded-sm bg-surface-hover px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-text-faint">
          yakında
        </span>
      </button>
    );
  }
  return (
    <Link
      to={to}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      {...menuProps}
      className={cn(
        "focus-ring flex h-10 items-center gap-2.5 rounded-control px-3 text-[13px] transition-colors",
        active ? "bg-blue-soft font-semibold text-brand" : "text-text-secondary hover:bg-surface-hover"
      )}
    >
      <Icon className={cn("h-[18px] w-[18px] shrink-0", active ? "text-brand" : "text-text-muted")} />
      <span className="flex-1 truncate">{label}</span>
      {right}
    </Link>
  );
}
