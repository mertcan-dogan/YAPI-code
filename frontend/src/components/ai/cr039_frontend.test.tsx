// CR-039 — conversational authoring: the ProposedActionCard renders the two
// authoring DRAFT kinds (draft_report / draft_dashboard) with Oluştur / Düzenle /
// İptal (NO director gate — any user creates their OWN artifact). Oluştur calls the
// existing create endpoint as the user and STAYS in chat with an "Aç" button.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  createReport: vi.fn(() => Promise.resolve({ id: "rep-new" })),
  createDashboard: vi.fn(() => Promise.resolve({ id: "dash-new" })),
  createSkill: vi.fn(() => Promise.resolve({ id: "skill-new" })),
  run: vi.fn(() => Promise.resolve({ meta: {}, totals: { metrics: {} }, columns: [], rows: [] })),
  catalog: vi.fn(() => Promise.resolve({ metrics: [], dimensions: [] })),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  navigate: vi.fn(),
  role: { current: "project_manager" as string },
}));

vi.mock("@/lib/api", () => ({
  apiPut: vi.fn(() => Promise.resolve({})),
  studio: { createReport: h.createReport, createDashboard: h.createDashboard, run: h.run, catalog: h.catalog },
  skills: { createSkill: h.createSkill },
}));
vi.mock("@/store/toast", () => ({ toast: { success: h.toastSuccess, error: h.toastError, info: vi.fn(), warning: vi.fn() } }));
vi.mock("@/store/auth", () => ({ useAuth: () => ({ user: { role: h.role.current } }) }));
// Keep the live-preview lightweight (no recharts) — its wiring is asserted via studio.run.
vi.mock("@/components/StudioChart", () => ({ StudioChart: () => null, formatMetricValue: (_t: any, v: any) => String(v) }));
vi.mock("@/components/DataTable", () => ({ DataTable: () => createElement("div", { "data-testid": "preview" }) }));
vi.mock("@/components/KPICard", () => ({ KPICard: () => createElement("div", { "data-testid": "preview" }) }));
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<any>();
  return { ...actual, useNavigate: () => h.navigate };
});

import { ProposedActionCard } from "@/components/ai/ProposedActionCard";

const REPORT_SPEC = { metrics: ["cost_try"], dimensions: ["project"], viz: "table" };
const DRAFT_REPORT: any = {
  kind: "draft_report", kind_label: "Rapor Taslağı", title: "Kârlılık",
  spec: REPORT_SPEC, visibility: "private", labels: null,
};
const DRAFT_DASH: any = {
  kind: "draft_dashboard", kind_label: "Pano Taslağı", title: "Pano",
  widgets: [{ id: "w1", type: "kpi", title: "Maliyet", layout: { x: 0, y: 0, w: 3, h: 2 },
              spec: { metrics: ["cost_try"], viz: "kpi" } }],
  date_range: null, comparison: null, filters: null, visibility: "private", labels: null,
};

// CR-044 — a draft_skill carries the compiled dashboard-shaped plan + format +
// instruction. Its preview/summary reuse the dashboard path (plan.widgets[0].spec).
const SKILL_PLAN: any = {
  format: "xlsx",
  title: "Aylık Özet",
  widgets: [
    { id: "w1", type: "kpi", title: "Maliyet", layout: { x: 0, y: 0, w: 3, h: 2 }, spec: { metrics: ["cost_try"], viz: "kpi" } },
  ],
  date_range: null,
};
const DRAFT_SKILL: any = {
  kind: "draft_skill", kind_label: "Beceri Taslağı", title: "Aylık DGN Martı Özeti",
  instruction: "Her ay DGN Martı gelir-gider özeti; Excel.", plan: SKILL_PLAN, format: "xlsx",
  visibility: "private", labels: null,
};

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  h.role.current = "project_manager";
});
afterEach(() => vi.clearAllMocks());

