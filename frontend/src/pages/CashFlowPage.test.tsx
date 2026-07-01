// CR-054 — the Nakit Akışı "Dışa Aktar" now downloads the backend decision-grade
// workbook (GET /reports/cashflow/{id}?fmt=xlsx: Özet KPIs + ₺ table + cumulative
// line), not the client-side raw "Veri" dump. The raw client CSV stays as a
// secondary "Ham veri (CSV)" option; the Excel (.xlsx) client dump is gone.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

type Row = {
  month: string; planned_out_try: string; actual_out_try: string;
  planned_in_try: string; actual_in_try: string; net_try: string;
  cumulative_try: string; is_past: boolean; is_current: boolean;
};

const ROWS: Row[] = [
  { month: "2026-01", planned_out_try: "100", actual_out_try: "90", planned_in_try: "200", actual_in_try: "210", net_try: "120", cumulative_try: "120", is_past: true, is_current: false },
  { month: "2026-02", planned_out_try: "110", actual_out_try: "0", planned_in_try: "150", actual_in_try: "0", net_try: "40", cumulative_try: "160", is_past: false, is_current: true },
];

const h = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: new Blob(["x"], { type: "application/vnd.openxmlformats" }) })),
  fetchImpl: (_url: string) => ({ data: null as any, meta: null as any, loading: false, error: null as string | null, refetch: () => {} }),
}));

vi.mock("@/hooks/useFetch", () => ({ useFetch: (url: string) => h.fetchImpl(url) }));
vi.mock("@/lib/api", () => ({ api: { get: h.get } }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/layout/AppLayout", () => ({
  PageHeader: ({ title, action }: { title: string; action?: any }) => createElement("div", null, createElement("h1", null, title), action),
}));
vi.mock("@/components/charts", () => ({ CashFlowChart: () => createElement("div", { "data-testid": "chart" }) }));
vi.mock("@/components/cashflow/CashFlowMonthDrawer", () => ({ CashFlowMonthDrawer: () => null }));
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useParams: () => ({ id: "p1" }),
}));

import { api } from "@/lib/api";
import { toast } from "@/store/toast";
import CashFlowPage from "./CashFlowPage";

beforeEach(() => {
  // Default: cashflow rows load fine; the /risk fetch returns an empty list.
  h.fetchImpl = (url: string) =>
    url.includes("/risk")
      ? { data: [], meta: null, loading: false, error: null, refetch: () => {} }
      : { data: ROWS, meta: { from_month: null, to_month: null }, loading: false, error: null, refetch: () => {} };
  h.get.mockClear();
  h.get.mockResolvedValue({ data: new Blob(["x"], { type: "application/vnd.openxmlformats" }) });
  (toast.success as any).mockClear?.();
  (toast.error as any).mockClear?.();
  (URL as any).createObjectURL = vi.fn(() => "blob:mock");
  (URL as any).revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const primaryExport = () => screen.getByRole("button", { name: /Dışa Aktar/ });
const rawCsvTrigger = () => screen.getByRole("button", { name: /Ham veri \(CSV\)/ });

describe("CashFlowPage CR-054 decision-grade export", () => {
  it("primary 'Dışa Aktar' hits GET /reports/cashflow/{id}?fmt=xlsx (blob)", async () => {
    render(createElement(CashFlowPage));
    fireEvent.click(primaryExport());
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/reports/cashflow/p1", { responseType: "blob", params: { fmt: "xlsx" } })
    );
  });

  it("downloads the blob via an anchor and toasts success", async () => {
    render(createElement(CashFlowPage));
    fireEvent.click(primaryExport());
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Rapor indirildi"));
    expect((URL as any).createObjectURL).toHaveBeenCalled();
    expect((URL as any).revokeObjectURL).toHaveBeenCalled();
  });

  it("shows a Turkish error toast when the export rejects", async () => {
    h.get.mockRejectedValueOnce(new Error("Rapor oluşturulamadı"));
    render(createElement(CashFlowPage));
    fireEvent.click(primaryExport());
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Rapor oluşturulamadı"));
  });

  it("keeps a secondary 'Ham veri (CSV)' option that exports client-side CSV — no backend, no Excel dump", async () => {
    render(createElement(CashFlowPage));
    // Open the secondary menu.
    fireEvent.click(rawCsvTrigger());
    // csvOnly: the client Excel (.xlsx) dump is gone; only CSV remains.
    expect(screen.queryByRole("button", { name: /Excel \(\.xlsx\)/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^CSV$/ }));
    await waitFor(() => expect((URL as any).createObjectURL).toHaveBeenCalled());
    // The raw CSV is purely client-side — it must NOT call the backend report endpoint.
    expect(api.get).not.toHaveBeenCalled();
  });
});
