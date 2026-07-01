// CR-035 — ProposedActionCard rich preview for the two Rapor Stüdyosu authoring
// kinds (agent_create_report / agent_create_dashboard). Asserts: a LIVE PREVIEW is
// rendered from POST /studio/run; Onayla approves then navigates using the
// `created` table+id the approve endpoint returns; Düzenle opens the editor /new
// route with an UNSAVED draft (creating nothing); Reddet posts the reject reason.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const CATALOG = {
    dimensions: [
      { id: "unit_type", label: "Daire tipi", type: "enum", group: "Satış", description: "Daire tipi.", status: "available" },
    ],
    metrics: [
      { id: "cost_try", label: "Maliyet (₺)", type: "currency", group: "Maliyet", description: "Maliyet.", status: "available", windowed: true },
      { id: "revenue", label: "Gelir", type: "currency", group: "Gelir", description: "Gelir.", status: "available", windowed: false },
    ],
  };
  const buildResult = (spec: any) => ({
    columns: (spec.metrics ?? []).map((m: string) => ({ id: m, label: m === "cost_try" ? "Maliyet (₺)" : "Gelir", kind: "metric", type: "currency" })),
    rows: [{ dims: {}, metrics: Object.fromEntries((spec.metrics ?? []).map((m: string) => [m, 1000])), deltas: null }],
    totals: { metrics: Object.fromEntries((spec.metrics ?? []).map((m: string) => [m, 1000])), deltas: null },
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
  return {
    apiPut: vi.fn(() => Promise.resolve({})) as any,
    run: vi.fn((spec: any) => Promise.resolve(buildResult(spec))),
    catalog: vi.fn(() => Promise.resolve(CATALOG)),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
    navigate: vi.fn(),
    user: { role: "director" } as { role: string } | null,
    CATALOG,
  };
});

