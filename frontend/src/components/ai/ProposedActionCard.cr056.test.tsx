// CR-056 — plan critique + ask-with-options on the draft card. Asserts: the
// structural critique[] (duplicate/mislabel) renders a summary + badges + options;
// the data-aware checks (empty_dimension / single_row / identical_data) are detected
// from the MiniReportPreview run-results (no extra /studio/run); picking an option
// trims/retitles the IN-MEMORY draft and the preview updates; Oluştur creates the
// TRIMMED plan; "Tümünü tut" keeps all; a clean plan shows no critique panel; and the
// critique never mutates the plan before a click.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const CATALOG = {
    dimensions: [
      { id: "cost_category", label: "Maliyet kategorisi", type: "enum", group: "Maliyet", description: "", status: "available" },
      { id: "vendor", label: "Tedarikçi", type: "enum", group: "Taraf", description: "", status: "available" },
    ],
    metrics: [
      { id: "cost_try", label: "Maliyet (₺)", type: "currency", group: "Maliyet", description: "", status: "available", windowed: true },
      { id: "revenue", label: "Gelir", type: "currency", group: "Gelir", description: "", status: "available", windowed: false },
    ],
  };
  return {
    apiPut: vi.fn(() => Promise.resolve({})) as any,
    run: vi.fn(),
    catalog: vi.fn(() => Promise.resolve(CATALOG)),
    createDashboard: vi.fn((_body: any) => Promise.resolve({ id: "dash-new" })),
    createReport: vi.fn((_body: any) => Promise.resolve({ id: "rep-new" })),
    createSkill: vi.fn((_body: any) => Promise.resolve({ id: "skill-new" })),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
    navigate: vi.fn(),
    user: { role: "director" } as { role: string } | null,
    RESULTS: new Map<string, any>(),
  };
});

const meta = {
  row_count: 3,
  basis: { cost: "actual", currency: "try", financing: "excl", vat: "excl" },
  date_range: { from: null, to: null },
  comparison: null,
  currency: "try",
  truncated: false,
  unavailable: [],
  usd_missing_count: 0,
};
const res = (columns: any[], rows: any[], totals: Record<string, number>) => ({
  columns, rows, totals: { metrics: totals, deltas: null }, meta,
});
// A multi-row, multi-distinct default → no data-aware finding for un-registered specs.
const defaultRes = (spec: any) => {
  const dims = spec.dimensions ?? [];
  const metrics = spec.metrics ?? [];
  const cols = [
    ...dims.map((d: string) => ({ id: d, label: d, kind: "dimension", type: "enum" })),
    ...metrics.map((m: string) => ({ id: m, label: m, kind: "metric", type: "currency" })),
  ];
  const rows = ["a", "b", "c"].map((v) => ({
    dims: Object.fromEntries(dims.map((d: string) => [d, v])),
    metrics: Object.fromEntries(metrics.map((m: string) => [m, 100])),
    deltas: null,
  }));
  return res(cols, rows, Object.fromEntries(metrics.map((m: string) => [m, 300])));
};

vi.mock("@/lib/api", () => ({
  apiPut: h.apiPut,
  studio: { run: h.run, catalog: h.catalog, createDashboard: h.createDashboard, createReport: h.createReport },
  skills: { createSkill: h.createSkill },
}));
vi.mock("@/store/auth", () => ({ useAuth: () => ({ user: h.user }) }));
vi.mock("@/store/toast", () => ({
  toast: { success: h.toastSuccess, error: h.toastError, info: vi.fn(), warning: vi.fn() },
}));
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => h.navigate };
});

import { ProposedActionCard } from "@/components/ai/ProposedActionCard";

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

const DUP_SPEC = { metrics: ["cost_try"], dimensions: ["cost_category"], viz: "table" };
const widget = (id: string, title: string, spec: any) => ({
  id, type: "table", title, layout: { x: 0, y: 0, w: 6, h: 4 }, spec,
});

