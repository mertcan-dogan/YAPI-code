// CR-044 — Uygulamalar (Beceriler / Skills) list. A skill = a saved, named
// "deliverable recipe" (free-form instruction + a compiled dashboard-shaped plan +
// an output format). This page lists the user's skills and lets them Çalıştır
// (generate the file from live data → download), Düzenle (edit name/instruction/
// visibility — the plan itself is re-authored in the Yapı AI chat), or Sil.
// Mirrors StudioDashboardsPage for table styling, loading/empty/error states and
// the row "…" menu; a failed fetch shows an error+retry, never a silent empty.
import { PageHeader } from "@/components/layout/AppLayout";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge, Button, Modal, MenuItem, RowMenu, Select, Tabs } from "@/components/ui";
import { skills } from "@/lib/api";
import { downloadFromUrl } from "@/lib/download";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { SkillFormat, SkillListItem, SkillOut, SkillRunOut } from "@/types/skill";
import { formatRelativeTime } from "@/utils/format";
import {
  Download,
  FileSpreadsheet,
  FileText,
  History,
  Loader2,
  Lock,
  MoreHorizontal,
  Pencil,
  Play,
  Search,
  Sparkles,
  Trash2,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

function FormatBadge({ format }: { format: SkillFormat }) {
  if (format === "pdf") {
    return (
      <Badge variant="danger">
        <FileText className="h-3 w-3" /> PDF
      </Badge>
    );
  }
  return (
    <Badge variant="success">
      <FileSpreadsheet className="h-3 w-3" /> Excel
    </Badge>
  );
}

function VisibilityChip({ visibility }: { visibility: string }) {
  if (visibility === "company") {
    return (
      <Badge variant="info">
        <Users className="h-3 w-3" /> Herkes
      </Badge>
    );
  }
  return (
    <Badge variant="neutral">
      <Lock className="h-3 w-3" /> Özel
    </Badge>
  );
}

export default function SkillsPage() {
  const navigate = useNavigate();
  const user = useAuth((s) => s.user);
  const [tab, setTab] = useState<"mine" | "all">("mine");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<SkillListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The id of the skill currently running (drives the row's spinner).
  const [runningId, setRunningId] = useState<string | null>(null);
  // The skill being edited in the metadata modal (null = closed).
  const [editing, setEditing] = useState<SkillOut | null>(null);
  // CR-044.1 — the skill whose run history modal is open (null = closed).
  const [historyOf, setHistoryOf] = useState<SkillListItem | null>(null);

  // CR-044.1 — re-download a past run's file: re-sign a short-lived URL (signed URLs
  // expire) via POST /skills/runs/{run_id}/download, then trigger the browser save.
  const reDownload = useCallback(async (runId: string, fileName: string | null) => {
    try {
      const res = await skills.downloadSkillFile(runId);
      downloadFromUrl(res.download_url, res.file_name ?? fileName ?? "beceri");
    } catch (e: any) {
      toast.error(e?.message ?? "Dosya indirilemedi");
    }
  }, []);

  // Debounce the search box → the server-side ?q= filter.
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(() => {
    setLoading(true);
    skills
      .listSkills(q || undefined)
      .then((data) => {
        setItems(data ?? []);
        setError(null);
      })
      .catch((e) => setError(e?.message ?? "Beceriler yüklenemedi."))
      .finally(() => setLoading(false));
  }, [q]);

  useEffect(() => {
    load();
  }, [load]);

  const canEdit = useCallback(
    (row: SkillListItem) => user?.role === "director" || row.owner_id === user?.id,
    [user]
  );

  const rows = useMemo(
    () => (tab === "mine" ? items.filter((s) => s.owner_id === user?.id) : items),
    [items, tab, user]
  );

  // Çalıştır — generate the file from LIVE data, then download it via the signed URL.
  const onRun = async (row: SkillListItem) => {
    if (runningId) return;
    setRunningId(row.id);
    try {
      const res = await skills.runSkill(row.id);
      downloadFromUrl(res.download_url, res.file_name);
      const word = row.format === "pdf" ? "PDF" : "Excel";
      const nowIso = new Date().toISOString();
      // CR-044.1 — explicit "it downloaded, and where" + an İndir to re-open it.
      toast.success(`${word} üretildi ve indirildi — İndirilenler klasörü`, {
        action: { label: "İndir", onClick: () => reDownload(res.run_id, res.file_name) },
      });
      // Reflect the fresh run on the row (son çalıştırma + the per-row İndir) without
      // a full refetch — so the file stays findable immediately, before any reload.
      setItems((prev) =>
        prev.map((s) =>
          s.id === row.id
            ? {
                ...s,
                last_run_at: nowIso,
                last_run: { run_id: res.run_id, run_at: nowIso, file_name: res.file_name, status: "ok" },
              }
            : s
        )
      );
    } catch (e: any) {
      toast.error(e?.message ?? "Beceri çalıştırılamadı");
    } finally {
      setRunningId(null);
    }
  };

  const onEdit = async (row: SkillListItem) => {
    try {
      const full = await skills.getSkill(row.id);
      setEditing(full);
    } catch (e: any) {
      toast.error(e?.message ?? "Beceri yüklenemedi");
    }
  };

  const onDelete = async (row: SkillListItem) => {
    if (!window.confirm(`"${row.name}" becerisini silmek istediğinize emin misiniz?`)) return;
    try {
      await skills.deleteSkill(row.id);
      toast.success("Beceri silindi");
      load();
    } catch (e: any) {
      toast.error(e?.message ?? "Beceri silinemedi");
    }
  };

  const columns: Column<SkillListItem>[] = [
    {
      key: "name",
      header: "Ad",
      render: (row) => (
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control bg-blue-soft text-brand">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <span className="truncate text-[13px] font-semibold text-text-primary">{row.name}</span>
            {row.labels && row.labels.length > 0 && (
              <div className="mt-0.5 flex flex-wrap gap-1">
                {row.labels.map((l) => (
                  <span key={l} className="rounded-sm bg-surface-hover px-1.5 py-px text-[10px] text-text-muted">
                    {l}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      key: "format",
      header: "Biçim",
      render: (row) => <FormatBadge format={row.format} />,
    },
    {
      key: "visibility",
      header: "Görünürlük",
      render: (row) => <VisibilityChip visibility={row.visibility} />,
    },
    {
      key: "last_run_at",
      header: "Son çalıştırma",
      render: (row) => (
        <span className="text-[13px] text-text-muted">
          {row.last_run_at ? formatRelativeTime(row.last_run_at) : "Henüz çalıştırılmadı"}
        </span>
      ),
      sortValue: (row) => row.last_run_at ?? "",
      sortable: true,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (row) => {
        const isRunning = runningId === row.id;
        return (
          <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              onClick={() => onRun(row)}
              disabled={!!runningId}
              aria-label={`Çalıştır: ${row.name}`}
              className="focus-ring inline-flex items-center gap-1 rounded-control border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text-primary transition hover:border-brand hover:text-brand disabled:opacity-50"
            >
              {isRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              {isRunning ? "Çalışıyor…" : "Çalıştır"}
            </button>
            {/* CR-044.1 — re-download the latest produced file (re-signs a fresh URL).
                Shown once the skill has at least one successful run. */}
            {row.last_run && (
              <button
                type="button"
                onClick={() => reDownload(row.last_run!.run_id, row.last_run!.file_name)}
                aria-label={`İndir: ${row.name}`}
                className="focus-ring inline-flex items-center gap-1 rounded-control border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text-primary transition hover:border-brand hover:text-brand"
              >
                <Download className="h-3.5 w-3.5" /> İndir
              </button>
            )}
            <RowMenu
              align="right"
              triggerLabel={`Beceri işlemleri: ${row.name}`}
              trigger={<MoreHorizontal className="h-[18px] w-[18px] text-text-muted" />}
            >
              {(close) => (
                <>
                  {/* CR-044.1 — run history (everyone who can view): every produced
                      file is findable here, not just the latest. */}
                  <MenuItem
                    icon={History}
                    onClick={() => {
                      close();
                      setHistoryOf(row);
                    }}
                  >
                    Çalıştırma geçmişi
                  </MenuItem>
                  {canEdit(row) && (
                    <MenuItem
                      icon={Pencil}
                      onClick={() => {
                        close();
                        onEdit(row);
                      }}
                    >
                      Düzenle
                    </MenuItem>
                  )}
                  {canEdit(row) && (
                    <MenuItem
                      icon={Trash2}
                      danger
                      onClick={() => {
                        close();
                        onDelete(row);
                      }}
                    >
                      Sil
                    </MenuItem>
                  )}
                </>
              )}
            </RowMenu>
          </div>
        );
      },
    },
  ];

  return (
    <div>
      <PageHeader
        title="Uygulamalar"
        subtitle="Yapı AI ile oluşturduğunuz becerileri çalıştırın, düzenleyin ve yönetin."
        breadcrumb="Stüdyo"
      />

      {/* AI hero — becerileri Yapı AI ile sohbette oluşturun. */}
      <button
        type="button"
        onClick={() => navigate("/ai-assistant")}
        className="mb-5 flex w-full items-center gap-3 rounded-card border border-blue-border bg-gradient-to-r from-blue-soft to-purple-soft px-4 py-3 text-left transition-colors hover:brightness-[0.98]"
      >
        <span className="flex h-9 w-9 items-center justify-center rounded-control bg-white text-purple">
          <Sparkles className="h-5 w-5" />
        </span>
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-text-primary">Yapay zekâ ile beceri oluştur</span>
          <span className="block text-xs text-text-secondary">
            Tekrarlayan bir çıktıyı anlatın — Yapı AI bir beceri olarak derlesin.
          </span>
        </span>
      </button>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          tabs={[
            { id: "mine", label: "Becerilerim" },
            { id: "all", label: "Tüm beceriler" },
          ]}
          value={tab}
          onChange={(id) => setTab(id as "mine" | "all")}
        />
        <div className="flex-1" />
        <div className="flex h-9 items-center gap-2 rounded-control border border-border bg-surface px-3 text-sm text-text-secondary">
          <Search className="h-4 w-4 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Beceri ara…"
            aria-label="Beceri ara"
            className="w-40 bg-transparent outline-none placeholder:text-text-faint"
          />
        </div>
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        error={error}
        onRetry={load}
        emptyMessage="Henüz beceri yok — Yapı AI ile sohbette bir beceri oluşturun."
        emptyAction={{ label: "Yapı AI'ya git", onClick: () => navigate("/ai-assistant") }}
      />

      {editing && (
        <EditSkillModal
          skill={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}

      {historyOf && (
        <RunHistoryModal
          skill={historyOf}
          onClose={() => setHistoryOf(null)}
          onDownload={reDownload}
        />
      )}
    </div>
  );
}

// CR-044.1 — Çalıştırma geçmişi: every produced file is findable here (not just the
// latest). Lists each run (run_at · status) with an İndir for successful runs, via
// the existing GET /skills/{id}/runs + POST /skills/runs/{run_id}/download.
function RunHistoryModal({
  skill,
  onClose,
  onDownload,
}: {
  skill: SkillListItem;
  onClose: () => void;
  onDownload: (runId: string, fileName: string | null) => void;
}) {
  const [runs, setRuns] = useState<SkillRunOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    skills
      .listSkillRuns(skill.id)
      .then((data) => alive && setRuns(data ?? []))
      .catch((e) => alive && setError(e?.message ?? "Geçmiş yüklenemedi."));
    return () => {
      alive = false;
    };
  }, [skill.id]);

  return (
    <Modal open onClose={onClose} title={`Çalıştırma geçmişi · ${skill.name}`} size="md">
      <div className="max-h-[60vh] overflow-y-auto">
        {error ? (
          <p className="py-6 text-center text-sm text-danger">{error}</p>
        ) : runs === null ? (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-text-secondary">
            <Loader2 className="h-4 w-4 animate-spin text-brand" /> Yükleniyor…
          </div>
        ) : runs.length === 0 ? (
          <p className="py-8 text-center text-sm text-text-secondary">Bu beceri henüz çalıştırılmadı.</p>
        ) : (
          <ul className="divide-y divide-border">
            {runs.map((run) => (
              <li key={run.id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {run.status === "ok" ? (
                      <Badge variant="success">Başarılı</Badge>
                    ) : (
                      <Badge variant="danger">Hata</Badge>
                    )}
                    <span className="truncate text-[13px] text-text-primary">
                      {formatRelativeTime(run.run_at)}
                    </span>
                  </div>
                  {run.status === "error" && run.error && (
                    <p className="mt-0.5 truncate text-[11px] text-text-muted">{run.error}</p>
                  )}
                </div>
                {run.status === "ok" && (
                  <button
                    type="button"
                    onClick={() => onDownload(run.id, run.file_name)}
                    className="focus-ring inline-flex shrink-0 items-center gap-1 rounded-control border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text-primary transition hover:border-brand hover:text-brand"
                  >
                    <Download className="h-3.5 w-3.5" /> İndir
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}

// Lightweight metadata edit — name, visibility and the free-form instruction. The
// compiled plan is re-authored in the Yapı AI chat ("yeniden yorumla"); this modal
// only edits the recipe's label fields + instruction text.
function EditSkillModal({
  skill,
  onClose,
  onSaved,
}: {
  skill: SkillOut;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(skill.name);
  const [instruction, setInstruction] = useState(skill.instruction);
  const [visibility, setVisibility] = useState<"private" | "company">(
    skill.visibility === "company" ? "company" : "private"
  );
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!name.trim()) {
      toast.error("Beceri adı zorunludur");
      return;
    }
    if (!instruction.trim()) {
      toast.error("Yönerge zorunludur");
      return;
    }
    setBusy(true);
    try {
      await skills.updateSkill(skill.id, {
        name: name.trim(),
        instruction: instruction.trim(),
        visibility,
      });
      toast.success("Beceri güncellendi");
      onSaved();
    } catch (e: any) {
      toast.error(e?.message ?? "Beceri güncellenemedi");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Beceriyi düzenle"
      size="md"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Vazgeç
          </Button>
          <Button onClick={save} loading={busy}>
            Kaydet
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <div>
          <label htmlFor="skill-name" className="mb-1 block text-sm font-medium text-text-secondary">
            Beceri adı
          </label>
          <input
            id="skill-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </div>
        <div>
          <label htmlFor="skill-instruction" className="mb-1 block text-sm font-medium text-text-secondary">
            Yönerge
          </label>
          <textarea
            id="skill-instruction"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={4}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand"
          />
          <p className="mt-1 text-[11px] text-text-faint">
            Planı yeniden derlemek için Yapı AI sohbetinde "yeniden yorumla" deyin.
          </p>
        </div>
        <div>
          <label htmlFor="skill-visibility" className="mb-1 block text-sm font-medium text-text-secondary">
            Görünürlük
          </label>
          <Select
            id="skill-visibility"
            value={visibility}
            onChange={(e) => setVisibility(e.target.value as "private" | "company")}
          >
            <option value="private">Özel</option>
            <option value="company">Herkes</option>
          </Select>
        </div>
      </div>
    </Modal>
  );
}
