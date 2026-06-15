// CR-009-B — "Çalışma Alanım": real drag-and-drop / resizable board.
//
// Upgrades the CR-008 fallback ordered grid to react-grid-layout. Backend is
// unchanged: layout {x,y,w,h} still persists via PUT /workspace/layout. Pinned
// items stay SNAPSHOTS (no re-fetch). Below lg the board collapses to a single
// read-only column (drag/resize disabled), preserving CR-008 behaviour.
import { AgentChart } from "@/components/charts/AgentChart";
import { MarkdownText } from "@/components/MarkdownText";
import { PageHeader } from "@/components/layout/AppLayout";
import { EmptyState, LoadError } from "@/components/EmptyState";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { AgentChartSpec, Citation } from "@/types/agent";
import { formatDate } from "@/utils/format";
import { Pencil, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Responsive, WidthProvider, type Layout } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const ResponsiveGridLayout = WidthProvider(Responsive);

interface WorkspaceItem {
  id: string;
  title: string;
  item_type: "chart" | "analysis";
  payload: AgentChartSpec | { answer_markdown: string; citations?: Citation[] };
  layout: { x: number; y: number; w: number; h: number } | null;
  pinned_at: string | null;
}

const DEFAULT_W = 6;
const DEFAULT_H = 3;
const MIN_W = 3;
const MIN_H = 2;
const ROW_HEIGHT = 80;
const MARGIN_Y = 16;
const PERSIST_DEBOUNCE_MS = 600;

function useIsDesktop(): boolean {
  const query = "(min-width: 1024px)";
  const [desktop, setDesktop] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia && window.matchMedia(query).matches
  );
  useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia(query);
    const onChange = () => setDesktop(mq.matches);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);
  return desktop;
}

const layoutSig = (l: Layout[]) =>
  JSON.stringify([...l].map((x) => [x.i, x.x, x.y, x.w, x.h]).sort());

export default function WorkspacePage() {
  const { data, loading, error, refetch } = useFetch<WorkspaceItem[]>("/workspace/items");
  const [items, setItems] = useState<WorkspaceItem[]>([]);
  const isDesktop = useIsDesktop();

  const lastSig = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (data) setItems(data);
  }, [data]);

  useEffect(() => () => clearTimeout(timer.current), []);

  // 12-col desktop layout: respect saved {x,y,w,h}; flow null-layout items in.
  const lgLayout: Layout[] = useMemo(
    () =>
      items.map((it, idx) => ({
        i: it.id,
        x: it.layout?.x ?? (idx % 2) * DEFAULT_W,
        y: it.layout?.y ?? Math.floor(idx / 2) * DEFAULT_H,
        // Clamp to the minimums — legacy CR-008 items were saved with h=1.
        w: Math.max(MIN_W, it.layout?.w ?? DEFAULT_W),
        h: Math.max(MIN_H, it.layout?.h ?? DEFAULT_H),
        minW: MIN_W,
        minH: MIN_H,
      })),
    [items]
  );
  // Single-column stack for small screens (read-only).
  const stackedLayout: Layout[] = useMemo(
    () => items.map((it, idx) => ({ i: it.id, x: 0, y: idx * DEFAULT_H, w: 1, h: Math.max(MIN_H, it.layout?.h ?? DEFAULT_H), minW: 1, minH: MIN_H })),
    [items]
  );

  // Seed the signature from the rendered layout so the mount onLayoutChange is a
  // no-op; only genuine drag/resize then persists.
  useEffect(() => {
    if (lastSig.current === null && items.length) lastSig.current = layoutSig(lgLayout);
  }, [items.length, lgLayout]);

  const onLayoutChange = (layout: Layout[]) => {
    // Don't let the mobile (1-col) layout overwrite the saved desktop layout.
    if (!isDesktop) return;
    const sig = layoutSig(layout);
    if (sig === lastSig.current) return;
    lastSig.current = sig;

    // Keep items state in sync with the new positions/sizes.
    const byId = new Map(layout.map((l) => [l.i, l]));
    setItems((prev) =>
      prev.map((it) => {
        const l = byId.get(it.id);
        return l ? { ...it, layout: { x: l.x, y: l.y, w: l.w, h: l.h } } : it;
      })
    );

    const payload = layout.map((l) => ({ id: l.i, x: l.x, y: l.y, w: l.w, h: l.h }));
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      apiPut("/workspace/layout", { items: payload }).catch(() => toast.error("Düzen kaydedilemedi"));
    }, PERSIST_DEBOUNCE_MS);
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
      <PageHeader title="Çalışma Alanım" subtitle="Sabitlediğiniz grafikler ve analizler — sürükleyip yeniden boyutlandırın" />

      {error && !loading ? (
        <div className="rounded-xl border border-border bg-surface shadow-sm"><LoadError onRetry={refetch} /></div>
      ) : !loading && items.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface shadow-sm">
          <EmptyState message="Henüz bir şey sabitlemediniz. Yapı Agent'ta bir grafik veya analiz oluşturup '📌 Sabitle' deyin." />
        </div>
      ) : (
        <ResponsiveGridLayout
          className="layout"
          // Drive the column count off isDesktop, NOT RGL's container-width
          // breakpoints — a narrow content area (sidebar + small window) would
          // otherwise collapse to 1 column and block width resizing. A single
          // always-active breakpoint (width 0) gives 12 cols on desktop (so the
          // east/corner handles work) and 1 col read-only on mobile.
          layouts={{ lg: isDesktop ? lgLayout : stackedLayout }}
          breakpoints={{ lg: 0 }}
          cols={{ lg: isDesktop ? 12 : 1 }}
          rowHeight={ROW_HEIGHT}
          margin={[16, MARGIN_Y]}
          measureBeforeMount
          isDraggable={isDesktop}
          isResizable={isDesktop}
          draggableHandle=".wsp-drag"
          draggableCancel=".wsp-nodrag"
          resizeHandles={["se", "e", "s"]}
          onLayoutChange={onLayoutChange}
        >
          {items.map((it) => {
            const isChart = it.item_type === "chart";
            return (
              <div key={it.id} className="flex flex-col overflow-hidden rounded-xl border border-border bg-surface">
                <div className={`flex items-start justify-between gap-2 border-b border-border px-3 py-2 ${isDesktop ? "wsp-drag cursor-move" : ""}`}>
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-text-primary">{it.title}</h3>
                    {it.pinned_at && (
                      <p className="text-[11px] text-text-secondary">{formatDate(it.pinned_at)} tarihinde sabitlendi</p>
                    )}
                  </div>
                  <div className="wsp-nodrag flex shrink-0 items-center gap-1">
                    <button onClick={() => rename(it)} aria-label="Yeniden adlandır"
                      className="rounded p-1 text-text-secondary hover:text-brand"><Pencil className="h-4 w-4" /></button>
                    <button onClick={() => remove(it)} aria-label="Kaldır"
                      className="rounded p-1 text-text-secondary hover:text-danger"><Trash2 className="h-4 w-4" /></button>
                  </div>
                </div>
                {/* Charts FILL the cell (no inner scrollbar); long analyses scroll. */}
                <div className={`min-h-0 flex-1 p-2 ${isChart ? "overflow-hidden" : "overflow-auto"}`}>
                  {isChart ? (
                    <AgentChart spec={it.payload as AgentChartSpec} fill />
                  ) : (
                    <div className="text-sm leading-relaxed text-text-primary">
                      <MarkdownText text={(it.payload as { answer_markdown: string }).answer_markdown} />
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </ResponsiveGridLayout>
      )}
    </div>
  );
}
