// CR-019-C — "Aşamalar & Kilometre Taşları" (schedule lane).
//
// A condensed Proje Özeti card showing the weighted schedule-progress bar, the
// next deadline and an overdue badge (all from the CR-019-B dashboard milestones
// block). Clicking it opens a manager modal to add/edit/complete/reorder
// milestones grouped by stage, with overdue rows highlighted red. CRUD uses the
// CR-019-A endpoints. SCHEDULE LANE ONLY (§0.2) — no money figures here.
import { LoadError } from "@/components/EmptyState";
import { Button, Input, Label, Modal, Select, Skeleton } from "@/components/ui";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiPost, apiPut } from "@/lib/api";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import { formatDate, formatPct, toNumber } from "@/utils/format";
import { AlertTriangle, ArrowDown, ArrowUp, CalendarClock, CheckCircle2, ListChecks, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";

export interface MilestoneStageRollup {
  stage: string | null;
  progress_pct: string | null;
  done: number;
  total: number;
  deadline: string | null;
}

export interface MilestonesBlock {
  schedule_progress_pct: string | null;
  total: number;
  done: number;
  next_deadline: string | null;
  overdue_count: number;
  by_stage: MilestoneStageRollup[];
}

interface Milestone {
  id: string;
  project_id: string;
  title: string;
  stage: string | null;
  planned_date: string | null;
  weight: string;
  status: string;
  completed_date: string | null;
  sort_order: number;
  notes: string | null;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "Beklemede",
  in_progress: "Devam ediyor",
  done: "Tamamlandı",
};

const todayISO = () => new Date().toISOString().slice(0, 10);

function isOverdue(m: Milestone): boolean {
  return m.status !== "done" && !!m.planned_date && m.planned_date < todayISO();
}

/** The Proje Özeti card — summary + opens the manager. */
export function MilestonesCard({ projectId, block, canManage, onChanged }: {
  projectId: string;
  block?: MilestonesBlock;
  canManage: boolean;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const total = block?.total ?? 0;
  const done = block?.done ?? 0;
  const progress = block?.schedule_progress_pct != null ? toNumber(block.schedule_progress_pct) : null;
  const overdue = block?.overdue_count ?? 0;

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(true)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(true); } }}
        className="group mt-4 cursor-pointer rounded-xl border border-border bg-surface shadow-sm transition-colors hover:border-brand focus:border-brand focus:outline-none"
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <span className="flex items-center gap-1.5 text-sm font-semibold text-primary">
            <ListChecks className="h-4 w-4 text-brand" /> Aşamalar & Kilometre Taşları
          </span>
          <div className="flex items-center gap-2">
            {overdue > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-danger">
                <AlertTriangle className="h-3 w-3" /> {overdue} gecikmiş
              </span>
            )}
            <span className="hidden items-center text-[11px] font-medium text-brand opacity-0 transition-opacity group-hover:opacity-100 sm:inline-flex">Yönet →</span>
          </div>
        </div>

        {total === 0 ? (
          <p className="px-4 py-4 text-sm text-text-secondary">
            Henüz kilometre taşı eklenmedi.{canManage ? " Aşamaları ve kilometre taşlarını eklemek için tıklayın." : ""}
          </p>
        ) : (
          <div className="space-y-2 p-4">
            <div className="flex items-center justify-between text-xs">
              <span className="text-text-secondary">Takvim İlerlemesi (ağırlıklı)</span>
              <span className="tabular font-medium text-text-primary">{progress == null ? "—" : formatPct(progress)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-bg">
              <div className="h-full rounded-full bg-brand" style={{ width: `${progress == null ? 0 : Math.max(0, Math.min(100, progress))}%` }} />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-secondary">
              <span>{done} / {total} tamamlandı</span>
              <span className="inline-flex items-center gap-1">
                <CalendarClock className="h-3.5 w-3.5" />
                {block?.next_deadline ? `Sıradaki: ${formatDate(block.next_deadline)}` : "Yaklaşan son tarih yok"}
              </span>
            </div>
          </div>
        )}
      </div>

      <Modal open={open} title="Aşamalar & Kilometre Taşları" onClose={() => setOpen(false)} size="lg">
        <MilestonesManager projectId={projectId} canManage={canManage} onChanged={onChanged} />
      </Modal>
    </>
  );
}

