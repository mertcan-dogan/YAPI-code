// CR-033 — Report editor. Asserts: coming_soon metric shows "Yakında" and is not
// selectable; selecting a metric fires the debounced /studio/run and renders the
// table; the visibility control offers Özel/Herkes with Takım disabled "Yakında";
// the windowing tag appears on a windowed:false metric once a date range is set;
// a /studio/run failure surfaces an error + retry; Save calls POST /studio/reports.
// api/auth/toast/router are mocked; the catalog + run shapes mirror the backend.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const CATALOG = {
    dimensions: [
      { id: "project", label: "Proje", type: "enum", group: "Proje", description: "Projeye göre kır.", status: "available" },
      { id: "month", label: "Ay", type: "date", group: "Zaman", description: "Aya göre kır.", status: "available" },
    ],
    metrics: [
      { id: "cost_try", label: "Maliyet (₺)", type: "currency", group: "Maliyet", description: "Gerçekleşen maliyet.", status: "available", windowed: true },
      { id: "budget", label: "Bütçe", type: "currency", group: "Maliyet", description: "Revize bütçe.", status: "available", windowed: false },
      { id: "dso", label: "DSO", type: "number", group: "Alacak", description: "Tahsilat süresi.", status: "coming_soon", windowed: false },
    ],
  };
  const labelOf = (id: string) =>
    [...CATALOG.dimensions, ...CATALOG.metrics].find((x) => x.id === id)?.label ?? id;
  const buildResult = (spec: any) => ({
    columns: [
      ...spec.dimensions.map((d: string) => ({ id: d, label: labelOf(d), kind: "dimension", type: "enum" })),
      ...spec.metrics.map((m: string) => ({ id: m, label: labelOf(m), kind: "metric", type: "currency" })),
    ],
    rows: [
      {
        dims: Object.fromEntries(spec.dimensions.map((d: string) => [d, "Proje A"])),
        metrics: Object.fromEntries(spec.metrics.map((m: string) => [m, 1000])),
        deltas: null,
      },
    ],
    totals: { metrics: Object.fromEntries(spec.metrics.map((m: string) => [m, 1000])), deltas: null },
    meta: {
      row_count: 1,
      basis: { cost: "actual", currency: "try", financing: "excl", vat: "excl" },
      date_range: { from: null, to: null },
      comparison: null,
      currency: "try",
      truncated: false,
      unavailable: [],
      usd_missing_count: 0,
    },
  });
  return { params: {} as any, user: { id: "me", role: "director", full_name: "Ben" }, runMode: "ok" as "ok" | "fail", CATALOG, buildResult };
});

