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
import type { SkillFormat, SkillListItem, SkillOut } from "@/types/skill";
import { formatRelativeTime } from "@/utils/format";
import {
  FileSpreadsheet,
  FileText,
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
      toast.success("Dosya üretildi");
      // Reflect the fresh run on the list (son çalıştırma) without a full refetch.
      setItems((prev) =>
        prev.map((s) => (s.id === row.id ? { ...s, last_run_at: new Date().toISOString() } : s))
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
            <RowMenu
              align="right"
              triggerLabel={`Beceri işlemleri: ${row.name}`}
              trigger={<MoreHorizontal className="h-[18px] w-[18px] text-text-muted" />}
            >
              {(close) => (
                <>
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
    </div>
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
