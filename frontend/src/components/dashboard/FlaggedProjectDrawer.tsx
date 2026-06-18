import { SideDrawer } from "@/components/SideDrawer";
import { Button, Stat } from "@/components/ui";
import { formatPct, toNumber } from "@/utils/format";
import { useNavigate } from "react-router-dom";

// CR-028 §3.2.4: a flagged project opens in a slide-over (read-only quick view)
// instead of a full-page navigation. "Projeyi aç" is the secondary full-page
// affordance. Derived from the dashboard's existing project data — no new call.
export function FlaggedProjectDrawer({ project, onClose }: { project: any | null; onClose: () => void }) {
  const navigate = useNavigate();
  const m = project ? toNumber(project.margin_pct) : 0;
  const tone = m < 5 ? "text-danger" : m < 10 ? "text-warning" : "text-success";
  return (
    <SideDrawer open={!!project} title="Riskli proje" onClose={onClose}>
      {project && (
        <div className="space-y-4">
          <div>
            <div className="text-base font-semibold text-primary">{project.name}</div>
            {project.client_name && <div className="text-sm text-text-secondary">{project.client_name}</div>}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Kar Marjı" value={<span className={tone}>{formatPct(project.margin_pct)}</span>} />
            {project.rag_status && <Stat label="Durum" value={String(project.rag_status).toUpperCase()} />}
          </div>
          <p className="text-caption text-text-secondary">
            Bu proje portföydeki en düşük kar marjına sahip. Ayrıntılar için proje özetini açın.
          </p>
          <Button
            variant="outline"
            onClick={() => {
              onClose();
              navigate(`/projects/${project.id}/dashboard`);
            }}
          >
            Projeyi aç
          </Button>
        </div>
      )}
    </SideDrawer>
  );
}
