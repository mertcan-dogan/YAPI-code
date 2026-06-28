import { DataTable, type Column } from "@/components/DataTable";
import { KPICard } from "@/components/KPICard";
import { StudioChart, formatMetricValue } from "@/components/StudioChart";
import { apiPut, studio } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { ProposedAction } from "@/types/agent";
import type { CatalogDimension, CatalogMetric, RunResult, RunRow, StudioSpec } from "@/types/studio";
import { Check, Pencil, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

// CR-011-D §4.1 — proposed-action confirm UI. When the agent proposes a write it
// appears as a clearly-labeled "Yapı AI şunu öneriyor: …" card with Onayla /
// Reddet that route through the EXISTING /approvals flow — never an instant
// write. Only a director can decide (matching the approvals endpoints); other
// users see a link to the Onaylar page. Confirmation toast on approve.
//
// CR-035 — the two Rapor Stüdyosu authoring kinds (agent_create_report /
// agent_create_dashboard) get a richer body: a spec summary + a LIVE PREVIEW
// (via POST /studio/run, rendered with the SAME StudioChart / KPICard / DataTable
// kit the editor uses) and a "Düzenle" action that opens the editor on an UNSAVED
// draft. Onayla creates the artefact via approval, then navigates to it.
type Decision = "pending" | "approved" | "rejected";

const VIZ_LABELS: Record<string, string> = {
  line: "Çizgi",
  area: "Alan",
  bar: "Çubuk",
  kpi: "KPI",
  table: "Tablo",
};

const DATE_LABELS: Record<string, string> = {
  this_month: "Bu ay",
  last_month: "Geçen ay",
  last_3_months: "Son 3 ay",
  last_6_months: "Son 6 ay",
  last_12_months: "Son 12 ay",
  ytd: "Bu yıl",
  last_year: "Geçen yıl",
};

function dateRangeLabel(dr: any): string | null {
  if (!dr) return null;
  if (dr.preset) return DATE_LABELS[dr.preset] ?? dr.preset;
  if (dr.from || dr.to) return "Özel aralık";
  return null;
}

// A compact summary chip.
function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-control border border-border bg-surface px-2 py-0.5 text-[11px] text-text-secondary">
      <b className="font-semibold text-text-primary">{label}:</b>
      <span className="truncate">{value}</span>
    </span>
  );
}

