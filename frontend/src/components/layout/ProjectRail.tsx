import * as React from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  BarChart3,
  Calculator,
  Coins,
  FileText,
  History,
  PlusSquare,
  TrendingUp,
  Users,
  Wrench,
  X,
} from "lucide-react";
import { cachedGet } from "@/lib/requestCache";
import { useAuth } from "@/store/auth";
import { useProjectStore } from "@/store/project";
import { NavItemRow } from "./NavItemRow";

// CR-038 §A3 — the active-project submenu, moved UNCHANGED out of the old sidebar
// into the contextual left rail. It is STORE-BACKED (useProjectStore): the active
// project comes from the URL on a project page and otherwise from the persisted
// store, so it survives navigation (CR-004-H). Renders nothing when there is no
// active project (the shell then shows no rail on that route).
export const PROJECT_NAV = (id: string) => [
  { icon: BarChart3, label: "Proje Özeti", to: `/projects/${id}/dashboard` },
  { icon: Calculator, label: "Bütçe & Maliyetler", to: `/projects/${id}/budget` },
  { icon: FileText, label: "Faturalar & Hakediş", to: `/projects/${id}/invoices` },
  { icon: Coins, label: "Satışlar & Kar/Zarar", to: `/projects/${id}/sales-pnl` },
  { icon: PlusSquare, label: "Ek İşler", to: `/projects/${id}/variations` },
  { icon: Users, label: "Alt Yükleniciler", to: `/projects/${id}/subcontractors` },
  { icon: TrendingUp, label: "Nakit Akışı", to: `/projects/${id}/cashflow` },
  { icon: Wrench, label: "Ekipman", to: `/projects/${id}/equipment` },
];

export function ProjectRail({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const isDirector = useAuth((s) => s.user?.role === "director");
  const { activeProjectId, activeProjectName, setActiveProject, clearActiveProject } = useProjectStore();
  const [projects, setProjects] = React.useState<{ id: string; name: string; status: string }[]>([]);

  // CR-004-H: the active project comes from the URL on a project page, otherwise
  // from the persisted store — so the submenu survives navigation.
  const effectiveId = params.id ?? activeProjectId ?? undefined;
  const effectiveName = params.id
    ? projects.find((p) => p.id === params.id)?.name ?? activeProjectName ?? "Proje"
    : activeProjectName ?? "Proje";

  React.useEffect(() => {
    cachedGet<{ id: string; name: string; status: string }[]>("/projects")
      .then(({ data }) => setProjects(data ?? []))
      .catch(() => setProjects([]));
  }, [params.id]);

  // Remember the project the user is viewing.
  React.useEffect(() => {
    if (params.id) {
      const p = projects.find((x) => x.id === params.id);
      if (p) setActiveProject(p.id, p.name);
    }
  }, [params.id, projects, setActiveProject]);

  // Auto-clear when the active project is deleted or no longer active.
  React.useEffect(() => {
    if (activeProjectId && projects.length && !projects.some((p) => p.id === activeProjectId && p.status === "active")) {
      clearActiveProject();
    }
  }, [projects, activeProjectId, clearActiveProject]);

  const closeContext = () => {
    clearActiveProject();
    navigate("/projects");
    onNavigate?.();
  };

  if (!effectiveId) return null;

  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between px-3 pb-1">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-text-faint">Aktif Proje</span>
        <button
          onClick={closeContext}
          className="focus-ring rounded-sm text-text-faint hover:text-text-primary"
          aria-label="Proje bağlamını kapat"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <p className="truncate px-3 pb-1 text-[13px] font-semibold text-text-primary" title={effectiveName}>
        {effectiveName}
      </p>
      {PROJECT_NAV(effectiveId).map((n) => (
        <NavItemRow key={n.to} {...n} active={pathname === n.to} onNavigate={onNavigate} />
      ))}
      {isDirector && (
        <NavItemRow
          icon={History}
          label="Denetim İzi"
          to={`/projects/${effectiveId}/audit-log`}
          active={pathname === `/projects/${effectiveId}/audit-log`}
          onNavigate={onNavigate}
        />
      )}
    </div>
  );
}