beforeEach(() => {
  vi.clearAllMocks();
  h.user = { role: "director" };
  h.RESULTS.clear();
  h.run.mockImplementation((spec: any) =>
    Promise.resolve(h.RESULTS.get(JSON.stringify(spec)) ?? defaultRes(spec))
  );
});
afterEach(() => vi.clearAllMocks());

describe("CR-056 — structural critique (duplicate) + trim", () => {
  const dupAction = () => ({
    kind: "draft_dashboard",
    kind_label: "Pano Taslağı",
    title: "DGN",
    widgets: [widget("w1", "Kalem Kalem Gider", { ...DUP_SPEC }), widget("w2", "Maliyet Kategorileri", { ...DUP_SPEC })],
    critique: [
      { type: "duplicate", widget_ids: ["w1", "w2"], message: "İki tablo aynı veriyi gösteriyor." },
    ],
  });

  it("renders the critique summary + options + badges on both widgets", async () => {
    wrap(<ProposedActionCard action={dupAction() as any} />);
    expect(await screen.findByText("İki tablo aynı veriyi gösteriyor.")).toBeInTheDocument();
    // Ask-with-options for a duplicate.
    expect(screen.getByText("İkisini de tut")).toBeInTheDocument();
    expect(screen.getByText(/Sadece .Kalem Kalem Gider./)).toBeInTheDocument();
    expect(screen.getByText(/Sadece .Maliyet Kategorileri./)).toBeInTheDocument();
    // A "Yinelenen" badge marks the affected widgets.
    await waitFor(() => expect(screen.getAllByText("Yinelenen").length).toBeGreaterThanOrEqual(1));
  });

  it('picking "Sadece A" trims the draft and Oluştur creates the trimmed plan', async () => {
    wrap(<ProposedActionCard action={dupAction() as any} />);
    fireEvent.click(await screen.findByText(/Sadece .Kalem Kalem Gider./));
    // Finding resolved → summary gone.
    await waitFor(() => expect(screen.queryByText("İki tablo aynı veriyi gösteriyor.")).not.toBeInTheDocument());
    fireEvent.click(screen.getByText("Oluştur"));
    await waitFor(() => expect(h.createDashboard).toHaveBeenCalled());
    const arg = h.createDashboard.mock.calls[0][0];
    expect(arg.widgets.map((w: any) => w.id)).toEqual(["w1"]); // w2 trimmed
  });

  it("critique never mutates the plan before a click — Oluştur keeps both", async () => {
    wrap(<ProposedActionCard action={dupAction() as any} />);
    await screen.findByText("İki tablo aynı veriyi gösteriyor.");
    fireEvent.click(screen.getByText("Oluştur"));
    await waitFor(() => expect(h.createDashboard).toHaveBeenCalled());
    expect(h.createDashboard.mock.calls[0][0].widgets.map((w: any) => w.id)).toEqual(["w1", "w2"]);
  });

  it('"Tümünü tut" dismisses findings and keeps all widgets', async () => {
    wrap(<ProposedActionCard action={dupAction() as any} />);
    fireEvent.click(await screen.findByText("Tümünü tut"));
    await waitFor(() => expect(screen.queryByText("İki tablo aynı veriyi gösteriyor.")).not.toBeInTheDocument());
    fireEvent.click(screen.getByText("Oluştur"));
    await waitFor(() => expect(h.createDashboard).toHaveBeenCalled());
    expect(h.createDashboard.mock.calls[0][0].widgets.map((w: any) => w.id)).toEqual(["w1", "w2"]);
  });
});

describe("CR-056 — structural critique (mislabel) retitle", () => {
  it('"Başlığı düzelt" strips the % label; Oluştur creates the retitled report', async () => {
    const action = {
      kind: "draft_report",
      kind_label: "Rapor Taslağı",
      title: "Maliyet Dağılımı (%)",
      spec: { metrics: ["cost_try"], dimensions: ["cost_category"], viz: "bar" },
      critique: [{ type: "mislabel", widget_ids: ["report"], message: "Başlık % ima ediyor ama ₺." }],
    };
    wrap(<ProposedActionCard action={action as any} />);
    fireEvent.click(await screen.findByText("Başlığı düzelt"));
    fireEvent.click(screen.getByText("Oluştur"));
    await waitFor(() => expect(h.createReport).toHaveBeenCalled());
    expect(h.createReport.mock.calls[0][0].title).toBe("Maliyet Dağılımı");
  });
});

