// CR-009-B — "Çalışma Alanım": react-grid-layout board.
//
// Cards REORDER by dragging the header; size is set with explicit header controls
// (width presets + height stepper) rather than drag-handles — paced drag-resize
// couldn't be made reliable, and button controls are unambiguous and testable.
// Backend unchanged: layout {x,y,w,h} persists via PUT /workspace/layout. Pinned
// items stay SNAPSHOTS (no re-fetch). Below lg: single read-only column.
import { AgentChart } from "@/components/charts/AgentChart";
import { MarkdownText } from "@/components/MarkdownText";
import { PageHeader } from "@/components/layout/AppLayout";
import { EmptyState, LoadError } from "@/components/EmptyState";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { AgentChartSpec, Citation } from "@/types/agent";
import { formatDate } from "@/utils/format";
import { Minus, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import GridLayout, { WidthProvider, type Layout } from "react-grid-layout";
import "react-grid-layout/css/styles.css";

// Base (non-responsive) grid: its getDerivedStateFromProps reliably re-syncs from
// the `layout` prop whenever it changes (when not mid-drag), so the explicit
// width/height controls reflow the card LIVE. The Responsive wrapper did not pick
// up controlled-`layouts` changes after mount, so a width click only took effect
// on reload. We drive the column count off isDesktop anyway (no breakpoints).
const Grid = WidthProvider(GridLayout);

interface WorkspaceItem {
  id: string;
  title: string;
  item_type: "chart" | "analysis";
  payload: AgentChartSpec | { answer_markdown: string; citations?: Citation[] };
  layout: { x: number; y: number; w: number; h: number } | null;
  pinned_at: string | null;
}

const COLS = 12;
const DEFAULT_W = 6;
const DEFAULT_H = 3;
const MIN_W = 3;
const MIN_H = 2;
const MAX_H = 8;
const ROW_HEIGHT = 80;
const MARGIN_Y = 16;
const PERSIST_DEBOUNCE_MS = 600;

// Width presets → column spans on the 12-col grid.
const WIDTH_PRESETS: { label: string; w: number }[] = [
  { label: "⅓", w: 4 },
  { label: "½", w: 6 },
  { label: "⅔", w: 8 },
  { label: "Tam", w: 12 },
];

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

export default function WorkspacePage() {
  const { data, loading, error, refetch } = useFetch<WorkspaceItem[]>("/workspace/items");
  const [items, setItems] = useState<WorkspaceItem[]>([]);
  const isDesktop = useIsDesktop();

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

  // Resolve every item to a concrete {id,x,y,w,h} (same defaults/clamps as lgLayout).
  const buildPayload = (its: WorkspaceItem[]) =>
    its.map((it, idx) => ({
      id: it.id,
      x: it.layout?.x ?? (idx % 2) * DEFAULT_W,
      y: it.layout?.y ?? Math.floor(idx / 2) * DEFAULT_H,
      w: Math.max(MIN_W, it.layout?.w ?? DEFAULT_W),
      h: Math.max(MIN_H, it.layout?.h ?? DEFAULT_H),
    }));

  const schedulePut = (its: WorkspaceItem[]) => {
    const payload = buildPayload(its);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      apiPut("/workspace/layout", { items: payload }).catch(() => toast.error("Düzen kaydedilemedi"));
    }, PERSIST_DEBOUNCE_MS);
  };

  // Drag-to-reorder: persist the new positions when a drag ends.
  const onDragStop = (layout: Layout[]) => {
    if (!isDesktop) return;
    const byId = new Map(layout.map((l) => [l.i, l]));
    setItems((prev) => {
      const next = prev.map((it) => {
        const l = byId.get(it.id);
        return l ? { ...it, layout: { x: l.x, y: l.y, w: l.w, h: l.h } } : it;
      });
      schedulePut(next);
      return next;
    });
  };

  // Explicit size controls — set width span / step height, then persist.
  const setWidth = (item: WorkspaceItem, w: number) => {
    setItems((prev) => {
      const next = prev.map((it) => {
        if (it.id !== item.id) return it;
        const y = it.layout?.y ?? 0;
        const h = Math.max(MIN_H, it.layout?.h ?? DEFAULT_H);
        const x = Math.max(0, Math.min(it.layout?.x ?? 0, COLS - w)); // keep within the grid
        return { ...it, layout: { x, y, w, h } };
      });
      schedulePut(next);
      return next;
    });
  };

  const setHeight = (item: WorkspaceItem, delta: number) => {
    setItems((prev) => {
      const next = prev.map((it) => {
        if (it.id !== item.id) return it;
        const h = Math.min(MAX_H, Math.max(MIN_H, (it.layout?.h ?? DEFAULT_H) + delta));
        return {
          ...it,
          layout: { x: it.layout?.x ?? 0, y: it.layout?.y ?? 0, w: Math.max(MIN_W, it.layout?.w ?? DEFAULT_W), h },
        };
      });
      schedulePut(next);
      return next;
    });
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
      <PageHeader title="Çalışma Alanım" subtitle="Kartları sürükleyerek sıralayın, boyut düğmeleriyle ayarlayın" />

      {error && !loading ? (
        <div className="rounded-xl border border-border bg-surface shadow-sm"><LoadError onRetry={refetch} /></div>
      ) : !loading && items.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface shadow-sm">
          <EmptyState message="Henüz bir şey sabitlemediniz. Yapı Agent'ta bir grafik veya analiz oluşturup '📌 Sabitle' deyin." />
        </div>
      ) : (
        <Grid
          className="layout"
          // Drive the column count off isDesktop — 12 cols on desktop, a single
          // read-only column below lg. The controlled `layout` reflows the card
          // live when a size control changes it.
          layout={isDesktop ? lgLayout : stackedLayout}
          cols={isDesktop ? COLS : 1}
          rowHeight={ROW_HEIGHT}
          margin={[16, MARGIN_Y]}
          // NOTE: do NOT set measureBeforeMount — in this RGL version it makes
          // WidthProvider's ResizeObserver observe the throwaway placeholder node
          // (the ref moves to the real grid after mount), so it later reports
          // width 0 and the grid stops recomputing pixel widths. Without it, the
          // observer tracks the real grid node and size controls reflow live.
          isDraggable={isDesktop}
          isResizable={false} // sizing is via the explicit header controls
          draggableHandle=".wsp-drag"
          draggableCancel=".wsp-nodrag"
          onDragStop={onDragStop}
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
                  <div className="wsp-nodrag flex shrink-0 items-center gap-1.5">
                    {isDesktop && (
                      <>
                        {/* Width presets → column span */}
                        <div className="flex overflow-hidden rounded-md border border-border">
                          {WIDTH_PRESETS.map((o) => {
                            const active = (it.layout?.w ?? DEFAULT_W) === o.w;
                            return (
                              <button key={o.w} onClick={() => setWidth(it, o.w)} title={`Genişlik: ${o.label}`}
                                aria-label={`Genişlik ${o.label}`} aria-pressed={active}
                                className={`px-1.5 py-0.5 text-[11px] font-medium leading-none ${active ? "bg-brand text-white" : "text-text-secondary hover:bg-navy-50"}`}>
                                {o.label}
                              </button>
                            );
                          })}
                        </div>
                        {/* Height stepper */}
                        <div className="flex items-center rounded-md border border-border">
                          <button onClick={() => setHeight(it, -1)} aria-label="Kısalt"
                            className="px-1 py-0.5 text-text-secondary hover:bg-navy-50 disabled:opacity-30"
                            disabled={(it.layout?.h ?? DEFAULT_H) <= MIN_H}><Minus className="h-3.5 w-3.5" /></button>
                          <span className="min-w-[14px] text-center text-[11px] tabular text-text-secondary">{Math.max(MIN_H, it.layout?.h ?? DEFAULT_H)}</span>
                          <button onClick={() => setHeight(it, 1)} aria-label="Uzat"
                            className="px-1 py-0.5 text-text-secondary hover:bg-navy-50 disabled:opacity-30"
                            disabled={(it.layout?.h ?? DEFAULT_H) >= MAX_H}><Plus className="h-3.5 w-3.5" /></button>
                        </div>
                      </>
                    )}
                    <button onClick={() => rename(it)} aria-label="Yeniden adlandır"
                      className="rounded p-1 text-text-secondary hover:text-brand"><Pencil className="h-4 w-4" /></button>
                    <button onClick={() => remove(it)} aria-label="Kaldır"
                      className="rounded p-1 text-text-secondary hover:text-danger"><Trash2 className="h-4 w-4" /></button>
                  </div>
                </div>
                {/* Charts FILL the cell (scale to the card); long analyses scroll. */}
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
        </Grid>
      )}
    </div>
  );
}