vi.mock("@/lib/api", () => ({
  studio: {
    catalog: vi.fn(() => Promise.resolve(h.CATALOG)),
    run: vi.fn((spec: any) => (h.runMode === "fail" ? Promise.reject(new Error("boom")) : Promise.resolve(h.buildResult(spec)))),
    getReport: vi.fn(() => Promise.resolve({})),
    createReport: vi.fn(() => Promise.resolve({ id: "new1", owner_id: "me", is_owner: true, created_at: "2026-06-26T00:00:00Z", updated_at: "2026-06-26T00:00:00Z" })),
    updateReport: vi.fn(() => Promise.resolve({ id: "r1", owner_id: "me", is_owner: true, created_at: "2026-06-26T00:00:00Z", updated_at: "2026-06-26T00:00:00Z" })),
    exportReportBlob: vi.fn(() => Promise.resolve(new Blob())),
  },
}));
vi.mock("@/store/auth", () => ({ useAuth: (sel: any) => sel({ user: h.user }) }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("react-router-dom", () => ({ useParams: () => h.params, useNavigate: () => vi.fn() }));

import { studio } from "@/lib/api";
import StudioReportEditorPage from "./StudioReportEditorPage";

beforeEach(() => {
  h.params = {};
  h.user = { id: "me", role: "director", full_name: "Ben" };
  h.runMode = "ok";
  vi.clearAllMocks();
});
afterEach(cleanup);

it("renders a coming_soon metric as 'Yakında' and does not select it", async () => {
  render(<StudioReportEditorPage />);
  await screen.findByText("Metrikler");

  // DSO is coming_soon → greyed with a non-selectable "Yakında" badge.
  expect(screen.getByText("DSO")).toBeInTheDocument();
  expect(screen.getByText("Yakında")).toBeInTheDocument();

  // Clicking it must not select it (it is not a button) → /studio/run never fires.
  fireEvent.click(screen.getByText("DSO"));
  await new Promise((r) => setTimeout(r, 500)); // past the 400ms debounce
  expect(studio.run).not.toHaveBeenCalled();
});

it("selecting a metric fires a debounced /studio/run and renders the table", async () => {
  render(<StudioReportEditorPage />);
  await screen.findByText("Metrikler");

  fireEvent.click(screen.getByText("Maliyet (₺)"));
  await waitFor(() => expect(studio.run).toHaveBeenCalledWith(expect.objectContaining({ metrics: ["cost_try"] })));
  // The preview table renders the formatted metric value.
  expect((await screen.findAllByText("1.000,00 ₺")).length).toBeGreaterThan(0);
});

it("visibility offers Özel/Herkes selectable with Takım disabled 'Yakında'", async () => {
  render(<StudioReportEditorPage />);
  await screen.findByText("Metrikler");
  fireEvent.click(screen.getByText("Genel"));

  expect(screen.getByText("Özel")).toBeInTheDocument();
  expect(screen.getByText("Herkes")).toBeInTheDocument();
  const takim = screen.getByText("Takım").closest("button") as HTMLButtonElement;
  expect(takim).toBeDisabled();
  expect(within(takim).getByText("Yakında")).toBeInTheDocument();

  // Herkes (company) is selectable.
  fireEvent.click(screen.getByText("Herkes"));
  expect(screen.getByText(/Şirketinizdeki herkes/)).toBeInTheDocument();
});

it("shows the 'tüm proje, bugüne kadar' tag on a windowed:false metric once a date range is set", async () => {
  render(<StudioReportEditorPage />);
  await screen.findByText("Metrikler");

  fireEvent.click(screen.getByText("Bütçe")); // windowed:false (project snapshot)
  await screen.findAllByText("1.000,00 ₺");
  // No date range yet → no windowing tag.
  expect(screen.queryByText("tüm proje, bugüne kadar")).not.toBeInTheDocument();

  // Set a date range → the snapshot tag appears on the metric column.
  fireEvent.click(screen.getByText("Tüm zamanlar"));
  fireEvent.click(screen.getByText("Son 6 ay"));
  await waitFor(() => expect(screen.getByText("tüm proje, bugüne kadar")).toBeInTheDocument());
});

it("surfaces an error + retry when /studio/run fails (never a silent empty)", async () => {
  h.runMode = "fail";
  render(<StudioReportEditorPage />);
  await screen.findByText("Metrikler");

  fireEvent.click(screen.getByText("Maliyet (₺)"));
  expect(await screen.findByText("Tekrar Dene")).toBeInTheDocument();
  expect(screen.getByText(/Önizleme yüklenemedi/)).toBeInTheDocument();

  const before = (studio.run as any).mock.calls.length;
  fireEvent.click(screen.getByText("Tekrar Dene"));
  await waitFor(() => expect((studio.run as any).mock.calls.length).toBeGreaterThan(before));
});

it("Save calls POST /studio/reports for a new report", async () => {
  render(<StudioReportEditorPage />);
  await screen.findByText("Metrikler");

  fireEvent.click(screen.getByText("Maliyet (₺)")); // a metric is required to save
  await screen.findAllByText("1.000,00 ₺");
  fireEvent.click(screen.getByText("Kaydet"));

  await waitFor(() =>
    expect(studio.createReport).toHaveBeenCalledWith(expect.objectContaining({ spec: expect.objectContaining({ metrics: ["cost_try"] }) }))
  );
});