describe("ProposedActionCard draft (CR-039)", () => {
  it("a draft_report shows Oluştur/Düzenle/İptal for a NON-director (no approval gate)", async () => {
    wrap(<ProposedActionCard action={DRAFT_REPORT} />);
    expect(screen.getByText("Oluştur")).toBeInTheDocument();
    expect(screen.getByText("Düzenle")).toBeInTheDocument();
    expect(screen.getByText("İptal")).toBeInTheDocument();
    // Authoring is self-serve — no director-gated approval path.
    expect(screen.queryByText("Onayla")).not.toBeInTheDocument();
    expect(screen.queryByText("Onaylar sayfası")).not.toBeInTheDocument();
    // The live preview is wired (POST /studio/run).
    await waitFor(() => expect(h.run).toHaveBeenCalled());
  });

  it("Oluştur creates the report AS THE USER, stays in chat, then Aç navigates", async () => {
    const onResolve = vi.fn();
    wrap(<ProposedActionCard action={DRAFT_REPORT} onResolve={onResolve} />);
    fireEvent.click(screen.getByText("Oluştur"));

    await waitFor(() =>
      expect(h.createReport).toHaveBeenCalledWith({
        title: "Kârlılık", spec: REPORT_SPEC, visibility: "private", labels: null,
      })
    );
    expect(h.toastSuccess).toHaveBeenCalledWith("Rapor oluşturuldu.");
    expect(onResolve).toHaveBeenCalled();
    // Stays in chat: success + "Aç", NOT an auto-navigation.
    expect(await screen.findByText("Aç")).toBeInTheDocument();
    expect(h.navigate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Aç"));
    expect(h.navigate).toHaveBeenCalledWith("/studio/reports/rep-new");
  });

  it("a draft_dashboard creates via createDashboard and opens the pano", async () => {
    wrap(<ProposedActionCard action={DRAFT_DASH} />);
    fireEvent.click(screen.getByText("Oluştur"));
    await waitFor(() => expect(h.createDashboard).toHaveBeenCalled());
    const dashBody = (h.createDashboard.mock.calls as any[])[0][0];
    expect(dashBody.widgets[0].id).toBe("w1");
    fireEvent.click(await screen.findByText("Aç"));
    expect(h.navigate).toHaveBeenCalledWith("/studio/dashboards/dash-new");
  });

  it("the Herkes toggle sets visibility=company on create (Özel is the default)", async () => {
    wrap(<ProposedActionCard action={DRAFT_REPORT} />);
    fireEvent.click(screen.getByText("Herkes"));
    fireEvent.click(screen.getByText("Oluştur"));
    await waitFor(() =>
      expect(h.createReport).toHaveBeenCalledWith(expect.objectContaining({ visibility: "company" }))
    );
  });

  it("İptal dismisses the draft (no write) and notifies the page", () => {
    const onResolve = vi.fn();
    wrap(<ProposedActionCard action={DRAFT_REPORT} onResolve={onResolve} />);
    fireEvent.click(screen.getByText("İptal"));
    expect(onResolve).toHaveBeenCalled();
    expect(screen.getByText("İptal edildi.")).toBeInTheDocument();
    expect(h.createReport).not.toHaveBeenCalled();
  });

  it("a non-authoring kind still renders the director-gated approval card", () => {
    h.role.current = "director";
    wrap(
      <ProposedActionCard
        action={{ request_id: "r1", kind: "agent_task", kind_label: "Görev (AI önerisi)",
                  description: "Teklif hazırla", status: "pending", deep_link: "/approvals" } as any}
      />
    );
    expect(screen.getByText("Onayla")).toBeInTheDocument();
    expect(screen.queryByText("Oluştur")).not.toBeInTheDocument();
  });
});

// CR-044 — the draft_skill authoring card: a plan summary (format + sections) + a
// live preview of the plan's first widget + "Beceri olarak kaydet" (→ createSkill,
// no director gate) / İptal + the refine hint. CR-044.1 — NO Düzenle (a skill has
// no editor page; it's refined by chatting).
describe("ProposedActionCard draft_skill (CR-044)", () => {
  it("shows 'Beceri olarak kaydet'/İptal (NO Düzenle) for a NON-director (no approval gate) + a format chip", async () => {
    wrap(<ProposedActionCard action={DRAFT_SKILL} />);
    expect(screen.getByText("Beceri olarak kaydet")).toBeInTheDocument();
    // CR-044.1 — the dead Düzenle button is gone for skill drafts.
    expect(screen.queryByText("Düzenle")).not.toBeInTheDocument();
    expect(screen.getByText("İptal")).toBeInTheDocument();
    // The output-format chip is shown (skill plan summary).
    expect(screen.getByText("Excel (.xlsx)")).toBeInTheDocument();
    // No director-gated approval path for authoring.
    expect(screen.queryByText("Onayla")).not.toBeInTheDocument();
    // The live preview of plan.widgets[0].spec is wired (POST /studio/run).
    await waitFor(() => expect(h.run).toHaveBeenCalled());
    // The refine hint is present.
    expect(screen.getByText(/Değiştirmek için yazmaya devam edin/)).toBeInTheDocument();
  });

  it("'Beceri olarak kaydet' creates the skill AS THE USER and stays in chat with a link to Uygulamalar", async () => {
    const onResolve = vi.fn();
    wrap(<ProposedActionCard action={DRAFT_SKILL} onResolve={onResolve} />);
    fireEvent.click(screen.getByText("Beceri olarak kaydet"));

    await waitFor(() =>
      expect(h.createSkill).toHaveBeenCalledWith({
        name: "Aylık DGN Martı Özeti",
        instruction: "Her ay DGN Martı gelir-gider özeti; Excel.",
        plan: SKILL_PLAN,
        format: "xlsx",
        visibility: "private",
        labels: null,
      })
    );
    expect(h.toastSuccess).toHaveBeenCalledWith("Beceri kaydedildi.");
    expect(onResolve).toHaveBeenCalled();
    // Stays in chat: success + an "Uygulamalar" link, no auto-navigation.
    expect(await screen.findByText("Uygulamalar")).toBeInTheDocument();
    expect(h.navigate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Uygulamalar"));
    expect(h.navigate).toHaveBeenCalledWith("/studio/skills");
  });

  it("the Herkes toggle sets visibility=company when saving the skill (Özel is the default)", async () => {
    wrap(<ProposedActionCard action={DRAFT_SKILL} />);
    fireEvent.click(screen.getByText("Herkes"));
    fireEvent.click(screen.getByText("Beceri olarak kaydet"));
    await waitFor(() =>
      expect(h.createSkill).toHaveBeenCalledWith(expect.objectContaining({ visibility: "company" }))
    );
  });

  it("İptal dismisses the skill draft (no write) and notifies the page", () => {
    const onResolve = vi.fn();
    wrap(<ProposedActionCard action={DRAFT_SKILL} onResolve={onResolve} />);
    fireEvent.click(screen.getByText("İptal"));
    expect(onResolve).toHaveBeenCalled();
    expect(screen.getByText("İptal edildi.")).toBeInTheDocument();
    expect(h.createSkill).not.toHaveBeenCalled();
  });
});
