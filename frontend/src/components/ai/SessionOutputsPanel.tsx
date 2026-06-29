import { AgentChart } from "@/components/charts/AgentChart";
import { Select } from "@/components/ui";
import type { AgentChartSpec } from "@/types/agent";
import { Pin } from "lucide-react";

// CR-038 §B1 / §7-D — the right panel, reserved as "Oturum Çıktıları" (distinct
// from the /workspace "Çalışma Alanım" page). For now it holds the existing
// "Tuval" canvas (latest chart + pin-to-workspace) and the project filter; the
// full Dema-style workspace panel drops into this same slot in a later CR.
interface Project {
  id: string;
  name: string;
}

interface Props {
  latestChart: AgentChartSpec | null;
  canPin: boolean;
  onPin: () => void;
  onViewWorkspace: () => void;
  projectId: string;
  onProjectChange: (id: string) => void;
  projects: Project[];
}

export function SessionOutputsPanel({
  latestChart,
  canPin,
  onPin,
  onViewWorkspace,
  projectId,
  onProjectChange,
  projects,
}: Props) {
  return (
    <div className="space-y-5 p-4">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-text-faint">Oturum Çıktıları</div>

      {/* Tuval (Canvas) */}
      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-text-secondary">Tuval</span>
          <div className="flex items-center gap-2">
            <button onClick={onViewWorkspace} className="focus-ring rounded-sm text-[11px] font-medium text-brand hover:underline">
              Görüntüle
            </button>
            <button
              type="button"
              onClick={onPin}
              disabled={!canPin}
              className="focus-ring inline-flex items-center gap-1 rounded-control border border-border bg-surface px-2 py-1 text-xs font-medium text-text-primary transition hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Pin className="h-3 w-3" /> Çalışma Alanıma Ekle
            </button>
          </div>
        </div>
        {latestChart ? (
          <AgentChart spec={latestChart} height={240} />
        ) : (
          <p className="rounded-card border border-dashed border-border bg-surface p-4 text-xs text-text-secondary">
            Bir analiz veya grafik istediğinizde burada görünecek.
          </p>
        )}
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-text-secondary">Proje Filtresi</label>
        <Select value={projectId} onChange={(e) => onProjectChange(e.target.value)}>
          <option value="">Tüm Projeler</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
      </div>
    </div>
  );
}
