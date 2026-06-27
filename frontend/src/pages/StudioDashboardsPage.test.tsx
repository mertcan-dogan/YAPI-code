// CR-034 — Panolar (dashboards) list. Mirrors StudioReportsPage.test: tabs
// Panolarım / Tüm panolar, debounced server-side search, the row "…" menu
// (Çoğalt / Bağlantıyı kopyala / Sil — Sil gated to owner or director), the
// delete confirm, and the empty + error+retry states. api/auth/toast/router are
// mocked; DataTable + Menu render for real.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  user: { id: "me", role: "project_manager", full_name: "Ben" } as { id: string; role: string; full_name: string },
  dashboards: [
    { id: "d1", title: "Benim Panom", owner_id: "me", visibility: "private", updated_at: "2026-06-20T10:00:00Z", labels: null, widget_count: 3 },
    { id: "d2", title: "Başkasının Panosu", owner_id: "other", visibility: "company", updated_at: "2026-06-19T10:00:00Z", labels: null, widget_count: 5 },
  ] as any[],
  listMode: "ok" as "ok" | "fail",
}));

vi.mock("@/lib/api", () => ({
  studio: {
    listDashboards: vi.fn(() => (h.listMode === "fail" ? Promise.reject(new Error("boom")) : Promise.resolve(h.dashboards))),
    duplicateDashboard: vi.fn(() => Promise.resolve({ id: "dup" })),
    deleteDashboard: vi.fn(() => Promise.resolve({ deleted: true })),
  },
}));
vi.mock("@/store/auth", () => ({ useAuth: (sel: any) => sel({ user: h.user }) }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/layout/AppLayout", () => ({
  PageHeader: ({ title, action }: { title: string; action?: any }) => createElement("div", null, createElement("h1", null, title), action),
}));
const navigate = vi.fn();
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));

import { studio } from "@/lib/api";
import { toast } from "@/store/toast";
import StudioDashboardsPage from "./StudioDashboardsPage";

beforeEach(() => {
  h.user = { id: "me", role: "project_manager", full_name: "Ben" };
  h.listMode = "ok";
  navigate.mockClear();
  vi.clearAllMocks();
});
afterEach(cleanup);

it("Panolarım shows only my panos; Tüm panolar reveals the company one", async () => {
  render(<StudioDashboardsPage />);
  // Default "Panolarım" → only the pano owned by me.
  await screen.findByText("Benim Panom");
  expect(screen.queryByText("Başkasının Panosu")).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("Tüm panolar"));
  expect(await screen.findByText("Başkasının Panosu")).toBeInTheDocument();
});

it("renders a Görünürlük chip per pano (Özel / Herkes) + widget count", async () => {
  render(<StudioDashboardsPage />);
  await screen.findByText("Benim Panom");
  expect(screen.getByText("Özel")).toBeInTheDocument();
  expect(screen.getByText("3 widget")).toBeInTheDocument();

  fireEvent.click(screen.getByText("Tüm panolar"));
  const row = (await screen.findByText("Başkasının Panosu")).closest("tr") as HTMLElement;
  expect(within(row).getByText("Herkes")).toBeInTheDocument();
  expect(within(row).getByText("5 widget")).toBeInTheDocument();
});

it("hides Sil from a non-owner non-director (but keeps Çoğalt + Bağlantıyı kopyala)", async () => {
  render(<StudioDashboardsPage />);
  await screen.findByText("Benim Panom");
  fireEvent.click(screen.getByText("Tüm panolar"));
  await screen.findByText("Başkasının Panosu");

  fireEvent.click(screen.getByLabelText("Pano işlemleri: Başkasının Panosu"));
  expect(screen.getByText("Çoğalt")).toBeInTheDocument();
  expect(screen.getByText("Bağlantıyı kopyala")).toBeInTheDocument();
  expect(screen.queryByText("Sil")).not.toBeInTheDocument();
});