describe("CR-056 — data-aware findings from preview results", () => {
  it("detects empty_dimension (one bucket) and Kaldır removes the widget", async () => {
    const emptySpec = { metrics: ["cost_try"], dimensions: ["vendor"], viz: "table" };
    h.RESULTS.set(
      JSON.stringify(emptySpec),
      res(
        [{ id: "vendor", label: "Tedarikçi", kind: "dimension", type: "enum" },
         { id: "cost_try", label: "Maliyet", kind: "metric", type: "currency" }],
        [{ dims: { vendor: null }, metrics: { cost_try: 500 }, deltas: null }],
        { cost_try: 500 }
      )
    );
    const action = {
      kind: "draft_dashboard", kind_label: "Pano Taslağı", title: "Pano",
      widgets: [widget("v1", "Tedarikçi Kırılımı", emptySpec), widget("c1", "Kategoriler", { ...DUP_SPEC })],
    };
    wrap(<ProposedActionCard action={action as any} />);
    // The empty-dimension finding appears once its preview result arrives.
    expect(await screen.findByText(/kırılımında veri yok/)).toBeInTheDocument();
    expect(screen.getAllByText("Veri yok").length).toBeGreaterThanOrEqual(1);
    // Kaldır trims it; the clean widget stays.
    fireEvent.click(screen.getByText("Kaldır"));
    await waitFor(() => expect(screen.queryByText(/kırılımında veri yok/)).not.toBeInTheDocument());
    fireEvent.click(screen.getByText("Oluştur"));
    await waitFor(() => expect(h.createDashboard).toHaveBeenCalled());
    expect(h.createDashboard.mock.calls[0][0].widgets.map((w: any) => w.id)).toEqual(["c1"]);
  });

  it("detects identical_data across different specs", async () => {
    const specA = { metrics: ["cost_try"], dimensions: ["cost_category"], viz: "table" };
    const specB = { metrics: ["revenue"], dimensions: ["cost_category"], viz: "bar" };
    const identical = res(
      [{ id: "cost_category", label: "Kategori", kind: "dimension", type: "enum" },
       { id: "x", label: "x", kind: "metric", type: "currency" }],
      [
        { dims: { cost_category: "A" }, metrics: { x: 10 }, deltas: null },
        { dims: { cost_category: "B" }, metrics: { x: 20 }, deltas: null },
      ],
      { x: 30 }
    );
    h.RESULTS.set(JSON.stringify(specA), identical);
    h.RESULTS.set(JSON.stringify(specB), identical);
    const action = {
      kind: "draft_dashboard", kind_label: "Pano Taslağı", title: "Pano",
      widgets: [widget("a1", "Gider", specA), widget("b1", "Gelir", specB)],
    };
    wrap(<ProposedActionCard action={action as any} />);
    expect(await screen.findByText(/aynı veriyi üretiyor/)).toBeInTheDocument();
  });
});

describe("CR-056 — a clean plan looks exactly as before", () => {
  it("shows no critique panel or badges", async () => {
    const action = {
      kind: "draft_dashboard", kind_label: "Pano Taslağı", title: "Temiz",
      widgets: [widget("w1", "Kategoriler", { ...DUP_SPEC }), widget("w2", "Gelir", { metrics: ["revenue"], dimensions: ["cost_category"], viz: "line" })],
    };
    wrap(<ProposedActionCard action={action as any} />);
    await waitFor(() => expect(h.run).toHaveBeenCalled());
    // Give results time to settle, then assert no critique surfaced.
    await waitFor(() => expect(h.run.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByText(/gözden geçirdim/)).not.toBeInTheDocument();
    expect(screen.queryByText("Yinelenen")).not.toBeInTheDocument();
    expect(screen.queryByText("Veri yok")).not.toBeInTheDocument();
    expect(screen.getByText("Oluştur")).toBeInTheDocument();
  });
});
