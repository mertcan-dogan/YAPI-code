// CR-034 — Pano (dashboard) canvas. Asserts every widget kind renders from one
// batch runDashboard (kpi→KPICard, chart→StudioChart, table→DataTable, text
// content, report→KPI + "Rapora git"); an unavailable report → the
// "Bu rapor artık kullanılamıyor" placeholder; a per-widget run failure → an
// error+retry (never a silent empty); Save persists each widget's layout{x,y,w,h}
// in the PATCH body; the visibility control offers Özel/Herkes with Takım disabled
// "Yakında"; and a windowed:false metric under a global date range shows the
// "tüm proje, bugüne kadar" tag. api/auth/toast/router mocked; the canvas
// components (KPICard / StudioChart / DataTable / MarkdownText) render for real.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const CATALOG = {
    dimensions: [
      { id: "project", label: "Proje", type: "enum", group: "Proje", description: "Projeye göre kır.", status: "available" },
      { id: "month", label: "Ay", type: "date", group: "Zaman", description: "Aya göre.", status: "available" },
    ],
    metrics: [
      { id: "cost_try", label: "Maliyet (₺)", type: "currency", group: "Maliyet", description: "Maliyet.", status: "available", windowed: true },
      { id: "revenue", label: "Gelir", type: "currency", group: "Gelir", description: "Gelir.", status: "available", windowed: false },
      { id: "receivables", label: "Açık alacak", type: "currency", group: "Alacak", description: "Alacak.", status: "available", windowed: false },
      { id: "irr", label: "IRR", type: "percent", group: "Getiri", description: "IRR.", status: "available", windowed: false },
      { id: "budget", label: "Bütçe", type: "currency", group: "Maliyet", description: "Bütçe.", status: "available", windowed: false },
    ],
  };
  const labelOf = (id: string) => [...CATALOG.dimensions, ...CATALOG.metrics].find((x) => x.id === id)?.label ?? id;
  const typeOf = (id: string) => CATALOG.metrics.find((x) => x.id === id)?.type ?? "currency";
  const buildResult = (spec: any) => {
    const dims: string[] = spec.dimensions ?? [];
    const metrics: string[] = spec.metrics ?? [];
    const viz = spec.viz ?? "table";
    const result: any = {
      columns: [
        ...dims.map((d) => ({ id: d, label: labelOf(d), kind: "dimension", type: "enum" })),
        ...metrics.map((m) => ({ id: m, label: labelOf(m), kind: "metric", type: typeOf(m) })),
      ],
      rows: [
        {
          dims: Object.fromEntries(dims.map((d) => [d, "Proje A"])),
          metrics: Object.fromEntries(metrics.map((m) => [m, 1000])),
          deltas: null,
        },
      ],
      totals: { metrics: Object.fromEntries(metrics.map((m) => [m, 1000])), deltas: null },
      meta: {
        row_count: 1, basis: { cost: "actual", currency: "try", financing: "excl", vat: "excl" },
        date_range: { from: null, to: null }, comparison: null, currency: "try",
        truncated: false, unavailable: [], usd_missing_count: 0,
      },
    };
    if (viz === "line" || viz === "area" || viz === "bar") {
      result.series = metrics.map((m) => ({
        name: labelOf(m), metric: m,
        points: [{ x: "2026-01", y: 1000 }, { x: "2026-02", y: 2000 }], compare: null,
      }));
    }
    return result;
  };
  return {
    params: {} as any,
    location: { state: null } as any,
    user: { id: "me", role: "director", full_name: "Ben" },
    dashboard: null as any,
    batch: {} as any,
    report: null as any,
    runMode: "ok" as "ok" | "fail",
    reportMode: "ok" as "ok" | "fail",
    saved: null as any,
    CATALOG, buildResult,
  };
});

