// CR-034 — Pano (dashboard) canvas. Handles BOTH /studio/dashboards/new (no id)
// and /studio/dashboards/:id. A pano is a react-grid-layout canvas of widgets
// (KPI / Grafik / Tablo / Metin / Rapordan widget) grouped into labelled section
// bands, with a dashboard-global date range + comparison + filters that flow into
// every widget (a widget's own spec overrides the global — mirrors the backend's
// _global_merge). Widgets render from one POST /studio/dashboards/{id}/run batch
// on the first load of a SAVED pano; while editing (unsaved doc, after add/edit,
// or per-widget retry) each widget runs via POST /studio/run with the global
// settings merged in so the preview reflects unsaved changes immediately.
//
// Loading / error / empty are handled PER WIDGET (skeleton while loading, an
// explicit error+retry on failure, a "configure" prompt for an empty data widget,
// and a "Bu rapor artık kullanılamıyor" placeholder for an unavailable report
// widget) — a failed run never renders as a silent empty widget. AI authoring
// (propose_dashboard / "Bu pano hakkında sor") is CR-035 → rendered disabled.
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, LoadError } from "@/components/EmptyState";
import { KPICard } from "@/components/KPICard";
import { MarkdownText } from "@/components/MarkdownText";
import {
  CatalogPicker,
  DeltaText,
  PresetMenu,
  Segmented,
  StudioChart,
  ToggleRow,
  WindowTag,
  formatMetricValue,
} from "@/components/StudioChart";
import { Badge, Button, Menu, MenuItem, Modal, Skeleton, Tabs } from "@/components/ui";
import { studio } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type {
  CatalogMetric,
  DateWindow,
  ReportListItem,
  RunResult,
  RunRow,
  StudioCatalog,
  StudioFilter,
  StudioSpec,
  Visibility,
  Viz,
  Widget,
} from "@/types/studio";
import {
  ArrowLeft,
  CalendarRange,
  ExternalLink,
  Filter,
  GripVertical,
  LayoutList,
  MessageSquare,
  MoreVertical,
  Pencil,
  Plus,
  Save,
  Search,
  Trash2,
  Type as TypeIcon,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import GridLayout, { WidthProvider, type Layout } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

// Base (non-responsive) grid wrapped in WidthProvider — its
// getDerivedStateFromProps re-syncs from the `layout` prop reliably (see the
// WorkspacePage note). One grid per section band; column count is driven off
// isDesktop (12 cols desktop, 1-col read-only stack below lg).
const Grid = WidthProvider(GridLayout);

const COLS = 12;
const ROW_HEIGHT = 76;

// Default cell size per widget type when first added (12-col grid units).
const DEFAULT_DIMS: Record<Widget["type"], { w: number; h: number }> = {
  kpi: { w: 3, h: 2 },
  chart: { w: 6, h: 4 },
  table: { w: 6, h: 4 },
  text: { w: 4, h: 3 },
  report: { w: 6, h: 4 },
};

const BLANK_SPEC: StudioSpec = {
  metrics: [],
  dimensions: [],
  viz: "table",
  basis: { cost: "actual", currency: "try", financing: "excl", vat: "excl" },
  comparison_unit: "pct",
};

const DATE_PRESETS: { id: string | null; label: string }[] = [
  { id: null, label: "Tüm zamanlar" },
  { id: "this_month", label: "Bu ay" },
  { id: "last_month", label: "Geçen ay" },
  { id: "last_3_months", label: "Son 3 ay" },
  { id: "last_6_months", label: "Son 6 ay" },
  { id: "last_12_months", label: "Son 12 ay" },
  { id: "ytd", label: "Bu yıl" },
  { id: "last_year", label: "Geçen yıl" },
];

const VIZ_LABELS: { id: Viz; label: string }[] = [
  { id: "line", label: "Çizgi" },
  { id: "area", label: "Alan" },
  { id: "bar", label: "Çubuk" },
  { id: "kpi", label: "KPI" },
  { id: "table", label: "Tablo" },
];

// react-grid-layout type → widget envelope type (kpi/table keep their own; the
// chart family all map to the "chart" envelope, like the report editor's viz).
const typeForViz = (viz: Viz): Widget["type"] => (viz === "kpi" ? "kpi" : viz === "table" ? "table" : "chart");

function newId(): string {
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  } catch {
    /* fall through */
  }
  return `w-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

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

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Per-widget render state. Exactly one of {loading,error,empty,unavailable,result}.
type WState = {
  loading?: boolean;
  error?: string | null;
  empty?: boolean;
  unavailable?: boolean;
  result?: RunResult;
};

// Resolved target of a report widget (its spec/title) or an "unavailable" marker.
type ReportInfo = { title: string; spec: StudioSpec } | { unavailable: true };

type DashMeta = {
  id: string;
  owner_id: string;
  is_owner: boolean;
  created_at: string;
  updated_at: string;
};

// --------------------------------------------------------------------------- #
// Section band — one react-grid-layout grid per section label.
// --------------------------------------------------------------------------- #
function SectionGrid({
  items,
  isDesktop,
  editable,
  onPersist,
  renderItem,
}: {
  items: Widget[];
  isDesktop: boolean;
  editable: boolean;
  onPersist: (layout: Layout[]) => void;
  renderItem: (w: Widget) => ReactNode;
}) {
  const layout: Layout[] = items.map((w, i) => ({
    i: w.id,
    x: w.layout?.x ?? (i % 2) * 6,
    y: w.layout?.y ?? Math.floor(i / 2) * 4,
    w: Math.max(2, w.layout?.w ?? 6),
    h: Math.max(2, w.layout?.h ?? 4),
    minW: 2,
    minH: 2,
  }));
  const stacked: Layout[] = items.map((w, i) => ({
    i: w.id,
    x: 0,
    y: i * 4,
    w: 1,
    h: Math.max(2, w.layout?.h ?? 4),
    minW: 1,
    minH: 2,
  }));
  return (
    <Grid
      className="layout"
      layout={isDesktop ? layout : stacked}
      cols={isDesktop ? COLS : 1}
      rowHeight={ROW_HEIGHT}
      margin={[14, 14]}
      isDraggable={isDesktop && editable}
      isResizable={isDesktop && editable}
      draggableHandle=".pano-drag"
      draggableCancel=".pano-nodrag"
      onDragStop={onPersist}
      onResizeStop={onPersist}
    >
      {items.map((w) => (
        <div key={w.id}>{renderItem(w)}</div>
      ))}
    </Grid>
  );
}

// --------------------------------------------------------------------------- #
// Widget config modal (kpi/chart/table) — the SAME Veri/Grafik config the report
// editor uses, scoped to one widget's spec.
// --------------------------------------------------------------------------- #
function WidgetConfigModal({
  catalog,
  widget,
  isNew,
  onApply,
  onClose,
}: {
  catalog: StudioCatalog;
  widget: Widget;
  isNew: boolean;
  onApply: (w: Widget) => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(widget.title);
  const [section, setSection] = useState(widget.section ?? "");
  const [spec, setSpec] = useState<StudioSpec>({ ...BLANK_SPEC, ...widget.spec });
  const [tab, setTab] = useState("veri");

  const dimById = useMemo(() => new Map(catalog.dimensions.map((d) => [d.id, d])), [catalog]);

  const patchSpec = (p: Partial<StudioSpec>) => setSpec((s) => ({ ...s, ...p }));
  const patchBasis = (p: Partial<NonNullable<StudioSpec["basis"]>>) =>
    setSpec((s) => ({ ...s, basis: { ...s.basis, ...p } }));
  const patchChart = (p: Partial<NonNullable<StudioSpec["chart"]>>) =>
    setSpec((s) => ({ ...s, chart: { ...s.chart, ...p } }));
  const toggleMetric = (mid: string) =>
    setSpec((s) => ({ ...s, metrics: s.metrics.includes(mid) ? s.metrics.filter((x) => x !== mid) : [...s.metrics, mid] }));
  const toggleDimension = (did: string) =>
    setSpec((s) => ({ ...s, dimensions: s.dimensions.includes(did) ? s.dimensions.filter((x) => x !== did) : [...s.dimensions, did] }));

  const apply = () => {
    if (spec.metrics.length === 0) {
      toast.error("En az bir metrik seçin.");
      return;
    }
    onApply({
      ...widget,
      type: typeForViz(spec.viz),
      title: title.trim() || "Adsız widget",
      section: section.trim() || null,
      spec,
      report_id: undefined,
      content: undefined,
    });
  };

  return (
    <Modal
      open
      title={isNew ? "Widget ekle" : "Widget'ı düzenle"}
      onClose={onClose}
      size="xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            İptal
          </Button>
          <Button onClick={apply}>Uygula</Button>
        </>
      }
    >
      <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div>
          <div className="mb-1 text-[11px] font-semibold text-text-secondary">Başlık</div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            aria-label="Widget başlığı"
            className="w-full rounded-control border border-border bg-surface px-2.5 py-1.5 text-sm outline-none focus:border-brand"
          />
        </div>
        <div>
          <div className="mb-1 text-[11px] font-semibold text-text-secondary">Bölüm (opsiyonel)</div>
          <input
            value={section}
            onChange={(e) => setSection(e.target.value)}
            placeholder="Örn: Genel Bakış"
            aria-label="Widget bölümü"
            className="w-full rounded-control border border-border bg-surface px-2.5 py-1.5 text-sm outline-none focus:border-brand"
          />
        </div>
      </div>

      <Tabs
        className="mb-3"
        tabs={[
          { id: "veri", label: "Veri" },
          { id: "grafik", label: "Grafik" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "veri" && (
        <div className="space-y-4">
          <CatalogPicker title="Boyutlar" hint="neye göre kır" items={catalog.dimensions} selected={spec.dimensions} onToggle={toggleDimension} />
          <CatalogPicker title="Metrikler" hint="ne ölçülecek" items={catalog.metrics} selected={spec.metrics} onToggle={toggleMetric} />
          <div className="space-y-2 rounded-control border border-border bg-surface p-3">
            <ToggleRow
              label="Açık taahhüdü dahil et (gerçekleşen + açık taahhüt)"
              checked={spec.basis?.cost === "actual_plus_open"}
              onChange={(v) => patchBasis({ cost: v ? "actual_plus_open" : "actual" })}
            />
            <div className="flex items-center justify-between">
              <span className="text-[12.5px] text-text-secondary">Para birimi</span>
              <Segmented
                value={spec.basis?.currency ?? "try"}
                options={[
                  { id: "try", label: "₺" },
                  { id: "usd", label: "$" },
                ]}
                onChange={(v) => patchBasis({ currency: v as "try" | "usd" })}
              />
            </div>
            <ToggleRow label="Finansman maliyetini dahil et" checked={spec.basis?.financing === "incl"} onChange={(v) => patchBasis({ financing: v ? "incl" : "excl" })} />
            <ToggleRow label="KDV dahil" checked={spec.basis?.vat === "incl"} onChange={(v) => patchBasis({ vat: v ? "incl" : "excl" })} />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-text-secondary">Karşılaştırma birimi</span>
            <Segmented
              value={spec.comparison_unit ?? "pct"}
              options={[
                { id: "pct", label: "%" },
                { id: "abs", label: "#" },
              ]}
              onChange={(v) => patchSpec({ comparison_unit: v as "pct" | "abs" })}
            />
          </div>
        </div>
      )}

      {tab === "grafik" && (
        <div className="space-y-4">
          <div>
            <div className="mb-1.5 text-[11px] font-semibold text-text-secondary">Görselleştirme</div>
            <Segmented full value={spec.viz} options={VIZ_LABELS} onChange={(v) => patchSpec({ viz: v as Viz })} />
          </div>
          <div className="space-y-2 rounded-control border border-border bg-surface p-3">
            <ToggleRow label="Lejant göster" checked={spec.chart?.legend !== false} onChange={(v) => patchChart({ legend: v })} />
            <ToggleRow label="Kümülatif" checked={!!spec.chart?.cumulative} onChange={(v) => patchChart({ cumulative: v })} />
          </div>
          <div>
            <div className="mb-1.5 text-[11px] font-semibold text-text-secondary">X ekseni</div>
            <select
              value={spec.chart?.x ?? ""}
              onChange={(e) => patchChart({ x: e.target.value || null })}
              aria-label="X ekseni"
              className="w-full rounded-control border border-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-brand"
            >
              <option value="">Otomatik</option>
              {spec.dimensions.map((d) => (
                <option key={d} value={d}>
                  {dimById.get(d)?.label ?? d}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
    </Modal>
  );
}

// --------------------------------------------------------------------------- #
// Text widget modal
// --------------------------------------------------------------------------- #
function TextWidgetModal({
  widget,
  isNew,
  onApply,
  onClose,
}: {
  widget: Widget;
  isNew: boolean;
  onApply: (w: Widget) => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(widget.title);
  const [section, setSection] = useState(widget.section ?? "");
  const [content, setContent] = useState(widget.content ?? "");
  return (
    <Modal
      open
      title={isNew ? "Metin ekle" : "Metni düzenle"}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            İptal
          </Button>
          <Button onClick={() => onApply({ ...widget, type: "text", title: title.trim() || "Metin", section: section.trim() || null, content, spec: undefined, report_id: undefined })}>
            Uygula
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div>
            <div className="mb-1 text-[11px] font-semibold text-text-secondary">Başlık</div>
            <input value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Metin başlığı" className="w-full rounded-control border border-border bg-surface px-2.5 py-1.5 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <div className="mb-1 text-[11px] font-semibold text-text-secondary">Bölüm (opsiyonel)</div>
            <input value={section} onChange={(e) => setSection(e.target.value)} placeholder="Örn: Notlar" aria-label="Metin bölümü" className="w-full rounded-control border border-border bg-surface px-2.5 py-1.5 text-sm outline-none focus:border-brand" />
          </div>
        </div>
        <div>
          <div className="mb-1 text-[11px] font-semibold text-text-secondary">İçerik (markdown destekler)</div>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={8}
            aria-label="Metin içeriği"
            className="w-full rounded-control border border-border bg-surface px-2.5 py-2 text-sm outline-none focus:border-brand"
            placeholder="**Önemli not** veya açıklama yazın…"
          />
        </div>
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------------------- #
// Report picker modal — embeds {type:'report', report_id} from a viewable report.
// --------------------------------------------------------------------------- #
function ReportPickerModal({ onPick, onClose }: { onPick: (r: ReportListItem) => void; onClose: () => void }) {
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    studio
      .listReports()
      .then((data) => {
        setReports(data ?? []);
        setError(null);
      })
      .catch((e) => setError(e?.message ?? "Raporlar yüklenemedi."))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const q = search.trim().toLocaleLowerCase("tr");
  const filtered = q ? reports.filter((r) => r.title.toLocaleLowerCase("tr").includes(q)) : reports;

  return (
    <Modal open title="Rapordan widget ekle" onClose={onClose} size="lg">
      <div className="mb-3 flex h-9 items-center gap-2 rounded-control border border-border bg-surface px-3 text-sm text-text-secondary">
        <Search className="h-4 w-4 text-text-muted" />
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Rapor ara…" aria-label="Rapor ara" className="w-full bg-transparent outline-none placeholder:text-text-faint" />
      </div>
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : error ? (
        <LoadError message={`Raporlar yüklenemedi. ${error}`} onRetry={load} />
      ) : filtered.length === 0 ? (
        <EmptyState message="Görüntülenebilir rapor bulunamadı." />
      ) : (
        <div className="max-h-[50vh] overflow-y-auto rounded-control border border-border">
          {filtered.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => onPick(r)}
              className="flex w-full items-center gap-3 border-b border-border px-3 py-2.5 text-left transition-colors last:border-0 hover:bg-surface-hover"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-semibold text-text-primary">{r.title}</div>
                <div className="text-[11px] text-text-faint">{r.visibility === "company" ? "Herkes" : "Özel"}</div>
              </div>
              <Plus className="h-4 w-4 shrink-0 text-text-muted" />
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}

// --------------------------------------------------------------------------- #
// Page
// --------------------------------------------------------------------------- #
export default function StudioDashboardCanvasPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const user = useAuth((s) => s.user);
  const isDesktop = useIsDesktop();

  // --- pano meta + content ---
  const [dashboard, setDashboard] = useState<DashMeta | null>(null);
  const [title, setTitle] = useState("Adsız pano");
  const [widgets, setWidgets] = useState<Widget[]>([]);
  const [dateRange, setDateRange] = useState<DateWindow | null>(null);
  const [comparison, setComparison] = useState<{ preset?: string; from?: string; to?: string } | null>(null);
  const [filters, setFilters] = useState<StudioFilter[]>([]);
  const [visibility, setVisibility] = useState<Visibility>("private");
  const [labels, setLabels] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  // --- catalog ---
  const [catalog, setCatalog] = useState<StudioCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  // --- load (edit mode) ---
  const [loading, setLoading] = useState(!!id);
  const [loadError, setLoadError] = useState<string | null>(null);

  // --- per-widget run state ---
  const [results, setResults] = useState<Record<string, WState>>({});
  const reportInfoRef = useRef<Record<string, ReportInfo>>({});
  const [, bumpReportInfo] = useReducer((x) => x + 1, 0);

  // --- run orchestration ---
  const [ready, setReady] = useState(false);
  const firstRunRef = useRef(true);

  // --- edit modals ---
  const [configState, setConfigState] = useState<{ widget: Widget; isNew: boolean } | null>(null);
  const [textState, setTextState] = useState<{ widget: Widget; isNew: boolean } | null>(null);
  const [reportPicker, setReportPicker] = useState(false);

  const canEdit = !id || dashboard?.is_owner || user?.role === "director";

  // Catalog (cached client-side) — drives the config picker + windowing flags.
  const loadCatalog = useCallback(() => {
    setCatalogError(null);
    studio
      .catalog()
      .then(setCatalog)
      .catch((e) => setCatalogError(e?.message ?? "Katalog yüklenemedi."));
  }, []);
  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  const metricById = useMemo(() => {
    const m = new Map<string, CatalogMetric>();
    catalog?.metrics.forEach((x) => m.set(x.id, x));
    return m;
  }, [catalog]);
  const dimById = useMemo(() => {
    const m = new Map<string, { label: string }>();
    catalog?.dimensions.forEach((x) => m.set(x.id, x));
    return m;
  }, [catalog]);

  const hasDateRange = !!dateRange && !!(dateRange.preset || dateRange.from || dateRange.to);

  // --- load the pano (or init a blank one) ---
  useEffect(() => {
    firstRunRef.current = true;
    setReady(false);
    setResults({});
    reportInfoRef.current = {};
    if (!id) {
      setDashboard(null);
      setTitle("Adsız pano");
      setWidgets([]);
      setDateRange(null);
      setComparison(null);
      setFilters([]);
      setVisibility("private");
      setLabels([]);
      setDirty(false);
      setLoadError(null);
      setLoading(false);
      setReady(true);
      return;
    }
    setLoading(true);
    setLoadError(null);
    studio
      .getDashboard(id)
      .then((d) => {
        setDashboard({ id: d.id, owner_id: d.owner_id, is_owner: d.is_owner, created_at: d.created_at, updated_at: d.updated_at });
        setTitle(d.title);
        setWidgets((d.widgets ?? []).map((w) => ({ ...w, layout: w.layout ?? { x: 0, y: 0, w: 6, h: 4 } })));
        setDateRange(d.date_range ?? null);
        setComparison(d.comparison ?? null);
        setFilters(d.filters ?? []);
        setVisibility(d.visibility === "company" ? "company" : "private");
        setLabels(d.labels ?? []);
        setDirty(false);
        setReady(true);
      })
      .catch((e) => setLoadError(e?.message ?? "Pano yüklenemedi."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // --- run helpers ---
  const setWState = (wid: string, s: WState) => setResults((prev) => ({ ...prev, [wid]: s }));

  // Inject the dashboard-global date_range/comparison/filters into a widget spec
  // ONLY where the widget doesn't set them (widget wins) — mirrors backend _global_merge.
  const mergeGlobal = (spec: StudioSpec): StudioSpec => {
    const merged: StudioSpec = { ...spec };
    if (dateRange != null && merged.date_range == null) merged.date_range = dateRange;
    if (comparison != null && merged.comparison == null) merged.comparison = comparison;
    if (filters.length > 0 && merged.filters == null) merged.filters = filters;
    return merged;
  };

  const resolveReport = async (rid: string): Promise<ReportInfo> => {
    const cached = reportInfoRef.current[rid];
    if (cached) return cached;
    try {
      const rep = await studio.getReport(rid);
      const info: ReportInfo = { title: rep.title, spec: rep.spec };
      reportInfoRef.current[rid] = info;
      bumpReportInfo();
      return info;
    } catch {
      const info: ReportInfo = { unavailable: true };
      reportInfoRef.current[rid] = info;
      bumpReportInfo();
      return info;
    }
  };

  // Run one widget via POST /studio/run with the global settings merged in.
  const runOneWidget = async (w: Widget) => {
    if (w.type === "text") return;
    setWState(w.id, { loading: true });
    try {
      if (w.type === "report") {
        const info = await resolveReport(w.report_id!);
        if ("unavailable" in info) {
          setWState(w.id, { unavailable: true });
          return;
        }
        const res = await studio.run(mergeGlobal(info.spec));
        setWState(w.id, { result: res });
      } else {
        const spec = w.spec;
        if (!spec || spec.metrics.length === 0) {
          setWState(w.id, { empty: true });
          return;
        }
        const res = await studio.run(mergeGlobal(spec));
        setWState(w.id, { result: res });
      }
    } catch (e: any) {
      setWState(w.id, { error: e?.message ?? "Widget yüklenemedi" });
    }
  };

  // Initial render of a SAVED pano: ONE batch /run for the data widgets; report
  // widgets resolve per-widget (so we have their viz/title). Unsaved → per-widget.
  const runInitial = () => {
    const renderable = widgets.filter((w) => w.type !== "text");
    const dataWidgets = renderable.filter((w) => w.type !== "report");
    const reportWidgets = renderable.filter((w) => w.type === "report");
    if (dashboard?.id && dataWidgets.length > 0) {
      dataWidgets.forEach((w) => setWState(w.id, { loading: true }));
      studio
        .runDashboard(dashboard.id)
        .then((batch) => {
          setResults((prev) => {
            const next = { ...prev };
            for (const w of dataWidgets) {
              const r = batch[w.id];
              if (!r) next[w.id] = { empty: true };
              else if ("unavailable" in r) next[w.id] = { unavailable: true };
              else next[w.id] = { result: r };
            }
            return next;
          });
        })
        .catch((e) => {
          setResults((prev) => {
            const next = { ...prev };
            for (const w of dataWidgets) next[w.id] = { error: e?.message ?? "Pano yüklenemedi" };
            return next;
          });
        });
    } else {
      dataWidgets.forEach(runOneWidget);
    }
    reportWidgets.forEach(runOneWidget);
  };

  const rerunAll = () => widgets.filter((w) => w.type !== "text").forEach(runOneWidget);

  // First render uses the batch; any global change re-runs per-widget so the
  // preview reflects the UNSAVED global (the batch endpoint uses the SAVED global).
  const globalKey = JSON.stringify({ d: dateRange, c: comparison, f: filters });
  useEffect(() => {
    if (!ready) return;
    if (firstRunRef.current) {
      firstRunRef.current = false;
      runInitial();
    } else {
      rerunAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, globalKey]);

  // --- widget mutations ---
  const nextY = (section: string | null | undefined) => {
    const key = (section ?? "").trim();
    return widgets
      .filter((w) => (w.section ?? "").trim() === key)
      .reduce((m, w) => Math.max(m, (w.layout?.y ?? 0) + (w.layout?.h ?? 0)), 0);
  };

  const addWidget = (w: Widget) => {
    setWidgets((prev) => [...prev, w]);
    setDirty(true);
    runOneWidget(w);
  };
  const updateWidget = (w: Widget) => {
    setWidgets((prev) => prev.map((x) => (x.id === w.id ? w : x)));
    setDirty(true);
    runOneWidget(w);
  };
  const removeWidget = (w: Widget) => {
    if (!window.confirm("Bu widget'ı panodan kaldırmak istiyor musunuz?")) return;
    setWidgets((prev) => prev.filter((x) => x.id !== w.id));
    setResults((prev) => {
      const next = { ...prev };
      delete next[w.id];
      return next;
    });
    setDirty(true);
  };
  const renameWidget = (w: Widget) => {
    const t = window.prompt("Yeni başlık", w.title);
    if (t == null || !t.trim()) return;
    setWidgets((prev) => prev.map((x) => (x.id === w.id ? { ...x, title: t.trim() } : x)));
    setDirty(true);
  };
  const editSection = (w: Widget) => {
    const s = window.prompt("Bölüm adı (boş bırakırsanız gruplanmaz)", w.section ?? "");
    if (s == null) return;
    setWidgets((prev) => prev.map((x) => (x.id === w.id ? { ...x, section: s.trim() || null } : x)));
    setDirty(true);
  };

  // Add menu handlers
  const startAddData = (viz: Viz) => {
    const type = typeForViz(viz);
    const draft: Widget = {
      id: newId(),
      type,
      title: viz === "kpi" ? "Yeni KPI" : viz === "table" ? "Yeni tablo" : "Yeni grafik",
      layout: { x: 0, y: nextY(null), w: DEFAULT_DIMS[type].w, h: DEFAULT_DIMS[type].h },
      spec: { ...BLANK_SPEC, viz },
    };
    setConfigState({ widget: draft, isNew: true });
  };
  const startAddText = () => {
    const draft: Widget = {
      id: newId(),
      type: "text",
      title: "Metin",
      layout: { x: 0, y: nextY(null), w: DEFAULT_DIMS.text.w, h: DEFAULT_DIMS.text.h },
      content: "",
    };
    setTextState({ widget: draft, isNew: true });
  };
  const pickReport = (r: ReportListItem) => {
    setReportPicker(false);
    const w: Widget = {
      id: newId(),
      type: "report",
      title: r.title,
      layout: { x: 0, y: nextY(null), w: DEFAULT_DIMS.report.w, h: DEFAULT_DIMS.report.h },
      report_id: r.id,
    };
    addWidget(w);
  };

  // Persist a section grid's new positions back onto the widgets.
  const persistLayout = (layout: Layout[]) => {
    const byId = new Map(layout.map((l) => [l.i, l]));
    setWidgets((prev) =>
      prev.map((w) => {
        const l = byId.get(w.id);
        return l ? { ...w, layout: { x: l.x, y: l.y, w: l.w, h: l.h } } : w;
      })
    );
    setDirty(true);
  };

  // --- toolbar actions ---
  const applyGlobal = (p: { dateRange?: DateWindow | null; comparison?: { preset?: string } | null; filters?: StudioFilter[] }) => {
    if ("dateRange" in p) setDateRange(p.dateRange ?? null);
    if ("comparison" in p) setComparison(p.comparison ?? null);
    if ("filters" in p) setFilters(p.filters ?? []);
    setDirty(true);
  };

  const addFilter = (field: string) => {
    const val = window.prompt(`"${dimById.get(field)?.label ?? field}" için değer`);
    if (val == null || !val.trim()) return;
    applyGlobal({ filters: [...filters, { field, op: "=", value: val.trim() }] });
  };

  const persistBody = () => ({
    title: title.trim() || "Adsız pano",
    widgets,
    date_range: dateRange,
    comparison,
    filters: filters.length ? filters : null,
    visibility,
    labels,
  });

  const onSave = async () => {
    const bad = widgets.find((w) => (w.type === "kpi" || w.type === "chart" || w.type === "table") && (!w.spec || w.spec.metrics.length === 0));
    if (bad) {
      toast.error("Kaydetmeden önce her veri widget'ında en az bir metrik seçin.");
      return;
    }
    setSaving(true);
    try {
      if (dashboard) {
        const d = await studio.updateDashboard(dashboard.id, persistBody());
        setDashboard({ id: d.id, owner_id: d.owner_id, is_owner: d.is_owner, created_at: d.created_at, updated_at: d.updated_at });
        setWidgets((d.widgets ?? []).map((w) => ({ ...w, layout: w.layout ?? { x: 0, y: 0, w: 6, h: 4 } })));
        setDirty(false);
        toast.success("Pano kaydedildi");
      } else {
        const d = await studio.createDashboard(persistBody());
        setDirty(false);
        toast.success("Pano oluşturuldu");
        navigate(`/studio/dashboards/${d.id}`);
      }
    } catch (e: any) {
      toast.error(e?.message ?? "Pano kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const onExport = async (fmt: "pdf" | "xlsx") => {
    if (!dashboard) return;
    try {
      const blob = await studio.exportDashboardBlob(dashboard.id, fmt);
      download(blob, `${(title || "pano").replace(/[^\w.-]+/g, "-")}.${fmt}`);
    } catch (e: any) {
      toast.error(e?.message ?? "Dışa aktarılamadı");
    }
  };

  // --- per-widget rendering ---
  const renderViz = (viz: Viz, result: RunResult, spec: StudioSpec, currency: string, showWin: (m: string) => boolean): ReactNode => {
    if (viz === "kpi") {
      return (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {spec.metrics.map((mid) => {
            const m = metricById.get(mid);
            const val = result.totals.metrics[mid];
            const d = result.totals.deltas?.[mid];
            return (
              <KPICard
                key={mid}
                label={m?.label ?? mid}
                value={formatMetricValue(m?.type, val, currency)}
                delta={spec.comparison_unit === "pct" && d != null ? d * 100 : undefined}
              />
            );
          })}
        </div>
      );
    }
    if (viz === "line" || viz === "area" || viz === "bar") {
      return <StudioChart result={result} viz={viz} legend={spec.chart?.legend !== false} />;
    }
    // table
    const cols = result.columns.map((col) => {
      const isMetric = col.kind === "metric";
      const snap = isMetric && showWin(col.id);
      return {
        key: col.id,
        header: (
          <span className="inline-flex items-center gap-1">
            {col.label}
            {snap && <WindowTag />}
          </span>
        ),
        align: isMetric ? "right" : "left",
        render: (row: RunRow) =>
          isMetric ? (
            <div className="flex flex-col items-end">
              <span className="tabular">{formatMetricValue(col.type, row.metrics[col.id], currency)}</span>
              {row.deltas && row.deltas[col.id] != null && (
                <DeltaText value={row.deltas[col.id] as number} unit={spec.comparison_unit ?? "pct"} type={col.type} currency={currency} />
              )}
            </div>
          ) : (
            <span>{row.dims[col.id] ?? "—"}</span>
          ),
      };
    }) as unknown as Column<RunRow>[];
    return <DataTable columns={cols} rows={result.rows} emptyMessage="Bu seçim için veri yok." minWidth={320} />;
  };

  const widgetBody = (w: Widget): ReactNode => {
    if (w.type === "text") {
      return (
        <div className="text-[13px] leading-relaxed text-text-primary">
          {w.content?.trim() ? <MarkdownText text={w.content} /> : <span className="text-text-faint">Boş metin.</span>}
        </div>
      );
    }
    const st = results[w.id];
    if (!st || st.loading) {
      return (
        <div className="space-y-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-20 w-full" />
        </div>
      );
    }
    if (st.unavailable) {
      return <div className="flex h-full items-center justify-center p-3 text-center text-[12px] text-text-muted">Bu rapor artık kullanılamıyor.</div>;
    }
    if (st.error) {
      return <LoadError message={`Widget yüklenemedi. ${st.error}`} onRetry={() => runOneWidget(w)} />;
    }
    if (st.empty) {
      return (
        <EmptyState
          message="Bu widget için veri seçilmedi."
          actionLabel={canEdit && w.type !== "report" ? "Yapılandır" : undefined}
          onAction={canEdit && w.type !== "report" ? () => setConfigState({ widget: w, isNew: false }) : undefined}
        />
      );
    }
    if (!st.result) return null;

    let spec: StudioSpec | undefined;
    let viz: Viz | undefined;
    if (w.type === "report") {
      const info = reportInfoRef.current[w.report_id!];
      if (info && !("unavailable" in info)) {
        spec = info.spec;
        viz = info.spec.viz;
      }
    } else {
      spec = w.spec;
      viz = w.spec?.viz;
    }
    if (!spec || !viz) return null;

    const currency = st.result.meta.currency ?? spec.basis?.currency ?? "try";
    const showWin = (mid: string) => hasDateRange && metricById.get(mid)?.windowed === false;
    const snap = spec.metrics.filter(showWin);
    const windowNote =
      snap.length > 0 ? (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          {snap.map((m) => (
            <span key={m} className="inline-flex items-center gap-1 text-[11px] text-text-muted">
              {metricById.get(m)?.label ?? m}: <WindowTag />
            </span>
          ))}
        </div>
      ) : null;

    return (
      <div>
        {windowNote}
        {renderViz(viz, st.result, spec, currency, showWin)}
      </div>
    );
  };

  const renderCard = (w: Widget): ReactNode => {
    const isReport = w.type === "report";
    return (
      <div className="flex h-full flex-col overflow-hidden rounded-card border border-border bg-surface shadow-card">
        <div className="pano-drag flex items-center gap-2 border-b border-border px-3 py-2">
          {isDesktop && canEdit && <GripVertical className="h-4 w-4 shrink-0 cursor-grab text-text-faint" />}
          <span className="truncate text-[13px] font-semibold text-text-primary">{w.title}</span>
          {isReport && <Badge variant="info">Rapor</Badge>}
          <div className="flex-1" />
          <div className="pano-nodrag" onClick={(e) => e.stopPropagation()}>
            <Menu align="right" triggerLabel={`Widget işlemleri: ${w.title}`} trigger={<MoreVertical className="h-[18px] w-[18px] text-text-muted" />}>
              {(close) => (
                <>
                  {isReport && (
                    <MenuItem
                      icon={ExternalLink}
                      onClick={() => {
                        close();
                        navigate(`/studio/reports/${w.report_id}`);
                      }}
                    >
                      Rapora git
                    </MenuItem>
                  )}
                  {canEdit && (w.type === "kpi" || w.type === "chart" || w.type === "table") && (
                    <MenuItem
                      icon={Pencil}
                      onClick={() => {
                        close();
                        setConfigState({ widget: w, isNew: false });
                      }}
                    >
                      Düzenle
                    </MenuItem>
                  )}
                  {canEdit && w.type === "text" && (
                    <MenuItem
                      icon={Pencil}
                      onClick={() => {
                        close();
                        setTextState({ widget: w, isNew: false });
                      }}
                    >
                      Düzenle
                    </MenuItem>
                  )}
                  {canEdit && (
                    <MenuItem
                      icon={TypeIcon}
                      onClick={() => {
                        close();
                        renameWidget(w);
                      }}
                    >
                      Yeniden adlandır
                    </MenuItem>
                  )}
                  {canEdit && (
                    <MenuItem
                      icon={LayoutList}
                      onClick={() => {
                        close();
                        editSection(w);
                      }}
                    >
                      Bölüm…
                    </MenuItem>
                  )}
                  {canEdit && (
                    <MenuItem
                      icon={Trash2}
                      danger
                      onClick={() => {
                        close();
                        removeWidget(w);
                      }}
                    >
                      Sil
                    </MenuItem>
                  )}
                </>
              )}
            </Menu>
          </div>
        </div>
        <div className="pano-nodrag min-h-0 flex-1 overflow-auto p-3">
          {isReport && (
            <div className="mb-2">
              <button
                type="button"
                onClick={() => navigate(`/studio/reports/${w.report_id}`)}
                className="inline-flex items-center gap-1 text-[11px] text-brand hover:underline"
              >
                <ExternalLink className="h-3 w-3" /> Rapora git
              </button>
            </div>
          )}
          {widgetBody(w)}
        </div>
      </div>
    );
  };

  // --- section grouping (labelled bands; ordered by first appearance) ---
  const groups = useMemo(() => {
    const order: string[] = [];
    const map = new Map<string, Widget[]>();
    for (const w of widgets) {
      const key = (w.section ?? "").trim();
      if (!map.has(key)) {
        map.set(key, []);
        order.push(key);
      }
      map.get(key)!.push(w);
    }
    return order.map((key) => ({ key, label: key || null, items: map.get(key)! }));
  }, [widgets]);

  // --- gates ---
  if (catalogError) {
    return <LoadError message={`Katalog yüklenemedi. ${catalogError}`} onRetry={loadCatalog} />;
  }
  if (loadError) {
    return <LoadError message={`Pano yüklenemedi. ${loadError}`} onRetry={() => navigate(0)} />;
  }
  if (loading || !catalog) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const dateLabel = DATE_PRESETS.find((p) => p.id === (dateRange?.preset ?? null))?.label ?? "Özel aralık";
  const ctrl = "flex h-9 items-center gap-2 rounded-control border border-border bg-surface px-3 text-[13px] text-text-secondary transition-colors hover:bg-surface-hover";

  return (
    <div>
      {/* Top bar */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => navigate("/studio/dashboards")}
          aria-label="Geri"
          className="flex h-9 w-9 items-center justify-center rounded-control border border-border bg-surface text-text-secondary hover:bg-surface-hover"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <input
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            setDirty(true);
          }}
          readOnly={!canEdit}
          aria-label="Pano başlığı"
          className="min-w-0 flex-1 rounded-control border border-transparent bg-transparent px-2 py-1.5 text-lg font-bold text-text-primary outline-none hover:border-border focus:border-brand"
        />
        <div className="flex-1" />
        <button
          type="button"
          disabled
          title="Yapay zekâ yakında (CR-035)"
          className="flex h-9 cursor-not-allowed items-center gap-2 rounded-control border border-border bg-surface px-3 text-[13px] text-text-faint opacity-60"
        >
          <MessageSquare className="h-4 w-4" /> Bu pano hakkında sor
        </button>
        {canEdit && (
          <Segmented
            value={visibility}
            options={[
              { id: "private", label: "Özel" },
              { id: "team", label: "Takım", disabled: true, badge: "Yakında" },
              { id: "company", label: "Herkes" },
            ]}
            onChange={(v) => {
              if (v === "private" || v === "company") {
                setVisibility(v);
                setDirty(true);
              }
            }}
          />
        )}
        {dashboard ? (
          <Menu align="right" triggerClassName={ctrl} triggerLabel="Dışa aktar" trigger={<span>Dışa aktar</span>}>
            {(close) => (
              <>
                <MenuItem
                  onClick={() => {
                    close();
                    onExport("pdf");
                  }}
                >
                  PDF
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    close();
                    onExport("xlsx");
                  }}
                >
                  Excel (xlsx)
                </MenuItem>
              </>
            )}
          </Menu>
        ) : (
          <button type="button" disabled title="Önce panoyu kaydedin" className={cn(ctrl, "cursor-not-allowed opacity-60")}>
            Dışa aktar
          </button>
        )}
        {canEdit && (
          <Button onClick={onSave} loading={saving} disabled={!dirty && !!dashboard}>
            <Save className="h-4 w-4" /> Kaydet
          </Button>
        )}
      </div>

      {/* Filter / date-range / comparison + Widget ekle bar */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {filters.map((f, i) => (
          <span key={i} className="inline-flex items-center gap-1 rounded-control border border-border bg-surface px-2.5 py-1 text-xs text-text-secondary">
            <b className="font-semibold text-text-primary">{dimById.get(f.field)?.label ?? f.field}</b>
            <span className="text-text-faint">= {String(f.value)}</span>
            {canEdit && (
              <button
                type="button"
                aria-label="Filtreyi kaldır"
                onClick={() => applyGlobal({ filters: filters.filter((_, j) => j !== i) })}
                className="text-text-faint hover:text-text-primary"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </span>
        ))}
        {canEdit && (
          <Menu align="left" triggerClassName={ctrl} triggerLabel="Filtreler" trigger={<><Filter className="h-4 w-4 text-text-muted" /><span>Filtreler</span></>}>
            {(close) => (
              <div className="max-h-72 overflow-y-auto">
                {catalog.dimensions.filter((d) => d.status !== "coming_soon").map((d) => (
                  <MenuItem
                    key={d.id}
                    onClick={() => {
                      close();
                      addFilter(d.id);
                    }}
                  >
                    {d.label}
                  </MenuItem>
                ))}
              </div>
            )}
          </Menu>
        )}
        <div className="flex-1" />
        <PresetMenu
          label={dateLabel}
          icon={<CalendarRange className="h-4 w-4 text-text-muted" />}
          options={DATE_PRESETS.map((p) => ({ id: p.id ?? "__all__", label: p.label }))}
          onPick={(pid) => applyGlobal({ dateRange: pid === "__all__" ? null : { preset: pid } })}
        />
        <button
          type="button"
          onClick={() => applyGlobal({ comparison: comparison ? null : { preset: "previous_period" } })}
          className={cn(
            "flex h-9 items-center gap-2 rounded-control border px-3 text-[13px] transition-colors",
            comparison ? "border-brand bg-blue-soft text-brand" : "border-border bg-surface text-text-secondary hover:bg-surface-hover"
          )}
        >
          vs Önceki dönem
        </button>
        {canEdit && (
          <Menu align="right" triggerClassName="inline-flex h-9 items-center gap-2 rounded-control bg-primary px-3 text-[13px] font-medium text-white hover:bg-primary-light" triggerLabel="Widget ekle" trigger={<><Plus className="h-4 w-4" /><span>Widget ekle</span></>}>
            {(close) => (
              <>
                <MenuItem onClick={() => { close(); startAddData("kpi"); }}>KPI</MenuItem>
                <MenuItem onClick={() => { close(); startAddData("line"); }}>Grafik</MenuItem>
                <MenuItem onClick={() => { close(); startAddData("table"); }}>Tablo</MenuItem>
                <MenuItem onClick={() => { close(); startAddText(); }}>Metin</MenuItem>
                <MenuItem onClick={() => { close(); setReportPicker(true); }}>Rapordan widget</MenuItem>
              </>
            )}
          </Menu>
        )}
      </div>

      {/* Canvas */}
      {widgets.length === 0 ? (
        <div className="rounded-card border border-border bg-surface shadow-card">
          <EmptyState
            message="Bu pano boş. Başlamak için bir widget ekleyin."
            actionLabel={canEdit ? "KPI ekle" : undefined}
            onAction={canEdit ? () => startAddData("kpi") : undefined}
          />
        </div>
      ) : (
        groups.map((g) => (
          <div key={g.key || "__default__"} className="mb-2">
            {g.label && (
              <div className="mt-4 mb-2 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wide text-text-muted">
                <GripVertical className="h-3.5 w-3.5 text-text-faint" />
                {g.label.toLocaleUpperCase("tr")}
              </div>
            )}
            <SectionGrid items={g.items} isDesktop={isDesktop} editable={!!canEdit} onPersist={persistLayout} renderItem={renderCard} />
          </div>
        ))
      )}

      {/* Modals */}
      {configState && catalog && (
        <WidgetConfigModal
          catalog={catalog}
          widget={configState.widget}
          isNew={configState.isNew}
          onClose={() => setConfigState(null)}
          onApply={(w) => {
            if (configState.isNew) addWidget(w);
            else updateWidget(w);
            setConfigState(null);
          }}
        />
      )}
      {textState && (
        <TextWidgetModal
          widget={textState.widget}
          isNew={textState.isNew}
          onClose={() => setTextState(null)}
          onApply={(w) => {
            if (textState.isNew) addWidget(w);
            else updateWidget(w);
            setTextState(null);
          }}
        />
      )}
      {reportPicker && <ReportPickerModal onPick={pickReport} onClose={() => setReportPicker(false)} />}
    </div>
  );
}
