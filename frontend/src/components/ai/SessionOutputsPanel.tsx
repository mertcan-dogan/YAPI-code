import { AgentChart } from "@/components/charts/AgentChart";
import { Select } from "@/components/ui";
import { downloadFromUrl } from "@/lib/download";
import type { AgentChartSpec } from "@/types/agent";
import { Download, FileSpreadsheet, FileText, Pin } from "lucide-react";

// CR-038 §B1 / §7-D — the right panel, reserved as "Oturum Çıktıları" (distinct
// from the /workspace "Çalışma Alanım" page). For now it holds the existing
// "Tuval" canvas (latest chart + pin-to-workspace) and the project filter; the
// full Dema-style workspace panel drops into this same slot in a later CR.
//
// CR-044 — adds a "Üretilen dosyalar" section listing this session's skill-run
// files (newest first) with an İndir per file (the signed download_url). The list
// is session-scoped (not persisted client-side) — the backend skill_runs table is
// the durable record.
interface Project {
  id: string;
  name: string;
}

// A skill-run output to download (sourced from the chat session's run_result cards).
export interface SkillRunOutput {
  run_id: string;
  file_name: string;
  format: "xlsx" | "pdf";
  download_url: string;
}

interface Props {
  latestChart: AgentChartSpec | null;
  canPin: boolean;
  onPin: () => void;
  onViewWorkspace: () => void;
  projectId: string;
  onProjectChange: (id: string) => void;
  projects: Project[];
  // CR-044 — this session's generated files (newest first), or empty.
  skillRuns?: SkillRunOutput[];
}

export function SessionOutputsPanel({
  latestChart,
  canPin,
  onPin,
  onViewWorkspace,
  projectId,
  onProjectChange,
  projects,
  skillRuns = [],
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

      {/* CR-044 — Üretilen dosyalar (generated files this session) */}
      <div>
        <div className="mb-2 text-sm font-medium text-text-secondary">Üretilen dosyalar</div>
        {skillRuns.length > 0 ? (
          <ul className="space-y-1.5">
            {skillRuns.map((r) => (
              <li
                key={r.run_id}
                className="flex items-center gap-2 rounded-control border border-border bg-surface px-2.5 py-1.5"
              >
                {r.format === "pdf" ? (
                  <FileText className="h-4 w-4 shrink-0 text-danger" />
                ) : (
                  <FileSpreadsheet className="h-4 w-4 shrink-0 text-success" />
                )}
                <span className="min-w-0 flex-1 truncate text-xs text-text-primary" title={r.file_name}>
                  {r.file_name}
                </span>
                <button
                  type="button"
                  onClick={() => r.download_url && downloadFromUrl(r.download_url, r.file_name)}
                  disabled={!r.download_url}
                  aria-label={`İndir: ${r.file_name}`}
                  className="focus-ring inline-flex shrink-0 items-center gap-1 rounded-sm text-[11px] font-medium text-brand transition hover:underline disabled:opacity-50"
                >
                  <Download className="h-3 w-3" /> İndir
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-card border border-dashed border-border bg-surface p-4 text-xs text-text-secondary">
            Bir beceri çalıştırdığınızda üretilen dosyalar burada listelenir.
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