vi.mock("@/lib/api", () => ({
  apiPut: h.apiPut,
  studio: { run: h.run, catalog: h.catalog },
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

const REPORT_ACTION = {
  request_id: "rr1",
  kind: "agent_create_report",
  kind_label: "Rapor (AI önerisi)",
  description: "Daire tipine göre kâr/zarar raporu",
  status: "pending",
  deep_link: "/approvals",
  title: "Kâr/Zarar Raporu",
  spec: { metrics: ["cost_try"], dimensions: ["unit_type"], viz: "kpi" },
};

const DASHBOARD_ACTION = {
  request_id: "dd1",
  kind: "agent_create_dashboard",
  kind_label: "Pano (AI önerisi)",
  description: "Genel bakış panosu",
  status: "pending",
  deep_link: "/approvals",
  title: "Genel Bakış",
  date_range: { preset: "last_6_months" },
  widgets: [
    { id: "w1", type: "kpi", title: "Maliyet", layout: { x: 0, y: 0, w: 3, h: 2 }, spec: { metrics: ["cost_try"], dimensions: [], viz: "kpi" } },
    { id: "w2", type: "text", title: "Not", layout: { x: 3, y: 0, w: 4, h: 2 }, content: "Merhaba" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  h.apiPut.mockResolvedValue({});
  h.user = { role: "director" };
});
afterEach(() => vi.clearAllMocks());

describe("ProposedActionCard — report authoring (CR-035)", () => {
  it("renders the spec summary + a live /studio/run preview", async () => {
    wrap(<ProposedActionCard action={REPORT_ACTION} />);

    // Trust copy + proposed title.
    expect(screen.getByText(/Yapı AI şunu öneriyor/)).toBeInTheDocument();
    expect(screen.getByText("Kâr/Zarar Raporu")).toBeInTheDocument();

    // The live preview ran the proposed spec…
    await waitFor(() =>
      expect(h.run).toHaveBeenCalledWith(expect.objectContaining({ metrics: ["cost_try"], viz: "kpi" }))
    );
    // …and rendered it via the studio kit (KPICard label from the catalog).
    expect((await screen.findAllByText("Maliyet (₺)")).length).toBeGreaterThan(0);
  });

  it("Onayla approves then navigates using the returned `created` (reports)", async () => {
    h.apiPut.mockResolvedValue({ id: "appr1", created: { table: "reports", id: "rep-new" } });
    wrap(<ProposedActionCard action={REPORT_ACTION} />);

    fireEvent.click(screen.getByText("Onayla"));
    await waitFor(() => expect(h.apiPut).toHaveBeenCalledWith("/approvals/request/rr1/approve", {}));
    await waitFor(() => expect(h.navigate).toHaveBeenCalledWith("/studio/reports/rep-new"));
    expect(h.toastSuccess).toHaveBeenCalledWith("Rapor oluşturuldu.");
  });

  it("Düzenle opens the editor /new with the draft spec and creates nothing", () => {
    wrap(<ProposedActionCard action={REPORT_ACTION} />);

    fireEvent.click(screen.getByText("Düzenle"));
    expect(h.navigate).toHaveBeenCalledWith("/studio/reports/new", {
      state: { draftSpec: REPORT_ACTION.spec, draftTitle: "Kâr/Zarar Raporu" },
    });
    // Düzenle never touches the approval endpoint (nothing is created).
    expect(h.apiPut).not.toHaveBeenCalled();
  });

  it("Reddet posts the reject reason to the approvals endpoint", async () => {
    wrap(<ProposedActionCard action={REPORT_ACTION} />);

    // Open the reason form (first Reddet), type a reason, submit (second Reddet).
    fireEvent.click(screen.getByText("Reddet"));
    fireEvent.change(screen.getByPlaceholderText("Red nedeni"), { target: { value: "Uygun değil" } });
    fireEvent.click(screen.getByText("Reddet"));

    await waitFor(() =>
      expect(h.apiPut).toHaveBeenCalledWith("/approvals/request/rr1/reject", { reason: "Uygun değil" })
    );
    expect(await screen.findByText(/Reddedildi/)).toBeInTheDocument();
  });

  it("non-directors see the approvals link, not Onayla/Düzenle", () => {
    h.user = { role: "project_manager" };
    wrap(<ProposedActionCard action={REPORT_ACTION} />);
    expect(screen.queryByText("Onayla")).not.toBeInTheDocument();
    expect(screen.queryByText("Düzenle")).not.toBeInTheDocument();
    expect(screen.getByText("Onaylar sayfası")).toBeInTheDocument();
  });
});

describe("ProposedActionCard — dashboard authoring (CR-035)", () => {
  it("previews the first data widget and Onayla navigates to the created pano", async () => {
    h.apiPut.mockResolvedValue({ id: "appr2", created: { table: "dashboards", id: "dash-new" } });
    wrap(<ProposedActionCard action={DASHBOARD_ACTION} />);

    // Widget-count chip + first data-widget preview.
    expect(screen.getByText("Genel Bakış")).toBeInTheDocument();
    await waitFor(() => expect(h.run).toHaveBeenCalledWith(expect.objectContaining({ metrics: ["cost_try"] })));

    fireEvent.click(screen.getByText("Onayla"));
    await waitFor(() => expect(h.apiPut).toHaveBeenCalledWith("/approvals/request/dd1/approve", {}));
    await waitFor(() => expect(h.navigate).toHaveBeenCalledWith("/studio/dashboards/dash-new"));
    expect(h.toastSuccess).toHaveBeenCalledWith("Pano oluşturuldu.");
  });

  it("Düzenle opens the pano canvas /new with the draft widgets, creating nothing", () => {
    wrap(<ProposedActionCard action={DASHBOARD_ACTION} />);

    fireEvent.click(screen.getByText("Düzenle"));
    expect(h.navigate).toHaveBeenCalledWith("/studio/dashboards/new", {
      state: {
        draftWidgets: DASHBOARD_ACTION.widgets,
        draftTitle: "Genel Bakış",
        draftDateRange: DASHBOARD_ACTION.date_range,
      },
    });
    expect(h.apiPut).not.toHaveBeenCalled();
  });
});