export function ProposedActionCard({ action }: { action: ProposedAction }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isDirector = user?.role === "director";
  const [state, setState] = useState<Decision>("pending");
  const [busy, setBusy] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [reason, setReason] = useState("");

  const isReport = action.kind === "agent_create_report";
  const isDashboard = action.kind === "agent_create_dashboard";
  const isStudio = isReport || isDashboard;

  // Catalog (cached) — used ONLY for the studio kinds to label dimension/metric
  // ids. Falls back to raw ids if it can't load (ids are acceptable per CR-035).
  const [metricById, setMetricById] = useState<Map<string, CatalogMetric>>(new Map());
  const [dimById, setDimById] = useState<Map<string, CatalogDimension>>(new Map());
  useEffect(() => {
    if (!isStudio) return;
    let alive = true;
    studio
      .catalog()
      .then((cat) => {
        if (!alive) return;
        setMetricById(new Map(cat.metrics.map((m) => [m.id, m])));
        setDimById(new Map(cat.dimensions.map((d) => [d.id, d])));
      })
      .catch(() => {
        /* keep raw ids */
      });
    return () => {
      alive = false;
    };
  }, [isStudio]);

  const labelOf = (id: string) => metricById.get(id)?.label ?? dimById.get(id)?.label ?? id;

  // The spec we live-preview: the report's own spec, or a dashboard's first data widget.
  const previewSpec: StudioSpec | null = useMemo(() => {
    if (isReport) return (action.spec as StudioSpec) ?? null;
    if (isDashboard) {
      const specs = (action.widgets ?? [])
        .map((w: any) => w?.spec as StudioSpec | undefined)
        .filter((s): s is StudioSpec => !!s && Array.isArray(s.metrics) && s.metrics.length > 0);
      return specs[0] ?? null;
    }
    return null;
  }, [isReport, isDashboard, action.spec, action.widgets]);

  const approve = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await apiPut<{ id?: string; created?: { table?: string; id?: string } } | undefined>(
        `/approvals/request/${action.request_id}/approve`,
        {}
      );
      setState("approved");
      const created = res?.created;
      if (isStudio && created?.id) {
        const isDash = created.table === "dashboards";
        toast.success(isDash ? "Pano oluşturuldu." : "Rapor oluşturuldu.");
        navigate(isDash ? `/studio/dashboards/${created.id}` : `/studio/reports/${created.id}`);
      } else {
        toast.success("Öneri onaylandı ve uygulandı.");
      }
    } catch (e: any) {
      toast.error(e?.message ?? "Onaylanamadı");
    } finally {
      setBusy(false);
    }
  };

  // Düzenle — open the editor on the PROPOSED spec, UNSAVED. Nothing is created.
  const edit = () => {
    if (isReport) {
      navigate("/studio/reports/new", { state: { draftSpec: action.spec, draftTitle: action.title } });
    } else if (isDashboard) {
      navigate("/studio/dashboards/new", {
        state: { draftWidgets: action.widgets, draftTitle: action.title, draftDateRange: action.date_range },
      });
    }
  };

  const reject = async () => {
    const r = reason.trim();
    if (!r) {
      toast.error("Red nedeni zorunludur");
      return;
    }
    setBusy(true);
    try {
      await apiPut(`/approvals/request/${action.request_id}/reject`, { reason: r });
      setState("rejected");
      setShowReject(false);
      toast.success("Öneri reddedildi.");
    } catch (e: any) {
      toast.error(e?.message ?? "Reddedilemedi");
    } finally {
      setBusy(false);
    }
  };

  // --- spec summary (studio kinds only) ---
  const reportSummary = () => {
    const spec = (action.spec as StudioSpec) ?? null;
    if (!spec) return null;
    const dims = spec.dimensions ?? [];
    const metrics = spec.metrics ?? [];
    const dr = dateRangeLabel(spec.date_range);
    return (
      <div className="mt-2 flex flex-wrap gap-1.5">
        {dims.length > 0 && <Chip label="Boyutlar" value={dims.map(labelOf).join(", ")} />}
        {metrics.length > 0 && <Chip label="Metrikler" value={metrics.map(labelOf).join(", ")} />}
        {spec.viz && <Chip label="Görsel" value={VIZ_LABELS[spec.viz] ?? spec.viz} />}
        {dr && <Chip label="Tarih" value={dr} />}
      </div>
    );
  };

  const dashboardSummary = () => {
    const widgets = action.widgets ?? [];
    const dataWidgets = widgets.filter(
      (w: any) => w?.spec && Array.isArray(w.spec.metrics) && w.spec.metrics.length > 0
    );
    const dr = dateRangeLabel(action.date_range);
    return (
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Chip label="Widget" value={`${widgets.length} adet`} />
        {dr && <Chip label="Tarih" value={dr} />}
        {dataWidgets.map((w: any, i: number) => (
          <Chip
            key={w.id ?? i}
            label={w.title || "Widget"}
            value={(w.spec.metrics as string[]).map(labelOf).join(", ")}
          />
        ))}
      </div>
    );
  };

  return (
    <div className="mt-3 rounded-control border border-brand/40 bg-navy-50/60 p-3">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand-2 text-white">
          <Sparkles className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-primary">
            Yapı AI şunu öneriyor
            <span className="ml-1 font-normal text-text-secondary">· {action.kind_label}</span>
          </p>
          <p className="mt-0.5 break-words text-[13px] text-text-primary">{action.description}</p>

          {/* CR-035 — spec summary + live preview for the two authoring kinds. */}
          {isStudio && (
            <>
              {action.title && <p className="mt-1 text-[13px] font-semibold text-text-primary">{action.title}</p>}
              {isReport ? reportSummary() : dashboardSummary()}
              {previewSpec ? (
                <div className="mt-2">
                  {isDashboard && (
                    <p className="mb-1 text-[11px] text-text-faint">İlk widget önizlemesi</p>
                  )}
                  <StudioRunPreview spec={previewSpec} metricById={metricById} />
                </div>
              ) : (
                <p className="mt-2 text-[11px] text-text-faint">Önizlenecek veri yok.</p>
              )}
            </>
          )}

          {state === "approved" ? (
            <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-success">
              <Check className="h-3.5 w-3.5" />{" "}
              {isStudio ? (isDashboard ? "Pano oluşturuldu." : "Rapor oluşturuldu.") : "Onaylandı ve uygulandı."}
            </p>
          ) : state === "rejected" ? (
            <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-danger">
              <X className="h-3.5 w-3.5" /> Reddedildi.
            </p>
          ) : isDirector ? (
            <>
              {!showReject ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    onClick={approve}
                    disabled={busy}
                    className="focus-ring rounded-control bg-brand px-3 py-1 text-xs font-medium text-white transition hover:bg-brand/90 disabled:opacity-50"
                  >
                    Onayla
                  </button>
                  {isStudio && (
                    <button
                      onClick={edit}
                      disabled={busy}
                      className="focus-ring inline-flex items-center gap-1 rounded-control border border-border px-3 py-1 text-xs font-medium text-text-primary transition hover:border-brand hover:text-brand disabled:opacity-50"
                    >
                      <Pencil className="h-3.5 w-3.5" /> Düzenle
                    </button>
                  )}
                  <button
                    onClick={() => setShowReject(true)}
                    disabled={busy}
                    className="focus-ring rounded-control border border-border px-3 py-1 text-xs font-medium text-text-primary transition hover:border-danger hover:text-danger disabled:opacity-50"
                  >
                    Reddet
                  </button>
                  <span className="self-center text-[11px] text-text-faint">
                    Onaylamadan hiçbir değişiklik yapılmaz.
                  </span>
                </div>
              ) : (
                <div className="mt-2 flex flex-col gap-1.5">
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Red nedeni"
                    rows={2}
                    className="w-full rounded-md border border-border bg-surface px-2 py-1 text-xs outline-none focus:border-brand"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={reject}
                      disabled={busy || !reason.trim()}
                      className="focus-ring rounded-control bg-danger px-3 py-1 text-xs font-medium text-white transition hover:bg-danger/90 disabled:opacity-50"
                    >
                      Reddet
                    </button>
                    <button
                      onClick={() => setShowReject(false)}
                      disabled={busy}
                      className="focus-ring rounded-control border border-border px-3 py-1 text-xs font-medium text-text-primary"
                    >
                      Vazgeç
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="mt-2 text-[11px] text-text-secondary">
              Bu öneri bir yöneticinin onayını bekliyor —{" "}
              <Link to="/approvals" className="font-medium text-brand hover:underline">
                Onaylar sayfası
              </Link>
              .
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- #
// Live preview — runs the proposed spec via POST /studio/run and renders it with
// the EXISTING studio kit (same dispatch as the editor's CanvasPreview). Self
// contained loading / error states; a failed run never blocks the rest of the card.
// --------------------------------------------------------------------------- #
function StudioRunPreview({ spec, metricById }: { spec: StudioSpec; metricById: Map<string, CatalogMetric> }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const specKey = JSON.stringify(spec);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setResult(null);
    studio
      .run(spec)
      .then((r) => {
        if (!alive) return;
        setResult(r);
        setLoading(false);
      })
      .catch((e) => {
        if (!alive) return;
        setError(e?.message ?? "Önizleme yüklenemedi.");
        setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [specKey]);

  if (loading) {
    return (
      <div className="rounded-control border border-border bg-surface px-3 py-4 text-center text-[11px] text-text-muted">
        Önizleme hazırlanıyor…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-control border border-border bg-surface px-3 py-3 text-[11px] text-text-secondary">
        Önizleme yüklenemedi. {error}
      </div>
    );
  }
  if (!result) return null;

  const currency = result.meta.currency ?? spec.basis?.currency ?? "try";
  const viz = spec.viz;

  if (viz === "kpi") {
    return (
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
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
  const tableColumns = result.columns.map((col) => {
    const isMetric = col.kind === "metric";
    return {
      key: col.id,
      header: col.label,
      align: isMetric ? "right" : "left",
      render: (row: RunRow) =>
        isMetric ? (
          <span className="tabular">{formatMetricValue(col.type, row.metrics[col.id], currency)}</span>
        ) : (
          <span>{row.dims[col.id] ?? "—"}</span>
        ),
    };
  }) as unknown as Column<RunRow>[];

  return <DataTable columns={tableColumns} rows={result.rows} emptyMessage="Bu seçim için veri yok." minWidth={320} />;
}
