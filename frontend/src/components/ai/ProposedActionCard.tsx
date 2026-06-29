import { DataTable, type Column } from "@/components/DataTable";
import { KPICard } from "@/components/KPICard";
import { StudioChart, formatMetricValue } from "@/components/StudioChart";
import { apiPut, skills, studio } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { ProposedAction } from "@/types/agent";
import type { CatalogDimension, CatalogMetric, RunResult, RunRow, StudioSpec } from "@/types/studio";
import { ArrowRight, Check, FileSpreadsheet, FileText, Pencil, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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

export function ProposedActionCard({
  action,
  onResolve,
}: {
  action: ProposedAction;
  // CR-039 — fired when a DRAFT is created (Oluştur) or dismissed (İptal/Düzenle)
  // so the page stops threading it as the active refine draft.
  onResolve?: (action: ProposedAction) => void;
}) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isDirector = user?.role === "director";
  const [state, setState] = useState<Decision>("pending");
  const [busy, setBusy] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [reason, setReason] = useState("");
  // CR-039 — the visibility the user picks before creating (default Özel/private).
  const [vis, setVis] = useState<"private" | "company">(action.visibility === "company" ? "company" : "private");
  // CR-039 — after Oluştur we STAY in chat and offer an "Aç" button to this target
  // (rather than auto-navigating), so the user can keep iterating in the thread.
  const [createdTarget, setCreatedTarget] = useState<string | null>(null);

  // CR-035 legacy approval kinds (dormant) + CR-039 authoring DRAFT kinds.
  const isReport = action.kind === "agent_create_report";
  const isDashboard = action.kind === "agent_create_dashboard";
  const isDraftReport = action.kind === "draft_report";
  const isDraftDashboard = action.kind === "draft_dashboard";
  // CR-044 — "draft_skill": a reusable file recipe (dashboard-shaped plan + format).
  const isDraftSkill = action.kind === "draft_skill";
  const isDraft = isDraftReport || isDraftDashboard || isDraftSkill;
  const isLegacyStudio = isReport || isDashboard;
  const isReportKind = isReport || isDraftReport;
  const isDashboardKind = isDashboard || isDraftDashboard;
  // A skill's plan is dashboard-shaped (widgets[]) — its preview/summary reuse the
  // dashboard path, keyed off plan.widgets instead of the top-level widgets[].
  const isAuthoring = isReportKind || isDashboardKind || isDraftSkill;
  // The skill plan's widgets (the figures come from the engine at run time).
  const skillWidgets: any[] = isDraftSkill ? action.plan?.widgets ?? [] : [];

  // Catalog (cached) — used ONLY for the studio kinds to label dimension/metric
  // ids. Falls back to raw ids if it can't load (ids are acceptable per CR-035).
  const [metricById, setMetricById] = useState<Map<string, CatalogMetric>>(new Map());
  const [dimById, setDimById] = useState<Map<string, CatalogDimension>>(new Map());
  useEffect(() => {
    if (!isAuthoring) return;
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
  }, [isAuthoring]);

  const labelOf = (id: string) => metricById.get(id)?.label ?? dimById.get(id)?.label ?? id;

  // CR-049 — the data widgets to live-preview as a scrollable mini-report. A report
  // is its single spec; a dashboard/skill is EACH data widget (kpi/chart/table) with
  // a non-empty spec, in plan order. text/empty widgets are dropped. (Was: only the
  // first widget — the draft card now shows the whole report, scrollable + capped.)
  const previewWidgets = useMemo<{ key: string; title: string | null; spec: StudioSpec }[]>(() => {
    const valid = (s: any): StudioSpec | null =>
      s && Array.isArray(s.metrics) && s.metrics.length > 0 ? (s as StudioSpec) : null;
    if (isReportKind) {
      const s = valid(action.spec);
      return s ? [{ key: "report", title: null, spec: s }] : [];
    }
    const widgetList = isDraftSkill ? skillWidgets : isDashboardKind ? action.widgets ?? [] : [];
    const out: { key: string; title: string | null; spec: StudioSpec }[] = [];
    (widgetList as any[]).forEach((w, i) => {
      const s = valid(w?.spec);
      // `idx-${i}` fallback can't collide with an explicit widget id (e.g. "w3").
      if (s) out.push({ key: w?.id != null ? String(w.id) : `idx-${i}`, title: w?.title ?? null, spec: s });
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isReportKind, isDashboardKind, isDraftSkill, action.spec, action.widgets, action.plan]);

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
      if (isLegacyStudio && created?.id) {
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
  // A skill has no unsaved-plan editor route — its plan is refined by chat (the
  // hint), so Düzenle there only dismisses the card; the user keeps typing.
  const edit = () => {
    if (isReportKind) {
      navigate("/studio/reports/new", { state: { draftSpec: action.spec, draftTitle: action.title } });
    } else if (isDashboardKind) {
      navigate("/studio/dashboards/new", {
        state: { draftWidgets: action.widgets, draftTitle: action.title, draftDateRange: action.date_range },
      });
    }
    onResolve?.(action);  // CR-039 — editing elsewhere ⇒ stop threading this draft
  };

  // CR-039 — OLUŞTUR: the user creates THEIR OWN report/pano via the existing
  // create endpoint (as themselves — same authz as the manual editor). The agent
  // wrote nothing; this explicit click is the only write. We stay in chat and show
  // an "Aç" button rather than auto-navigating, so the user can keep iterating.
  const create = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (isDraftReport) {
        const r = await studio.createReport({
          title: action.title ?? "Rapor", spec: action.spec, visibility: vis, labels: action.labels ?? null,
        });
        setCreatedTarget(`/studio/reports/${r.id}`);
        toast.success("Rapor oluşturuldu.");
      } else if (isDraftSkill) {
        // CR-044 — the user's save action: create THEIR OWN skill (owner = caller,
        // no director gate). The agent wrote nothing; this explicit click is the
        // only write. We stay in chat and offer an "Aç" link to Uygulamalar.
        const r = await skills.createSkill({
          name: action.title ?? "Beceri",
          instruction: action.instruction ?? "",
          plan: action.plan as any,
          format: action.format ?? "xlsx",
          visibility: vis,
          labels: action.labels ?? null,
        });
        setCreatedTarget(`/studio/skills`);
        void r;
        toast.success("Beceri kaydedildi.");
      } else {
        const r = await studio.createDashboard({
          title: action.title ?? "Pano", widgets: action.widgets ?? [], date_range: action.date_range ?? null,
          comparison: action.comparison ?? null, filters: action.filters ?? null, visibility: vis,
          labels: action.labels ?? null,
        });
        setCreatedTarget(`/studio/dashboards/${r.id}`);
        toast.success("Pano oluşturuldu.");
      }
      setState("approved");
      onResolve?.(action);  // created ⇒ no longer the active refine draft
    } catch (e: any) {
      toast.error(e?.message ?? "Oluşturulamadı");
    } finally {
      setBusy(false);
    }
  };

  // İptal — dismiss the draft card (nothing was ever written).
  const cancel = () => {
    setState("rejected");
    onResolve?.(action);
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

  // CR-044 — a skill's plan summary: an output-format chip + the widget count +
  // each widget's title/type as a chip (no figures — those come from the engine).
  const skillSummary = () => {
    const fmt = action.format ?? action.plan?.format ?? "xlsx";
    const fmtLabel = fmt === "pdf" ? "PDF" : "Excel (.xlsx)";
    const dr = dateRangeLabel(action.plan?.date_range);
    return (
      <div className="mt-2 flex flex-wrap gap-1.5">
        <span className="inline-flex items-center gap-1 rounded-control border border-border bg-surface px-2 py-0.5 text-[11px] font-medium text-text-secondary">
          {fmt === "pdf" ? (
            <FileText className="h-3 w-3 text-danger" />
          ) : (
            <FileSpreadsheet className="h-3 w-3 text-success" />
          )}
          {fmtLabel}
        </span>
        <Chip label="Bölüm" value={`${skillWidgets.length} adet`} />
        {dr && <Chip label="Tarih" value={dr} />}
        {skillWidgets.map((w: any, i: number) => (
          <Chip
            key={w.id ?? i}
            label={w.title || "Bölüm"}
            value={VIZ_LABELS[w?.spec?.viz] ?? w?.type ?? "—"}
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
            {isDraft ? "Yapı AI bir taslak hazırladı" : "Yapı AI şunu öneriyor"}
            <span className="ml-1 font-normal text-text-secondary">· {action.kind_label}</span>
          </p>
          {action.description && (
            <p className="mt-0.5 break-words text-[13px] text-text-primary">{action.description}</p>
          )}

          {/* CR-035/CR-039/CR-044 — spec summary + live preview for the authoring kinds. */}
          {isAuthoring && (
            <>
              {action.title && <p className="mt-1 text-[13px] font-semibold text-text-primary">{action.title}</p>}
              {isReportKind ? reportSummary() : isDraftSkill ? skillSummary() : dashboardSummary()}
              {previewWidgets.length > 0 ? (
                <MiniReportPreview
                  widgets={previewWidgets}
                  metricById={metricById}
                  showTitles={isDashboardKind || isDraftSkill}
                />
              ) : (
                <p className="mt-2 text-[11px] text-text-faint">Önizlenecek veri yok.</p>
              )}
            </>
          )}

          {state === "approved" ? (
            isDraft ? (
              // CR-039/CR-044 — created: stay in chat, offer "Aç" (no auto-navigation).
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1 text-xs font-medium text-success">
                  <Check className="h-3.5 w-3.5" />{" "}
                  {isDraftSkill ? "Beceri kaydedildi." : isDraftDashboard ? "Pano oluşturuldu." : "Rapor oluşturuldu."}
                </span>
                {createdTarget && (
                  <button
                    onClick={() => navigate(createdTarget)}
                    className="focus-ring inline-flex items-center gap-1 rounded-control bg-brand px-3 py-1 text-xs font-medium text-white transition hover:bg-brand/90"
                  >
                    {isDraftSkill ? "Uygulamalar" : "Aç"} <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            ) : (
              <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-success">
                <Check className="h-3.5 w-3.5" />{" "}
                {isLegacyStudio ? (isDashboard ? "Pano oluşturuldu." : "Rapor oluşturuldu.") : "Onaylandı ve uygulandı."}
              </p>
            )
          ) : state === "rejected" ? (
            <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-danger">
              <X className="h-3.5 w-3.5" /> {isDraft ? "İptal edildi." : "Reddedildi."}
            </p>
          ) : isDraft ? (
            // CR-039 — DRAFT actions: Oluştur / Düzenle / İptal. No director gate —
            // any user creates THEIR OWN report/pano (same authz as the editor).
            <div className="mt-2 space-y-2">
              <div className="flex items-center gap-2 text-[11px]">
                <span className="text-text-faint">Görünürlük:</span>
                <div className="inline-flex overflow-hidden rounded-control border border-border">
                  <button
                    type="button"
                    onClick={() => setVis("private")}
                    className={cn("px-2 py-0.5 transition-colors", vis === "private" ? "bg-brand text-white" : "bg-surface text-text-secondary hover:bg-surface-hover")}
                  >
                    Özel
                  </button>
                  <button
                    type="button"
                    onClick={() => setVis("company")}
                    className={cn("px-2 py-0.5 transition-colors", vis === "company" ? "bg-brand text-white" : "bg-surface text-text-secondary hover:bg-surface-hover")}
                  >
                    Herkes
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={create}
                  disabled={busy}
                  className="focus-ring rounded-control bg-brand px-3 py-1 text-xs font-medium text-white transition hover:bg-brand/90 disabled:opacity-50"
                >
                  {isDraftSkill ? "Beceri olarak kaydet" : "Oluştur"}
                </button>
                {/* CR-044.1 — a skill has no editor page (it's a free-form instruction
                    + compiled plan), so Düzenle would silently dismiss the draft.
                    Hide it for draft_skill; report/pano drafts keep it (they have an
                    editor). Skill drafts refine by chatting (the hint below). */}
                {!isDraftSkill && (
                  <button
                    onClick={edit}
                    disabled={busy}
                    className="focus-ring inline-flex items-center gap-1 rounded-control border border-border px-3 py-1 text-xs font-medium text-text-primary transition hover:border-brand hover:text-brand disabled:opacity-50"
                  >
                    <Pencil className="h-3.5 w-3.5" /> Düzenle
                  </button>
                )}
                <button
                  onClick={cancel}
                  disabled={busy}
                  className="focus-ring rounded-control border border-border px-3 py-1 text-xs font-medium text-text-primary transition hover:border-danger hover:text-danger disabled:opacity-50"
                >
                  İptal
                </button>
              </div>
              <p className="text-[11px] text-text-faint">Değiştirmek için yazmaya devam edin · oluşturunca sizin olur.</p>
            </div>
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
                  {isLegacyStudio && (
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
// CR-049 — scrollable multi-widget mini-report preview. Renders the plan's data
// widgets stacked in a scrollable container (each reusing StudioRunPreview), capped
// at the first PREVIEW_CAP with a "Tam önizleme" expand revealing the rest. The cap
// bounds how many /studio/run calls a draft card fires; a per-widget title labels
// each section for dashboards/skills (a single report needs none).
// --------------------------------------------------------------------------- #
const PREVIEW_CAP = 6;

// Defer mounting a child (and thus the /studio/run it fires) until its row scrolls
// into view, so a long mini-report doesn't fire every preview's request at once.
// When IntersectionObserver is unavailable (jsdom/tests, very old browsers) we mount
// immediately — correctness over the optimization. A rootMargin pre-loads the row
// just below the fold for a seamless scroll.
function LazyMount({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [show, setShow] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (show || typeof IntersectionObserver === "undefined") return;
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShow(true);
          io.disconnect();
        }
      },
      { rootMargin: "120px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [show]);
  return (
    <div ref={ref}>
      {show ? (
        children
      ) : (
        <div className="rounded-control border border-border bg-surface px-3 py-4 text-center text-[11px] text-text-muted">
          Önizleme hazırlanıyor…
        </div>
      )}
    </div>
  );
}

function MiniReportPreview({
  widgets,
  metricById,
  showTitles,
}: {
  widgets: { key: string; title: string | null; spec: StudioSpec }[];
  metricById: Map<string, CatalogMetric>;
  showTitles: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const hidden = Math.max(0, widgets.length - PREVIEW_CAP);
  const visible = expanded ? widgets : widgets.slice(0, PREVIEW_CAP);
  return (
    <div className="mt-2">
      <div className="max-h-[26rem] space-y-3 overflow-y-auto rounded-control border border-border bg-surface/40 p-2">
        {visible.map((w) => (
          <div key={w.key}>
            {showTitles && w.title && (
              <p className="mb-1 text-[11px] font-medium text-text-secondary">{w.title}</p>
            )}
            <LazyMount>
              <StudioRunPreview spec={w.spec} metricById={metricById} />
            </LazyMount>
          </div>
        ))}
      </div>
      {hidden > 0 && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="focus-ring mt-1.5 text-[11px] font-medium text-brand hover:underline"
        >
          Tam önizleme · +{hidden} widget daha
        </button>
      )}
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
