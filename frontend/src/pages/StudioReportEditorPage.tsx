import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, LoadError } from "@/components/EmptyState";
import { ExportMenu, type ExportColumn } from "@/components/ExportMenu";
import { KPICard } from "@/components/KPICard";
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
import { Badge, Button, Skeleton, Tabs } from "@/components/ui";
import { cn } from "@/lib/cn";
import { studio } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type {
  CatalogDimension,
  CatalogMetric,
  RunResult,
  RunRow,
  StudioCatalog,
  StudioSpec,
  Viz,
  Visibility,
} from "@/types/studio";
import { formatDateTime } from "@/utils/format";
import {
  ArrowLeft,
  BarChart3,
  CalendarRange,
  Hash,
  LineChart as LineIcon,
  MessageSquare,
  Save,
  Star,
  Table as TableIcon,
  Tag,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";

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

const VIZ_OPTIONS: { id: Viz; label: string; icon: any }[] = [
  { id: "line", label: "Çizgi", icon: LineIcon },
  { id: "area", label: "Alan", icon: LineIcon },
  { id: "bar", label: "Çubuk", icon: BarChart3 },
  { id: "kpi", label: "KPI", icon: Hash },
  { id: "table", label: "Tablo", icon: TableIcon },
];

const BLANK_SPEC: StudioSpec = {
  metrics: [],
  dimensions: [],
  viz: "table",
  basis: { cost: "actual", currency: "try", financing: "excl", vat: "excl" },
  comparison_unit: "pct",
};

// --------------------------------------------------------------------------- #
// Page
// --------------------------------------------------------------------------- #
export default function StudioReportEditorPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const user = useAuth((s) => s.user);
  const isNew = !id;

  // --- report meta + spec ---
  const [spec, setSpec] = useState<StudioSpec>(BLANK_SPEC);
  const [title, setTitle] = useState("Adsız rapor");
  const [visibility, setVisibility] = useState<Visibility>("private");
  const [labels, setLabels] = useState<string[]>([]);
  const [starred, setStarred] = useState(false);
  const [report, setReport] = useState<{
    id: string;
    owner_id: string;
    is_owner: boolean;
    created_at: string;
    updated_at: string;
  } | null>(null);

  // --- catalog ---
  const [catalog, setCatalog] = useState<StudioCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  // --- report load (edit mode) ---
  const [loadingReport, setLoadingReport] = useState(!isNew);
  const [reportError, setReportError] = useState<string | null>(null);

  // --- run / preview ---
  const [result, setResult] = useState<RunResult | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runNonce, setRunNonce] = useState(0);

  const [panel, setPanel] = useState("veri");
  const [labelDraft, setLabelDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [pdfExporting, setPdfExporting] = useState(false);

  // Catalog (cached client-side) — drives the pickers + windowing flags.
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

  // Load the saved report when editing.
  const loadReport = useCallback(() => {
    if (isNew) return;
    setLoadingReport(true);
    setReportError(null);
    studio
      .getReport(id!)
      .then((r) => {
        setSpec({ ...BLANK_SPEC, ...r.spec });
        setTitle(r.title);
        setVisibility((r.visibility === "company" ? "company" : "private") as Visibility);
        setLabels(r.labels ?? []);
        setReport({ id: r.id, owner_id: r.owner_id, is_owner: r.is_owner, created_at: r.created_at, updated_at: r.updated_at });
      })
      .catch((e) => setReportError(e?.message ?? "Rapor yüklenemedi."))
      .finally(() => setLoadingReport(false));
  }, [id, isNew]);
  useEffect(() => {
    loadReport();
  }, [loadReport]);

  // Debounced live preview — POST /studio/run on any spec change (≥1 metric).
  const specKey = JSON.stringify(spec);
  useEffect(() => {
    if (spec.metrics.length === 0) {
      setResult(null);
      setRunError(null);
      setRunLoading(false);
      return;
    }
    setRunLoading(true);
    const t = setTimeout(() => {
      studio
        .run(spec)
        .then((r) => {
          setResult(r);
          setRunError(null);
        })
        .catch((e) => setRunError(e?.message ?? "Önizleme yüklenemedi."))
        .finally(() => setRunLoading(false));
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [specKey, runNonce]);

  // --- catalog lookups ---
  const metricById = useMemo(() => {
    const m = new Map<string, CatalogMetric>();
    catalog?.metrics.forEach((x) => m.set(x.id, x));
    return m;
  }, [catalog]);
  const dimById = useMemo(() => {
    const m = new Map<string, CatalogDimension>();
    catalog?.dimensions.forEach((x) => m.set(x.id, x));
    return m;
  }, [catalog]);

  const hasDateRange = !!spec.date_range && !!(spec.date_range.preset || spec.date_range.from || spec.date_range.to);
  const showWindowTag = useCallback(
    (mid: string) => hasDateRange && metricById.get(mid)?.windowed === false,
    [hasDateRange, metricById]
  );
  const currency = result?.meta.currency ?? spec.basis?.currency ?? "try";

  // --- spec mutators ---
  const patchSpec = (partial: Partial<StudioSpec>) => setSpec((s) => ({ ...s, ...partial }));
  const patchBasis = (partial: Partial<NonNullable<StudioSpec["basis"]>>) =>
    setSpec((s) => ({ ...s, basis: { ...s.basis, ...partial } }));
  const patchChart = (partial: Partial<NonNullable<StudioSpec["chart"]>>) =>
    setSpec((s) => ({ ...s, chart: { ...s.chart, ...partial } }));
  const toggleMetric = (mid: string) =>
    setSpec((s) => ({ ...s, metrics: s.metrics.includes(mid) ? s.metrics.filter((x) => x !== mid) : [...s.metrics, mid] }));
  const toggleDimension = (did: string) =>
    setSpec((s) => ({ ...s, dimensions: s.dimensions.includes(did) ? s.dimensions.filter((x) => x !== did) : [...s.dimensions, did] }));
  // KPI shows a single total — switching to it clears (and hides) Boyutlar so the
  // spec doesn't carry silently-ignored dimensions (CR-034.1 Fix 1).
  const setViz = (viz: Viz) => setSpec((s) => ({ ...s, viz, ...(viz === "kpi" ? { dimensions: [] } : null) }));
  const isKpi = spec.viz === "kpi";

  const dateLabel = DATE_PRESETS.find((p) => p.id === (spec.date_range?.preset ?? null))?.label ?? "Özel aralık";

  // --- save / export ---
  const persistBody = () => ({ title: title.trim() || "Adsız rapor", spec, visibility, labels });

  const onSave = async () => {
    if (spec.metrics.length === 0) {
      toast.error("Kaydetmeden önce en az bir metrik seçin.");
      return;
    }
    setSaving(true);
    try {
      if (report) {
        const r = await studio.updateReport(report.id, persistBody());
        setReport({ id: r.id, owner_id: r.owner_id, is_owner: r.is_owner, created_at: r.created_at, updated_at: r.updated_at });
        toast.success("Rapor kaydedildi");
      } else {
        const r = await studio.createReport(persistBody());
        toast.success("Rapor oluşturuldu");
        navigate(`/studio/reports/${r.id}`);
      }
    } catch (e: any) {
      toast.error(e?.message ?? "Rapor kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const onSaveAs = async () => {
    if (spec.metrics.length === 0) {
      toast.error("Kaydetmeden önce en az bir metrik seçin.");
      return;
    }
    setSaving(true);
    try {
      const r = await studio.createReport({ ...persistBody(), title: `${title.trim() || "Adsız rapor"} (kopya)` });
      toast.success("Yeni rapor oluşturuldu");
      navigate(`/studio/reports/${r.id}`);
    } catch (e: any) {
      toast.error(e?.message ?? "Rapor kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const onDownloadPdf = async () => {
    if (!report) return;
    setPdfExporting(true);
    try {
      const blob = await studio.exportReportBlob(report.id, "pdf");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(title || "rapor").replace(/[^\w.-]+/g, "-")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      toast.error(e?.message ?? "PDF indirilemedi");
    } finally {
      setPdfExporting(false);
    }
  };

  // Client-side export columns/rows for the current preview (CSV/xlsx via ExportMenu).
  const exportColumns: ExportColumn<RunRow>[] = (result?.columns ?? []).map((col) => ({
    header: col.label,
    value: (row) => (col.kind === "dimension" ? row.dims[col.id] ?? "" : row.metrics[col.id] ?? null),
  }));

  // --- catalog gate ---
  if (catalogError) {
    return <LoadError message={`Katalog yüklenemedi. ${catalogError}`} onRetry={loadCatalog} />;
  }
  if (reportError) {
    return <LoadError message={`Rapor yüklenemedi. ${reportError}`} onRetry={loadReport} />;
  }
  if (loadingReport || !catalog) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const canEdit = isNew || report?.is_owner || user?.role === "director";

  return (
    <div>
      {/* Top bar */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => navigate("/studio/reports")}
          aria-label="Geri"
          className="flex h-9 w-9 items-center justify-center rounded-control border border-border bg-surface text-text-secondary hover:bg-surface-hover"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="Rapor başlığı"
          className="min-w-0 flex-1 rounded-control border border-transparent bg-transparent px-2 py-1.5 text-lg font-bold text-text-primary outline-none hover:border-border focus:border-brand"
        />
        <button
          type="button"
          onClick={() => setStarred((v) => !v)}
          aria-label="Yıldızla"
          aria-pressed={starred}
          className="flex h-9 w-9 items-center justify-center rounded-control border border-border bg-surface hover:bg-surface-hover"
        >
          <Star className={cn("h-4 w-4", starred ? "fill-amber text-amber" : "text-text-muted")} />
        </button>
        <div className="flex-1" />
        <button
          type="button"
          disabled
          title="Yapay zekâ yakında (CR-035)"
          className="flex h-9 cursor-not-allowed items-center gap-2 rounded-control border border-border bg-surface px-3 text-[13px] text-text-faint opacity-60"
        >
          <MessageSquare className="h-4 w-4" /> Bu rapor hakkında sor
        </button>
        <ExportMenu rows={result?.rows ?? []} columns={exportColumns} filename={(title || "rapor").replace(/[^\w.-]+/g, "-")} disabled={!result} />
        <Button
          variant="outline"
          onClick={onDownloadPdf}
          loading={pdfExporting}
          disabled={!report || pdfExporting}
          title={report ? "PDF indir" : "Önce raporu kaydedin"}
        >
          {pdfExporting ? "Dışa aktarılıyor…" : "PDF indir"}
        </Button>
        {!isNew && (
          <Button variant="outline" onClick={onSaveAs} disabled={saving}>
            Farklı kaydet
          </Button>
        )}
        {canEdit && (
          <Button onClick={onSave} loading={saving}>
            <Save className="h-4 w-4" /> Kaydet
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_340px]">
        {/* ===== Canvas ===== */}
        <div className="min-w-0">
          {/* Filter / date-range / comparison bar */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {(spec.filters ?? []).map((f, i) => (
              <span key={i} className="inline-flex items-center gap-1 rounded-control border border-border bg-surface px-2.5 py-1 text-xs text-text-secondary">
                <b className="font-semibold text-text-primary">{dimById.get(f.field)?.label ?? f.field}</b>
                <button
                  type="button"
                  aria-label="Filtreyi kaldır"
                  onClick={() => patchSpec({ filters: (spec.filters ?? []).filter((_, j) => j !== i) })}
                  className="text-text-faint hover:text-text-primary"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            <div className="flex-1" />
            <PresetMenu
              label={dateLabel}
              icon={<CalendarRange className="h-4 w-4 text-text-muted" />}
              options={DATE_PRESETS.map((p) => ({ id: p.id ?? "__all__", label: p.label }))}
              onPick={(pid) => patchSpec({ date_range: pid === "__all__" ? null : { preset: pid } })}
            />
            <button
              type="button"
              onClick={() =>
                patchSpec({ comparison: spec.comparison ? null : { preset: "previous_period" } })
              }
              className={cn(
                "flex h-9 items-center gap-2 rounded-control border px-3 text-[13px] transition-colors",
                spec.comparison ? "border-brand bg-blue-soft text-brand" : "border-border bg-surface text-text-secondary hover:bg-surface-hover"
              )}
            >
              vs Önceki dönem
            </button>
          </div>

          {/* Preview */}
          <CanvasPreview
            spec={spec}
            result={result}
            runLoading={runLoading}
            runError={runError}
            currency={currency}
            metricById={metricById}
            showWindowTag={showWindowTag}
            onRetry={() => setRunNonce((n) => n + 1)}
          />
        </div>

        {/* ===== Config panel ===== */}
        <div className="min-w-0 rounded-card border border-border bg-surface-soft p-3">
          <Tabs
            className="mb-3"
            tabs={[
              { id: "veri", label: "Veri" },
              { id: "grafik", label: "Grafik" },
              { id: "genel", label: "Genel" },
            ]}
            value={panel}
            onChange={setPanel}
          />

          {panel === "veri" && (
            <div className="space-y-4">
              {isKpi ? (
                <div>
                  <div className="mb-1.5 text-[11px] font-semibold text-text-secondary">
                    Boyutlar <span className="font-normal text-text-faint">(neye göre kır)</span>
                  </div>
                  <div className="rounded-control border border-border bg-surface px-3 py-2.5 text-[11.5px] leading-snug text-text-muted">
                    KPI tek bir değer gösterir — kırılım için Tablo veya Grafik kullanın.
                  </div>
                </div>
              ) : (
                <CatalogPicker
                  title="Boyutlar"
                  hint="neye göre kır"
                  items={catalog.dimensions}
                  selected={spec.dimensions}
                  onToggle={toggleDimension}
                />
              )}
              <CatalogPicker
                title="Metrikler"
                hint="ne ölçülecek"
                items={catalog.metrics}
                selected={spec.metrics}
                onToggle={toggleMetric}
              />

              <div>
                <div className="mb-1.5 text-[11px] font-semibold text-text-secondary">Hesap bazı</div>
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
                  <ToggleRow
                    label="Finansman maliyetini dahil et"
                    checked={spec.basis?.financing === "incl"}
                    onChange={(v) => patchBasis({ financing: v ? "incl" : "excl" })}
                  />
                  <ToggleRow
                    label="KDV dahil"
                    checked={spec.basis?.vat === "incl"}
                    onChange={(v) => patchBasis({ vat: v ? "incl" : "excl" })}
                  />
                </div>
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

          {panel === "grafik" && (
            <div className="space-y-4">
              <div>
                <div className="mb-1.5 text-[11px] font-semibold text-text-secondary">Grafik tipi</div>
                <div className="flex flex-wrap gap-1.5">
                  {VIZ_OPTIONS.map((o) => (
                    <button
                      key={o.id}
                      type="button"
                      onClick={() => setViz(o.id)}
                      className={cn(
                        "flex items-center gap-1.5 rounded-control border px-2.5 py-1.5 text-xs transition-colors",
                        spec.viz === o.id ? "border-brand bg-blue-soft text-brand" : "border-border bg-surface text-text-secondary hover:bg-surface-hover"
                      )}
                    >
                      <o.icon className="h-3.5 w-3.5" /> {o.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2 rounded-control border border-border bg-surface p-3">
                <ToggleRow label="Lejant göster" checked={spec.chart?.legend !== false} onChange={(v) => patchChart({ legend: v })} />
                <ToggleRow label="Kümülatif" checked={!!spec.chart?.cumulative} onChange={(v) => patchChart({ cumulative: v })} />
                <ToggleRow
                  label="Karşılaştırmayı göster"
                  checked={!!spec.comparison}
                  onChange={(v) => patchSpec({ comparison: v ? { preset: "previous_period" } : null })}
                />
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

              <div>
                <div className="mb-1.5 text-[11px] font-semibold text-text-secondary">Y ekseni (sol)</div>
                {spec.metrics.length === 0 && <div className="text-[11px] text-text-faint">Önce metrik seçin.</div>}
                <div className="space-y-1">
                  {spec.metrics.map((mid) => {
                    const on = (spec.chart?.y_left ?? spec.metrics).includes(mid);
                    return (
                      <label key={mid} className="flex cursor-pointer items-center gap-2 text-[12.5px] text-text-secondary">
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={(e) => {
                            const base = spec.chart?.y_left ?? spec.metrics;
                            const next = e.target.checked ? [...new Set([...base, mid])] : base.filter((x) => x !== mid);
                            patchChart({ y_left: next });
                          }}
                          className="h-3.5 w-3.5 accent-[var(--color-brand)]"
                        />
                        {metricById.get(mid)?.label ?? mid}
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {panel === "genel" && (
            <div className="space-y-4">
              <div>
                <div className="mb-1.5 text-[11px] font-semibold text-text-secondary">Görünürlük</div>
                <Segmented
                  full
                  value={visibility}
                  options={[
                    { id: "private", label: "Özel" },
                    { id: "team", label: "Takım", disabled: true, badge: "Yakında" },
                    { id: "company", label: "Herkes" },
                  ]}
                  onChange={(v) => {
                    if (v === "private" || v === "company") setVisibility(v);
                  }}
                />
                <p className="mt-1.5 text-[11px] text-text-muted">
                  {visibility === "company" ? "Şirketinizdeki herkes görüntüleyebilir." : "Yalnızca siz görürsünüz."}
                </p>
              </div>

              <div>
                <div className="mb-1.5 text-[11px] font-semibold text-text-secondary">Etiketler</div>
                <div className="mb-1.5 flex flex-wrap gap-1.5">
                  {labels.map((l) => (
                    <span key={l} className="inline-flex items-center gap-1 rounded-control bg-surface-hover px-2 py-0.5 text-[11px] text-text-secondary">
                      <Tag className="h-3 w-3" /> {l}
                      <button type="button" aria-label={`${l} etiketini kaldır`} onClick={() => setLabels((ls) => ls.filter((x) => x !== l))}>
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
                <input
                  value={labelDraft}
                  onChange={(e) => setLabelDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      const v = labelDraft.trim();
                      if (v && !labels.includes(v)) setLabels((ls) => [...ls, v]);
                      setLabelDraft("");
                    }
                  }}
                  placeholder="Etiket ekle (Enter)"
                  aria-label="Etiket ekle"
                  className="w-full rounded-control border border-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:border-brand"
                />
              </div>

              <div className="space-y-1 border-t border-border pt-2 text-[11.5px]">
                <MetaLine label="Sahip">{report ? (report.is_owner ? "Siz" : "Başka kullanıcı") : user?.full_name ?? "Siz"}</MetaLine>
                <MetaLine label="Oluşturulma">{report ? formatDateTime(report.created_at) : "Kaydedilmedi"}</MetaLine>
                <MetaLine label="Son güncelleme">{report ? formatDateTime(report.updated_at) : "—"}</MetaLine>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- #
// Canvas preview — loading / error / empty / viz switch
// --------------------------------------------------------------------------- #
function CanvasPreview({
  spec,
  result,
  runLoading,
  runError,
  currency,
  metricById,
  showWindowTag,
  onRetry,
}: {
  spec: StudioSpec;
  result: RunResult | null;
  runLoading: boolean;
  runError: string | null;
  currency: string;
  metricById: Map<string, CatalogMetric>;
  showWindowTag: (mid: string) => boolean | undefined;
  onRetry: () => void;
}) {
  if (runError) {
    return (
      <div className="rounded-card border border-border bg-surface shadow-card">
        <LoadError message={`Önizleme yüklenemedi. ${runError}`} onRetry={onRetry} />
      </div>
    );
  }
  if (spec.metrics.length === 0) {
    return (
      <div className="rounded-card border border-border bg-surface shadow-card">
        <EmptyState message="Başlamak için sağ panelden en az bir metrik seçin." />
      </div>
    );
  }
  if (runLoading && !result) {
    return (
      <div className="space-y-2 rounded-card border border-border bg-surface p-4 shadow-card">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (!result) return null;

  // Windowing note shared by chart + kpi (table puts it on the column header).
  const snapshotMetrics = spec.metrics.filter((m) => showWindowTag(m));
  const windowNote =
    snapshotMetrics.length > 0 ? (
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        {snapshotMetrics.map((m) => (
          <span key={m} className="inline-flex items-center gap-1 text-[11px] text-text-muted">
            {metricById.get(m)?.label ?? m}: <WindowTag />
          </span>
        ))}
      </div>
    ) : null;

  if (spec.viz === "kpi") {
    return (
      <div>
        {windowNote}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
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
      </div>
    );
  }

  if (spec.viz === "line" || spec.viz === "area" || spec.viz === "bar") {
    return (
      <div>
        {windowNote}
        <StudioChart result={result} viz={spec.viz} legend={spec.chart?.legend !== false} />
      </div>
    );
  }

  // table
  const metricCols = result.columns.filter((c) => c.kind === "metric");
  const tableColumns = result.columns.map((col) => {
    const isMetric = col.kind === "metric";
    const snap = isMetric && showWindowTag(col.id);
    return {
      key: col.id,
      // DataTable renders `header` as a child node; we pass a label + windowing
      // badge (typed string upstream, so cast the built columns once below).
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

  return (
    <div>
      <DataTable columns={tableColumns} rows={result.rows} emptyMessage="Bu seçim için veri yok." minWidth={480} />
      {metricCols.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-card border border-border bg-surface-soft px-4 py-3">
          <Badge variant="neutral">Toplam</Badge>
          {metricCols.map((col) => (
            <div key={col.id} className="min-w-0">
              <div className="overline">{col.label}</div>
              <div className="tabular text-sm font-semibold text-text-primary">
                {formatMetricValue(col.type, result.totals.metrics[col.id], currency)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- #
// Small shared controls
// --------------------------------------------------------------------------- #
function MetaLine({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-border py-1 last:border-0">
      <span className="text-text-muted">{label}</span>
      <span className="font-medium text-text-secondary">{children}</span>
    </div>
  );
}
