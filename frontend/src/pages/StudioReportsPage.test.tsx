// CR-033 — Rapor Stüdyosu list. The row "…" menu must expose Sil/Düzenle ONLY to
// the report owner or a director (Çoğalt is always available for any viewable
// report). api/auth/router are mocked; DataTable + Menu render for real.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  user: { id: "me", role: "project_manager", full_name: "Ben" } as { id: string; role: string; full_name: string },
  reports: [
    { id: "r1", title: "Benim Raporum", owner_id: "me", visibility: "private", updated_at: "2026-06-20T10:00:00Z", labels: null, viz: "table" },
    { id: "r2", title: "Başkasının Raporu", owner_id: "other", visibility: "company", updated_at: "2026-06-19T10:00:00Z", labels: null, viz: "bar" },
  ] as any[],
}));

vi.mock("@/lib/api", () => ({
  studio: {
    listReports: vi.fn(() => Promise.resolve(h.reports)),
    duplicateReport: vi.fn(() => Promise.resolve({ id: "dup" })),
    deleteReport: vi.fn(() => Promise.resolve({ deleted: true })),
  },
}));
vi.mock("@/store/auth", () => ({ useAuth: (sel: any) => sel({ user: h.user }) }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/layout/AppLayout", () => ({
  PageHeader: ({ title, action }: { title: string; action?: any }) => createElement("div", null, createElement("h1", null, title), action),
}));
const navigate = vi.fn();
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));

import StudioReportsPage from "./StudioReportsPage";

beforeEach(() => {
  h.user = { id: "me", role: "project_manager", full_name: "Ben" };
  navigate.mockClear();
});
afterEach(cleanup);

it("hides Sil/Düzenle from a non-owner non-director (but keeps Çoğalt)", async () => {
  render(<StudioReportsPage />);
  await screen.findByText("Benim Raporum");
  // Switch to "Tüm raporlar" to reveal the report owned by someone else.
  fireEvent.click(screen.getByText("Tüm raporlar"));
  await screen.findByText("Başkasının Raporu");

  fireEvent.click(screen.getByLabelText("Rapor işlemleri: Başkasının Raporu"));
  expect(screen.getByText("Çoğalt")).toBeInTheDocument();
  expect(screen.queryByText("Sil")).not.toBeInTheDocument();
  expect(screen.queryByText("Düzenle")).not.toBeInTheDocument();
});

it("shows Sil/Düzenle to the owner of a report", async () => {
  render(<StudioReportsPage />);
  await screen.findByText("Benim Raporum");

  fireEvent.click(screen.getByLabelText("Rapor işlemleri: Benim Raporum"));
  expect(screen.getByText("Düzenle")).toBeInTheDocument();
  expect(screen.getByText("Sil")).toBeInTheDocument();
});

it("shows Sil/Düzenle to a director even on another user's report", async () => {
  h.user = { id: "me", role: "director", full_name: "Patron" };
  render(<StudioReportsPage />);
  await screen.findByText("Benim Raporum");
  fireEvent.click(screen.getByText("Tüm raporlar"));
  await screen.findByText("Başkasının Raporu");

  fireEvent.click(screen.getByLabelText("Rapor işlemleri: Başkasının Raporu"));
  expect(screen.getByText("Düzenle")).toBeInTheDocument();
  expect(screen.getByText("Sil")).toBeInTheDocument();
});

it("renders a Görünürlük chip per report (Özel / Herkes)", async () => {
  render(<StudioReportsPage />);
  // "Raporlarım" → only the private report (Özel).
  await screen.findByText("Benim Raporum");
  expect(screen.getByText("Özel")).toBeInTheDocument();
  // "Tüm raporlar" → the company report shows Herkes.
  fireEvent.click(screen.getByText("Tüm raporlar"));
  const row = (await screen.findByText("Başkasının Raporu")).closest("tr") as HTMLElement;
  expect(within(row).getByText("Herkes")).toBeInTheDocument();
});

// --- CR-034.1 Fix 3: the row "…" menu renders via a portal (un-clipped) ---

it("renders the row … menu through a portal on <body> (not clipped inside the table)", async () => {
  render(<StudioReportsPage />);
  await screen.findByText("Benim Raporum");

  fireEvent.click(screen.getByLabelText("Rapor işlemleri: Benim Raporum"));
  // The items are reachable…
  expect(screen.getByText("Çoğalt")).toBeInTheDocument();
  // …and the panel is portaled to document.body, OUTSIDE the table's overflow box,
  // so it can't be clipped by the list container.
  const menu = document.body.querySelector('[role="menu"]') as HTMLElement | null;
  expect(menu).not.toBeNull();
  expect(menu!.closest("table")).toBeNull();
  expect(within(menu!).getByText("Çoğalt")).toBeInTheDocument();
});

it("keeps the portaled menu open on a mousedown inside it (two-ref outside-click)", async () => {
  render(<StudioReportsPage />);
  await screen.findByText("Benim Raporum");

  fireEvent.click(screen.getByLabelText("Rapor işlemleri: Benim Raporum"));
  const item = screen.getByText("Çoğalt");
  // A mousedown on the panel (separate portal ref from the trigger) must NOT close it.
  fireEvent.mouseDown(item);
  expect(screen.getByText("Çoğalt")).toBeInTheDocument();
});