it("shows Sil to the owner of a pano", async () => {
  render(<StudioDashboardsPage />);
  await screen.findByText("Benim Panom");
  fireEvent.click(screen.getByLabelText("Pano işlemleri: Benim Panom"));
  expect(screen.getByText("Sil")).toBeInTheDocument();
});

it("shows Sil to a director even on another user's pano", async () => {
  h.user = { id: "me", role: "director", full_name: "Patron" };
  render(<StudioDashboardsPage />);
  await screen.findByText("Benim Panom");
  fireEvent.click(screen.getByText("Tüm panolar"));
  await screen.findByText("Başkasının Panosu");

  fireEvent.click(screen.getByLabelText("Pano işlemleri: Başkasının Panosu"));
  expect(screen.getByText("Sil")).toBeInTheDocument();
});

it("Çoğalt duplicates and navigates to the new pano", async () => {
  render(<StudioDashboardsPage />);
  await screen.findByText("Benim Panom");
  fireEvent.click(screen.getByLabelText("Pano işlemleri: Benim Panom"));
  fireEvent.click(screen.getByText("Çoğalt"));

  await waitFor(() => expect(studio.duplicateDashboard).toHaveBeenCalledWith("d1"));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/studio/dashboards/dup"));
});

it("Sil deletes only after a confirm", async () => {
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<StudioDashboardsPage />);
  await screen.findByText("Benim Panom");

  // Cancelled confirm → no delete call.
  fireEvent.click(screen.getByLabelText("Pano işlemleri: Benim Panom"));
  fireEvent.click(screen.getByText("Sil"));
  expect(confirmSpy).toHaveBeenCalled();
  expect(studio.deleteDashboard).not.toHaveBeenCalled();

  // Accepted confirm → delete fires.
  confirmSpy.mockReturnValue(true);
  fireEvent.click(screen.getByLabelText("Pano işlemleri: Benim Panom"));
  fireEvent.click(screen.getByText("Sil"));
  await waitFor(() => expect(studio.deleteDashboard).toHaveBeenCalledWith("d1"));
  confirmSpy.mockRestore();
});

it("Bağlantıyı kopyala copies the deep link", async () => {
  const writeText = vi.fn(() => Promise.resolve());
  Object.assign(navigator, { clipboard: { writeText } });
  render(<StudioDashboardsPage />);
  await screen.findByText("Benim Panom");

  fireEvent.click(screen.getByLabelText("Pano işlemleri: Benim Panom"));
  fireEvent.click(screen.getByText("Bağlantıyı kopyala"));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("/studio/dashboards/d1")));
  await waitFor(() => expect(toast.success).toHaveBeenCalled());
});

it("debounced search hits the server-side ?q= filter", async () => {
  render(<StudioDashboardsPage />);
  await screen.findByText("Benim Panom");
  expect(studio.listDashboards).toHaveBeenCalledWith(undefined); // initial load

  fireEvent.change(screen.getByLabelText("Pano ara"), { target: { value: "rapor" } });
  await waitFor(() => expect(studio.listDashboards).toHaveBeenCalledWith("rapor"));
});

it("shows the empty state when there are no panos", async () => {
  h.dashboards = [];
  render(<StudioDashboardsPage />);
  expect(await screen.findByText("Henüz pano oluşturmadınız.")).toBeInTheDocument();
  // restore for later tests
  h.dashboards = [
    { id: "d1", title: "Benim Panom", owner_id: "me", visibility: "private", updated_at: "2026-06-20T10:00:00Z", labels: null, widget_count: 3 },
    { id: "d2", title: "Başkasının Panosu", owner_id: "other", visibility: "company", updated_at: "2026-06-19T10:00:00Z", labels: null, widget_count: 5 },
  ];
});

it("shows an error + retry (never reads as empty) and recovers on retry", async () => {
  h.listMode = "fail";
  render(<StudioDashboardsPage />);
  const retry = await screen.findByText("Tekrar Dene");
  expect(retry).toBeInTheDocument();

  h.listMode = "ok";
  fireEvent.click(retry);
  expect(await screen.findByText("Benim Panom")).toBeInTheDocument();
});
