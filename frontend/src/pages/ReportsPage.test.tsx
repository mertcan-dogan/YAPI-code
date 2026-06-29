// CR-048 — the four placeholder Raporlar cards (Maliyet Detay, Hakediş, Alt
// Yüklenici, Nakit Akış) now download real backend reports as blobs; cost/cashflow
// offer a PDF/Excel choice (?fmt=xlsx). The "yakında" stub is gone.
//
// Also retains the silent-load-failure guard: a failed /projects load must surface
// a clear Turkish error + retry where the project dropdown would be — never an empty
// dropdown that reads as "no projects". useFetch is mocked so we can drive states.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  projects: { data: null as any, meta: null as any, loading: false, error: null as string | null, refetch: () => {} },
  get: vi.fn(() => Promise.resolve({ data: new Blob(["x"], { type: "application/pdf" }) })),
}));

vi.mock("@/hooks/useFetch", () => ({ useFetch: () => h.projects }));
vi.mock("@/lib/api", () => ({ api: { get: h.get } }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/layout/AppLayout", () => ({ PageHeader: ({ title }: { title: string }) => createElement("h1", null, title) }));

import { api } from "@/lib/api";
import { toast } from "@/store/toast";
import ReportsPage from "./ReportsPage";

// jsdom lacks these blob/anchor APIs that the download helper calls.
beforeEach(() => {
  h.projects = { data: [{ id: "p1", name: "Test Projesi" }] as any, meta: null, loading: false, error: null, refetch: () => {} };
  h.get.mockClear();
  h.get.mockResolvedValue({ data: new Blob(["x"], { type: "application/pdf" }) });
  (toast.success as any).mockClear?.();
  (toast.error as any).mockClear?.();
  (toast.info as any).mockClear?.();
  (URL as any).createObjectURL = vi.fn(() => "blob:mock");
  (URL as any).revokeObjectURL = vi.fn();
  // Don't let the synthetic anchor click trigger a real navigation in jsdom.
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const selectProject = () => fireEvent.change(screen.getByRole("combobox"), { target: { value: "p1" } });

// "PDF"/"Excel"/"İndir" each appear in both a format badge (a <span>) and the
// action <button>; target the buttons by role so we never click a non-interactive
// badge. Order follows card order: cost then cashflow for the PDF/Excel pairs;
// Proje Durum, Hakediş, Alt Yüklenici for the single İndir buttons.
const buttons = (name: RegExp) => screen.getAllByRole("button", { name });
const pdfButtons = () => buttons(/^PDF$/);
const excelButtons = () => buttons(/^Excel$/);
const indirButtons = () => buttons(/^İndir$/);

describe("ReportsPage project dropdown load states", () => {
  it("renders the project dropdown when the projects load succeeds", () => {
    render(createElement(ReportsPage));
    expect(screen.getByText("Proje seçin...")).toBeInTheDocument();
    expect(screen.getByText("Test Projesi")).toBeInTheDocument();
  });

  it("shows a retryable Turkish error (not an empty dropdown) when the projects load fails", () => {
    const refetch = vi.fn();
    h.projects = { data: null, meta: null, loading: false, error: "500", refetch };
    render(createElement(ReportsPage));
    expect(screen.queryByText("Proje seçin...")).not.toBeInTheDocument();
    expect(screen.getByText("Projeler yüklenemedi.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Tekrar Dene"));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows a disabled loading placeholder (not the error state) while the projects are loading", () => {
    h.projects = { data: null, meta: null, loading: true, error: null, refetch: () => {} };
    render(createElement(ReportsPage));
    expect(screen.getByText("Projeler yükleniyor…")).toBeInTheDocument();
    expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(true);
    expect(screen.queryByText("Projeler yüklenemedi.")).not.toBeInTheDocument();
  });

  it("prefers the loading placeholder over the error state when a load is in flight (error gated on !loading)", () => {
    h.projects = { data: null, meta: null, loading: true, error: "500", refetch: () => {} };
    render(createElement(ReportsPage));
    expect(screen.getByText("Projeler yükleniyor…")).toBeInTheDocument();
    expect(screen.queryByText("Projeler yüklenemedi.")).not.toBeInTheDocument();
  });
});

describe("ReportsPage CR-048 report downloads", () => {
  it("no longer shows a 'yakında' stub for the four newly-wired cards", () => {
    render(createElement(ReportsPage));
    selectProject();
    // Trigger the formerly-stubbed cards: Hakediş + Alt Yüklenici (PDF-only) and the
    // cost/cashflow PDF/Excel buttons. None may toast the old "yakında" message.
    fireEvent.click(indirButtons()[1]); // Hakediş
    expect(toast.info).not.toHaveBeenCalledWith("Bu rapor türü yakında eklenecek");
    expect(screen.queryByText("Bu rapor türü yakında eklenecek")).not.toBeInTheDocument();
  });

  it("requires a selected project — toasts a Turkish message and does not call the API", () => {
    render(createElement(ReportsPage));
    // No project selected: clicking a card's button must toast and not hit the API.
    fireEvent.click(indirButtons()[0]);
    expect(toast.error).toHaveBeenCalledWith("Lütfen bir proje seçin");
    expect(api.get).not.toHaveBeenCalled();
  });

  // The three PDF-only single "İndir" buttons render in card order:
  //   [0] Proje Durum, [1] Hakediş, [2] Alt Yüklenici.
  it("the Proje Durum (PDF-only) card still hits /reports/project/{id} (unchanged)", async () => {
    render(createElement(ReportsPage));
    selectProject();
    fireEvent.click(indirButtons()[0]); // Proje Durum
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/reports/project/p1", { responseType: "blob", params: undefined })
    );
  });

  it("the Hakediş (PDF-only) card hits /reports/invoice/{id} with no fmt param", async () => {
    render(createElement(ReportsPage));
    selectProject();
    fireEvent.click(indirButtons()[1]); // Hakediş
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/reports/invoice/p1", { responseType: "blob", params: undefined })
    );
  });

  it("the Alt Yüklenici (PDF-only) card hits /reports/subcontractor/{id} with no fmt param", async () => {
    render(createElement(ReportsPage));
    selectProject();
    fireEvent.click(indirButtons()[2]); // Alt Yüklenici
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/reports/subcontractor/p1", { responseType: "blob", params: undefined })
    );
  });

  it("the Maliyet Detay card downloads PDF (no fmt) and Excel (?fmt=xlsx)", async () => {
    render(createElement(ReportsPage));
    selectProject();
    // The first PDF/Excel pair belongs to Maliyet Detay (cost).
    fireEvent.click(pdfButtons()[0]);
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/reports/cost/p1", { responseType: "blob", params: undefined })
    );
    fireEvent.click(excelButtons()[0]);
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/reports/cost/p1", { responseType: "blob", params: { fmt: "xlsx" } })
    );
  });

  it("the Nakit Akış card downloads PDF (no fmt) and Excel (?fmt=xlsx)", async () => {
    render(createElement(ReportsPage));
    selectProject();
    // The second PDF/Excel pair belongs to Nakit Akış (cashflow).
    fireEvent.click(pdfButtons()[1]);
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/reports/cashflow/p1", { responseType: "blob", params: undefined })
    );
    fireEvent.click(excelButtons()[1]);
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/reports/cashflow/p1", { responseType: "blob", params: { fmt: "xlsx" } })
    );
  });

  it("downloads a blob via an anchor and toasts success", async () => {
    render(createElement(ReportsPage));
    selectProject();
    fireEvent.click(indirButtons()[0]);
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Rapor indirildi"));
    expect((URL as any).createObjectURL).toHaveBeenCalled();
    expect((URL as any).revokeObjectURL).toHaveBeenCalled();
  });

  it("shows a Turkish error toast when a download rejects", async () => {
    h.get.mockRejectedValueOnce(new Error("Rapor oluşturulamadı"));
    render(createElement(ReportsPage));
    selectProject();
    fireEvent.click(pdfButtons()[0]); // Maliyet Detay PDF
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Rapor oluşturulamadı"));
  });
});