/** The manager body — live list (its own fetch) + CRUD. */
function MilestonesManager({ projectId, canManage, onChanged }: { projectId: string; canManage: boolean; onChanged: () => void }) {
  const { data, loading, error, refetch } = useFetch<Milestone[]>(`/projects/${projectId}/milestones`);
  const ordered = data ?? [];

  const empty = { title: "", stage: "", planned_date: "", weight: "1", status: "pending" };
  const [form, setForm] = useState(empty);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: string) => setForm((s) => ({ ...s, [k]: v }));

  const reload = () => { refetch(); onChanged(); };

  const startEdit = (m: Milestone) => {
    setEditingId(m.id);
    setForm({
      title: m.title,
      stage: m.stage ?? "",
      planned_date: m.planned_date ?? "",
      weight: m.weight ?? "1",
      status: m.status,
    });
  };
  const cancelEdit = () => { setEditingId(null); setForm(empty); };

  const save = async () => {
    if (!form.title.trim()) { toast.error("Başlık zorunludur"); return; }
    setSaving(true);
    try {
      const body = {
        title: form.title.trim(),
        stage: form.stage.trim() || null,
        planned_date: form.planned_date || null,
        weight: form.weight || "1",
        status: form.status,
      };
      if (editingId) await apiPut(`/projects/${projectId}/milestones/${editingId}`, body);
      else await apiPost(`/projects/${projectId}/milestones`, body);
      toast.success(editingId ? "Kilometre taşı güncellendi" : "Kilometre taşı eklendi");
      cancelEdit();
      reload();
    } catch (e: any) {
      toast.error(e?.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const setStatus = async (m: Milestone, status: string) => {
    try {
      await apiPut(`/projects/${projectId}/milestones/${m.id}`, { status });
      reload();
    } catch (e: any) {
      toast.error(e?.message ?? "Güncellenemedi");
    }
  };

  const remove = async (m: Milestone) => {
    if (!window.confirm(`"${m.title}" kilometre taşını silmek istediğinize emin misiniz?`)) return;
    try {
      await apiDelete(`/projects/${projectId}/milestones/${m.id}`);
      toast.success("Kilometre taşı silindi");
      if (editingId === m.id) cancelEdit();
      reload();
    } catch (e: any) {
      toast.error(e?.message ?? "Silinemedi");
    }
  };

  // Reorder via sort_order: swap with the adjacent milestone in the flat list.
  const move = async (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= ordered.length) return;
    const arr = [...ordered];
    [arr[idx], arr[j]] = [arr[j], arr[idx]];
    try {
      await apiPut(`/projects/${projectId}/milestones/reorder`, { items: arr.map((m, i) => ({ id: m.id, sort_order: i })) });
      reload();
    } catch (e: any) {
      toast.error(e?.message ?? "Sıralama kaydedilemedi");
    }
  };

  // Group by stage, preserving the (sort_order) sequence.
  const groups: { stage: string | null; items: Milestone[] }[] = [];
  const indexOfId = new Map(ordered.map((m, i) => [m.id, i]));
  for (const m of ordered) {
    const key = m.stage && m.stage.trim() ? m.stage : null;
    let g = groups.find((x) => x.stage === key);
    if (!g) { g = { stage: key, items: [] }; groups.push(g); }
    g.items.push(m);
  }

  return (
    <div className="space-y-4">
      {canManage && (
        <div className="rounded-lg border border-border bg-bg p-3">
          <div className="mb-2 text-xs font-semibold text-text-secondary">
            {editingId ? "Kilometre Taşını Düzenle" : "Yeni Kilometre Taşı"}
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div className="sm:col-span-2"><Label required>Başlık</Label><Input value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="örn. Temel betonu döküldü" /></div>
            <div><Label>Aşama</Label><Input value={form.stage} onChange={(e) => set("stage", e.target.value)} placeholder="örn. Kaba İnşaat" /></div>
            <div><Label>Son Tarih</Label><Input type="date" value={form.planned_date} onChange={(e) => set("planned_date", e.target.value)} /></div>
            <div><Label>Ağırlık</Label><Input type="number" min="0" step="0.5" value={form.weight} onChange={(e) => set("weight", e.target.value)} /></div>
            <div><Label>Durum</Label>
              <Select value={form.status} onChange={(e) => set("status", e.target.value)}>
                {Object.entries(STATUS_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </Select>
            </div>
          </div>
          <div className="mt-2 flex justify-end gap-2">
            {editingId && <Button variant="ghost" onClick={cancelEdit}>İptal</Button>}
            <Button onClick={save} loading={saving}><Plus className="h-4 w-4" /> {editingId ? "Güncelle" : "Ekle"}</Button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
      ) : error ? (
        <LoadError message="Kilometre taşları yüklenemedi." onRetry={refetch} />
      ) : ordered.length === 0 ? (
        <p className="py-6 text-center text-sm text-text-secondary">Henüz kilometre taşı yok.</p>
      ) : (
        <div className="space-y-4">
          {groups.map((g) => (
            <div key={g.stage ?? "__none__"}>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-secondary">{g.stage ?? "Aşamasız"}</div>
              <div className="space-y-1.5">
                {g.items.map((m) => {
                  const overdue = isOverdue(m);
                  const flatIdx = indexOfId.get(m.id)!;
                  const isDone = m.status === "done";
                  return (
                    <div
                      key={m.id}
                      className={cn(
                        "flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm",
                        overdue ? "border-danger/40 bg-red-50" : "border-border bg-surface"
                      )}
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={cn("truncate font-medium", isDone ? "text-text-secondary line-through" : "text-text-primary")} title={m.title}>{m.title}</span>
                          <span className="shrink-0 rounded bg-navy-50 px-1.5 py-0.5 text-[10px] text-brand" title="Ağırlık">×{toNumber(m.weight)}</span>
                        </div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px]">
                          <span className={cn(overdue ? "font-medium text-danger" : "text-text-secondary")}>
                            {m.planned_date ? formatDate(m.planned_date) : "Tarihsiz"}{overdue ? " · gecikmiş" : ""}
                          </span>
                          <span className="text-text-disabled">·</span>
                          <span className="text-text-secondary">{STATUS_LABELS[m.status] ?? m.status}</span>
                        </div>
                      </div>

                      {canManage && (
                        <div className="flex shrink-0 items-center gap-0.5">
                          <button onClick={() => move(flatIdx, -1)} disabled={flatIdx === 0} aria-label="Yukarı taşı" className="rounded p-1 text-text-secondary hover:text-primary disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
                          <button onClick={() => move(flatIdx, 1)} disabled={flatIdx === ordered.length - 1} aria-label="Aşağı taşı" className="rounded p-1 text-text-secondary hover:text-primary disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
                          {isDone ? (
                            <button onClick={() => setStatus(m, "pending")} aria-label="Geri al" title="Tamamlamayı geri al" className="rounded p-1 text-text-secondary hover:text-warning"><RotateCcw className="h-4 w-4" /></button>
                          ) : (
                            <button onClick={() => setStatus(m, "done")} aria-label="Tamamla" title="Tamamlandı işaretle" className="rounded p-1 text-text-secondary hover:text-success"><CheckCircle2 className="h-4 w-4" /></button>
                          )}
                          <button onClick={() => startEdit(m)} aria-label="Düzenle" className="rounded p-1 text-text-secondary hover:text-primary"><Pencil className="h-4 w-4" /></button>
                          <button onClick={() => remove(m)} aria-label="Sil" className="rounded p-1 text-text-secondary hover:text-danger"><Trash2 className="h-4 w-4" /></button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
