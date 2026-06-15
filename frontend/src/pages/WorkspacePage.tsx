// CR-008-D — "Çalışma Alanım": the board of pinned snapshot items.
//
// Dependency note (§0.0 #5 / §5.1): react-grid-layout is declared in package.json
// but is NOT installed in this environment, so per the spec's stated fallback this
// page uses a responsive ordered grid (no new dependency) with move/resize controls
// instead of free drag-drop. Order + width still persist via PUT /workspace/layout,
// so swapping in react-grid-layout later is a drop-in upgrade. Mobile (<lg) renders
// a single-column read-only stack.
import { AgentChart } from "@/components/charts/AgentChart";
import { MarkdownText } from "@/components/MarkdownText";
import { PageHeader } from "@/components/layout/AppLayout";
import { EmptyState, LoadError } from "@/components/EmptyState";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { AgentChartSpec, Citation } from "@/types/agent";
import { formatDate } from "@/utils/format";
import { ArrowDown, ArrowUp, Maximize2, Minimize2, Pencil, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

interface WorkspaceItem {
  id: string;
  title: string;
  item_type: "chart" | "analysis";
  payload: AgentChartSpec | { answer_markdown: string; citations?: Citation[] };
  layout: { x: number; y: number; w: number; h: number } | null;
  pinned_at: string | null;
}

const DEFAULT_W = 6;
const FULL_W = 12;

function sortForDisplay(items: WorkspaceItem[]): WorkspaceItem[] {
  return [...items].sort((a, b) => {
    const ay = a.layout?.y, by = b.layout?.y;
    if (ay != null && by != null) return ay - by;
    if (ay != null) return -1;
    if (by != null) return 1;
    return 0; // both unlaid-out: keep API order (pinned_at desc)
  });
}

export default function WorkspacePage() {
  const { data, loading, error, refetch } = useFetch<WorkspaceItem[]>("/workspace/items");
  const [items, setItems] = useState<WorkspaceItem[]>([]);

  useEffect(() => {
    if (data) setItems(sortForDisplay(data));
  }, [data]);

  // Persist the whole board's order + widths atomically (PUT /workspace/layout).
  const persist = (next: WorkspaceItem[]) => {
    const payload = next.map((it, idx) => ({
      id: it.id, x: 0, y: idx, w: it.layout?.w ?? DEFAULT_W, h: 1,
    }));
    apiPut("/workspace/layout", { items: payload }).catch(() => toast.error("Düzen kaydedilemedi"));
  };

  const move = (index: number, dir: -1 | 1) => {
    const j = index + dir;
    if (j < 0 || j >= items.length) return;
    const next = [...items];
    [next[index], next[j]] = [next[j], next[index]];
    setItems(next);
    persist(next);
  };

  const toggleWidth = (index: number) => {
    const next = items.map((it, i) => {
      if (i !== index) return it;
      const w = (it.layout?.w ?? DEFAULT_W) >= FULL_W ? DEFAULT_W : FULL_W;
      return { ...it, layout: { x: 0, y: i, w, h: 1 } };
    });
    setItems(next);
    persist(next);
  };

  const rename = async (it: WorkspaceItem) => {
    const title = window.prompt("Yeni başlık", it.title);
    if (title == null || !title.trim()) return;
    try {
      await apiPut(`/workspace/items/${it.id}`, { title: title.trim() });
      setItems((prev) => prev.map((x) => (x.id === it.id ? { ...x, title: title.trim() } : x)));
    } catch {
      toast.error("Yeniden adlandırılamadı");
    }
  };

  const remove = async (it: WorkspaceItem) => {
    if (!window.confirm("Bu öğeyi çalışma alanınızdan kaldırmak istiyor musunuz?")) return;
    try {
      await apiDelete(`/workspace/items/${it.id}`);
      setItems((prev) => prev.filter((x) => x.id !== it.id));
      toast.success("Kaldırıldı");
    } catch {
      toast.error("Kaldırılamadı");
    }
  };

  return (
    <div>
      <PageHeader title="Çalışma Alanım" subtitle="Sabitlediğiniz grafikler ve analizler" />

      {error && !loading ? (
        <div className="rounded-xl border border-border bg-surface shadow-sm"><LoadError onRetry={refetch} /></div>
      ) : !loading && items.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface shadow-sm">
          <EmptyState message="Henüz bir şey sabitlemediniz. AI Asistan'da bir grafik veya analiz oluşturup '📌 Sabitle' deyin." />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {items.map((it, i) => {
            const w = it.layout?.w ?? DEFAULT_W;
            const spanClass = w >= FULL_W ? "lg:col-span-12" : "lg:col-span-6";
            return (
              <div key={it.id} className={`rounded-xl border border-border bg-surface p-4 ${spanClass}`}>
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-text-primary">{it.title}</h3>
                    {it.pinned_at && (
                      <p className="text-[11px] text-text-secondary">{formatDate(it.pinned_at)} tarihinde sabitlendi</p>
                    )}
                  </div>
                  {/* Controls — desktop only (mobile board is read-only, §0.2/§5.1). */}
                  <div className="hidden shrink-0 items-center gap-1 lg:flex">
                    <button onClick={() => move(i, -1)} disabled={i === 0} aria-label="Yukarı taşı"
                      className="rounded p-1 text-text-secondary hover:text-brand disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
                    <button onClick={() => move(i, 1)} disabled={i === items.length - 1} aria-label="Aşağı taşı"
                      className="rounded p-1 text-text-secondary hover:text-brand disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
                    <button onClick={() => toggleWidth(i)} aria-label={w >= FULL_W ? "Daralt" : "Genişlet"}
                      className="rounded p-1 text-text-secondary hover:text-brand">
                      {w >= FULL_W ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
                    </button>
                    <button onClick={() => rename(it)} aria-label="Yeniden adlandır"
                      className="rounded p-1 text-text-secondary hover:text-brand"><Pencil className="h-4 w-4" /></button>
                    <button onClick={() => remove(it)} aria-label="Kaldır"
                      className="rounded p-1 text-text-secondary hover:text-danger"><Trash2 className="h-4 w-4" /></button>
                  </div>
                </div>

                {it.item_type === "chart" ? (
                  <AgentChart spec={it.payload as AgentChartSpec} height={240} />
                ) : (
                  <div className="text-sm leading-relaxed text-text-primary">
                    <MarkdownText text={(it.payload as { answer_markdown: string }).answer_markdown} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