vi.mock("@/lib/api", () => ({
  studio: {
    catalog: vi.fn(() => Promise.resolve(h.CATALOG)),
    getDashboard: vi.fn(() => Promise.resolve(h.dashboard)),
    runDashboard: vi.fn(() => (h.runMode === "fail" ? Promise.reject(new Error("boom")) : Promise.resolve(h.batch))),
    getReport: vi.fn(() => (h.reportMode === "fail" ? Promise.reject(new Error("gone")) : Promise.resolve(h.report))),
    run: vi.fn((spec: any) => Promise.resolve(h.buildResult(spec))),
    updateDashboard: vi.fn(() => Promise.resolve(h.saved)),
    createDashboard: vi.fn(() => Promise.resolve({ id: "new1" })),
    exportDashboardBlob: vi.fn(() => Promise.resolve(new Blob())),
    listReports: vi.fn(() => Promise.resolve([])),
  },
}));
vi.mock("@/store/auth", () => ({ useAuth: (sel: any) => sel({ user: h.user }) }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
const navigate = vi.fn();
vi.mock("react-router-dom", () => ({ useParams: () => h.params, useNavigate: () => navigate, useLocation: () => h.location }));

import { studio } from "@/lib/api";
import StudioDashboardCanvasPage from "./StudioDashboardCanvasPage";

const TS = "2026-06-26T00:00:00Z";

const widget = (id: string, type: string, extra: any) => ({ id, type, title: extra.title ?? id, layout: extra.layout ?? { x: 0, y: 0, w: 6, h: 4 }, ...extra });

beforeEach(() => {
  h.params = { id: "d1" };
  h.location = { state: null };
  h.user = { id: "me", role: "director", full_name: "Ben" };
  h.dashboard = null;
  h.batch = {};
  h.report = null;
  h.runMode = "ok";
  h.reportMode = "ok";
  h.saved = null;
  vi.clearAllMocks();
});
afterEach(cleanup);

it("renders every widget kind from one batch runDashboard", async () => {
  const wk = widget("wk", "kpi", { title: "KPI widget", spec: { metrics: ["cost_try"], dimensions: [], viz: "kpi" } });
  const wc = widget("wc", "chart", { title: "Grafik widget", spec: { metrics: ["revenue"], dimensions: ["month"], viz: "line", chart: { x: "month", y_left: ["revenue"] } } });
  const wt = widget("wt", "table", { title: "Tablo widget", spec: { metrics: ["receivables"], dimensions: ["project"], viz: "table" } });
  const wx = widget("wx", "text", { title: "Metin widget", content: "Merhaba Pano" });
  const wr = widget("wr", "report", { title: "Rapor widget", report_id: "rep1" });
  h.dashboard = { id: "d1", owner_id: "me", is_owner: true, created_at: TS, updated_at: TS, title: "Karma Pano", date_range: null, comparison: null, filters: [], visibility: "private", labels: [], widgets: [wk, wc, wt, wx, wr] };
  h.batch = { wk: h.buildResult(wk.spec), wc: h.buildResult(wc.spec), wt: h.buildResult(wt.spec) };
  h.report = { id: "rep1", title: "Gömülü Rapor", spec: { metrics: ["irr"], dimensions: [], viz: "kpi" } };

  render(<StudioDashboardCanvasPage />);

  // kpi → KPICard label, table → header + row dim, text → content.
  expect(await screen.findByText("Maliyet (₺)")).toBeInTheDocument();
  expect(screen.getByText("Açık alacak")).toBeInTheDocument();
  expect(screen.getByText("Proje A")).toBeInTheDocument();
  expect(screen.getByText("Merhaba Pano")).toBeInTheDocument();

  // chart → StudioChart container (never the "no data" empty message).
  expect(screen.queryByText("Grafik için veri yok.")).not.toBeInTheDocument();
  expect(document.querySelector(".recharts-responsive-container")).toBeTruthy();

  // report → embedded KPI (IRR) + a "Rapora git" link.
  expect(await screen.findByText("IRR")).toBeInTheDocument();
  expect(screen.getAllByText("Rapora git").length).toBeGreaterThan(0);

  // The data widgets came from a SINGLE batch call.
  expect(studio.runDashboard).toHaveBeenCalledTimes(1);
  expect(studio.runDashboard).toHaveBeenCalledWith("d1");
});

it("shows the unavailable placeholder for a report widget whose target is gone", async () => {
  const wr = widget("wr", "report", { title: "Kırık rapor", report_id: "gone" });
  h.dashboard = { id: "d1", owner_id: "me", is_owner: true, created_at: TS, updated_at: TS, title: "Pano", date_range: null, comparison: null, filters: [], visibility: "private", labels: [], widgets: [wr] };
  h.reportMode = "fail";

  render(<StudioDashboardCanvasPage />);
  expect(await screen.findByText(/Bu rapor artık kullanılamıyor/)).toBeInTheDocument();
  // The "Rapora git" affordance still renders (the widget header link).
  expect(screen.getAllByText("Rapora git").length).toBeGreaterThan(0);
});

it("surfaces a per-widget error + retry when the run fails, and recovers", async () => {
  const wk = widget("wk", "kpi", { title: "KPI widget", spec: { metrics: ["cost_try"], dimensions: [], viz: "kpi" } });
  h.dashboard = { id: "d1", owner_id: "me", is_owner: true, created_at: TS, updated_at: TS, title: "Pano", date_range: null, comparison: null, filters: [], visibility: "private", labels: [], widgets: [wk] };
  h.runMode = "fail"; // the batch rejects

  render(<StudioDashboardCanvasPage />);
  const retry = await screen.findByText("Tekrar Dene");
  expect(retry).toBeInTheDocument();
  expect(screen.getByText(/Widget yüklenemedi/)).toBeInTheDocument();

  // Retry runs the widget via POST /studio/run → it renders.
  fireEvent.click(retry);
  await waitFor(() => expect(studio.run).toHaveBeenCalled());
  expect(await screen.findByText("Maliyet (₺)")).toBeInTheDocument();
});

it("Save persists each widget's layout{x,y,w,h} in the PATCH body", async () => {
  const wk = widget("wk", "kpi", { title: "KPI widget", layout: { x: 2, y: 3, w: 4, h: 5 }, spec: { metrics: ["cost_try"], dimensions: [], viz: "kpi" } });
  h.dashboard = { id: "d1", owner_id: "me", is_owner: true, created_at: TS, updated_at: TS, title: "Pano", date_range: null, comparison: null, filters: [], visibility: "private", labels: [], widgets: [wk] };
  h.batch = { wk: h.buildResult(wk.spec) };
  h.saved = { ...h.dashboard, title: "Yeni başlık" };

  render(<StudioDashboardCanvasPage />);
  await screen.findByText("Maliyet (₺)");

  // Make the pano dirty so the (disabled-when-clean) Kaydet button enables.
  fireEvent.change(screen.getByLabelText("Pano başlığı"), { target: { value: "Yeni başlık" } });
  fireEvent.click(screen.getByText("Kaydet"));

  await waitFor(() => expect(studio.updateDashboard).toHaveBeenCalled());
  const [id, body] = (studio.updateDashboard as any).mock.calls[0];
  expect(id).toBe("d1");
  expect(body.widgets[0].layout).toEqual({ x: 2, y: 3, w: 4, h: 5 });
});

it("visibility offers Özel/Herkes with Takım disabled 'Yakında'", async () => {
  h.params = {}; // new pano → no fetch, canEdit true
  render(<StudioDashboardCanvasPage />);
  await screen.findByText("Özel");

  expect(screen.getByText("Herkes")).toBeInTheDocument();
  const takim = screen.getByText("Takım").closest("button") as HTMLButtonElement;
  expect(takim).toBeDisabled();
  expect(within(takim).getByText("Yakında")).toBeInTheDocument();
});

it("tags a windowed:false metric 'tüm proje, bugüne kadar' under a global date range", async () => {
  const wt = widget("wt", "table", { title: "Bütçe tablosu", spec: { metrics: ["budget"], dimensions: ["project"], viz: "table" } });
  h.dashboard = { id: "d1", owner_id: "me", is_owner: true, created_at: TS, updated_at: TS, title: "Pano", date_range: { preset: "last_6_months" }, comparison: null, filters: [], visibility: "private", labels: [], widgets: [wt] };
  h.batch = { wt: h.buildResult(wt.spec) };

  render(<StudioDashboardCanvasPage />);
  await screen.findByText("Bütçe"); // table header (windowed:false metric)
  expect(screen.getAllByText("tüm proje, bugüne kadar").length).toBeGreaterThan(0);
});

// --- CR-034.1 Fix 1: KPI hides Boyutlar in the widget config modal ---

it("KPI widget hides Boyutlar + shows the hint in the config modal", async () => {
  h.params = {}; // new pano → canEdit, no fetch
  render(<StudioDashboardCanvasPage />);
  await screen.findByLabelText("Widget ekle");

  fireEvent.click(screen.getByLabelText("Widget ekle"));
  fireEvent.click(screen.getByText("KPI")); // → draft at viz:"kpi", modal opens on the Veri tab

  // The Veri tab shows the KPI hint, not the Boyutlar picker.
  expect(
    screen.getByText("KPI tek bir değer gösterir — kırılım için Tablo veya Grafik kullanın.")
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Boyutlar ara")).toBeNull();
  // The metric picker still renders.
  expect(screen.getByLabelText("Metrikler ara")).toBeInTheDocument();
});

it("switching a data widget's viz to KPI clears + hides Boyutlar in the modal", async () => {
  h.params = {};
  render(<StudioDashboardCanvasPage />);
  await screen.findByLabelText("Widget ekle");

  fireEvent.click(screen.getByLabelText("Widget ekle"));
  fireEvent.click(screen.getByText("Tablo")); // a Tablo widget opens at viz:"table"

  // The Boyutlar picker is present for a table; pick the "Proje" item (not its header).
  expect(screen.getByLabelText("Boyutlar ara")).toBeInTheDocument();
  const proje = screen
    .getAllByText("Proje")
    .map((el) => el.closest("button"))
    .find((b): b is HTMLButtonElement => !!b);
  fireEvent.click(proje!);

  // Flip the Segmented to KPI on the Grafik tab → the Boyutlar picker is replaced by
  // the hint (dimensions are cleared + hidden).
  fireEvent.click(screen.getByText("Grafik"));
  fireEvent.click(screen.getByText("KPI"));
  fireEvent.click(screen.getByText("Veri"));

  expect(
    screen.getByText("KPI tek bir değer gösterir — kırılım için Tablo veya Grafik kullanın.")
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Boyutlar ara")).toBeNull();
});

// --- CR-034.1 Fix 2: section move-up/down reorders bands via widgets[] order ---

it("section move up/down reorders bands and persists via widgets[] order", async () => {
  const wa = widget("wa", "kpi", { title: "A widget", section: "Bölüm A", spec: { metrics: ["cost_try"], dimensions: [], viz: "kpi" } });
  const wb = widget("wb", "table", { title: "B widget", section: "Bölüm B", spec: { metrics: ["revenue"], dimensions: ["project"], viz: "table" } });
  h.dashboard = { id: "d1", owner_id: "me", is_owner: true, created_at: TS, updated_at: TS, title: "Pano", date_range: null, comparison: null, filters: [], visibility: "private", labels: [], widgets: [wa, wb] };
  h.batch = { wa: h.buildResult(wa.spec), wb: h.buildResult(wb.spec) };
  h.saved = { ...h.dashboard }; // updateDashboard echo

  render(<StudioDashboardCanvasPage />);
  await screen.findByText("BÖLÜM A"); // band label is uppercased
  expect(screen.getByText("BÖLÜM B")).toBeInTheDocument();

  // Ends are disabled: the first band can't go up, the last band can't go down. The
  // aria-labels use the RAW (not uppercased) section label.
  expect(screen.getByLabelText("Bölüm A bölümünü yukarı taşı")).toBeDisabled();
  expect(screen.getByLabelText("Bölüm B bölümünü aşağı taşı")).toBeDisabled();
  expect(screen.getByLabelText("Bölüm A bölümünü aşağı taşı")).not.toBeDisabled();

  // Move "Bölüm A" down → B becomes the first widget block.
  fireEvent.click(screen.getByLabelText("Bölüm A bölümünü aşağı taşı"));
  fireEvent.click(screen.getByText("Kaydet"));

  await waitFor(() => expect(studio.updateDashboard).toHaveBeenCalled());
  const [savedId, body] = (studio.updateDashboard as any).mock.calls[0];
  expect(savedId).toBe("d1");
  expect(body.widgets.map((w: any) => w.id)).toEqual(["wb", "wa"]);
});

// --- CR-035: AI authoring hand-off (draft widgets on /new) ---

it("initializes widgets/title from draftWidgets on /new (Düzenle from an AI pano proposal), creating nothing", async () => {
  h.params = {}; // /new route
  const wk = widget("wk", "kpi", { title: "KPI widget", spec: { metrics: ["cost_try"], dimensions: [], viz: "kpi" } });
  h.location = { state: { draftTitle: "AI panosu", draftWidgets: [wk] } };

  render(<StudioDashboardCanvasPage />);

  // The draft widget renders (per-widget POST /studio/run on an unsaved pano).
  expect(await screen.findByText("Maliyet (₺)")).toBeInTheDocument();
  // The title is seeded from the draft.
  expect((screen.getByLabelText("Pano başlığı") as HTMLInputElement).value).toBe("AI panosu");
  expect(studio.run).toHaveBeenCalled();
  // Nothing is persisted until the user clicks Kaydet.
  expect(studio.createDashboard).not.toHaveBeenCalled();
  expect(studio.updateDashboard).not.toHaveBeenCalled();
});

// --- CR-034.1 Fix 4: dashboard export loading state ---

it("dashboard export shows a loading state until the blob resolves", async () => {
  const wk = widget("wk", "kpi", { title: "KPI widget", spec: { metrics: ["cost_try"], dimensions: [], viz: "kpi" } });
  h.dashboard = { id: "d1", owner_id: "me", is_owner: true, created_at: TS, updated_at: TS, title: "Pano", date_range: null, comparison: null, filters: [], visibility: "private", labels: [], widgets: [wk] };
  h.batch = { wk: h.buildResult(wk.spec) };

  // A deferred export blob we resolve by hand.
  let resolveFn: (b: Blob) => void;
  const deferred = new Promise<Blob>((r) => {
    resolveFn = r;
  });
  (studio.exportDashboardBlob as any).mockReturnValue(deferred);

  // jsdom has no object-URL plumbing — stub it (restored in finally).
  const origCreate = (URL as any).createObjectURL;
  const origRevoke = (URL as any).revokeObjectURL;
  (URL as any).createObjectURL = vi.fn(() => "blob:mock");
  (URL as any).revokeObjectURL = vi.fn();

  try {
    render(<StudioDashboardCanvasPage />);
    await screen.findByText("Maliyet (₺)");

    fireEvent.click(screen.getByLabelText("Dışa aktar")); // open the export menu
    fireEvent.click(screen.getByText("PDF"));

    // While the blob is in flight: the busy indicator replaces the trigger.
    expect(await screen.findByText("Dışa aktarılıyor…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Dışa aktar")).toBeNull();
    expect(studio.exportDashboardBlob).toHaveBeenCalledWith("d1", "pdf");

    // Resolve → it restores to the normal "Dışa aktar" trigger.
    resolveFn!(new Blob());
    await waitFor(() => expect(screen.getByLabelText("Dışa aktar")).toBeInTheDocument());
    expect(screen.queryByText("Dışa aktarılıyor…")).toBeNull();
  } finally {
    (URL as any).createObjectURL = origCreate;
    (URL as any).revokeObjectURL = origRevoke;
  }
});
