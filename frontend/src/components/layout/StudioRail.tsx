import { useLocation } from "react-router-dom";
import { BarChart3, LayoutDashboard, Sparkles, Users } from "lucide-react";
import { NavItemRow } from "./NavItemRow";

// CR-038 §A3 — thin Studio sub-rail (the slot is established now; a richer
// version lands in a later CR). Store-free, route-driven — rendered directly by
// the shell on /studio/* routes.
const STUDIO_NAV = [
  { icon: BarChart3, label: "Rapor Stüdyosu", to: "/studio/reports" },
  { icon: LayoutDashboard, label: "Panolar", to: "/studio/dashboards" },
  { icon: Users, label: "Segmentler", to: "#segments", comingSoon: true },
  { icon: Sparkles, label: "Yapı AI", to: "/ai-assistant" },
];

export function StudioRail({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();
  return (
    <div className="space-y-0.5">
      <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wide text-text-faint">Rapor Stüdyosu</div>
      {STUDIO_NAV.map((n) => (
        <NavItemRow
          key={n.to}
          {...n}
          active={!n.comingSoon && (n.to === "/ai-assistant" ? pathname.startsWith(n.to) : pathname === n.to)}
          onNavigate={onNavigate}
        />
      ))}
    </div>
  );
}
