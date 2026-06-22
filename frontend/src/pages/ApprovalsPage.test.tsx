// CR-012-E: the agent_file_document approval card renders the proposed
// destination + confidence + a project picker, and approving sends the chosen
// project and edited fields to the approve endpoint.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  approvals: {
    data: [
      {
        kind: "agent_file_document",
        kind_label: "Belge Dosyalama (AI önerisi)",
        id: "req1",
        request_id: "req1",
        project_id: null,
        project_name: "",
        description: "«fatura.pdf» → Gider olarak önerildi",
        amount_try: "10000.00",
        created_at: "2026-06-21T08:00:00Z",
        proposed_by_agent: true,
        payload: {
          destination: "cost",
          confidence: 0.92,
          original_filename: "fatura.pdf",
          project_id_guess: null,
          fields: { supplier_name: "ABC", amount_try: 10000, vat_rate: 20, cost_category: "material_other", invoice_number: "F1" },
        },
      },
    ] as any[],
    meta: null,
    loading: false,
    error: null as string | null,
    refetch: vi.fn(),
  },
  projects: { data: [{ id: "p1", name: "Proje A" }], meta: null, loading: false, error: null, refetch: vi.fn() },
}));

vi.mock("@/hooks/useFetch", () => ({
  useFetch: (url: string | null) => (url === "/projects" ? h.projects : h.approvals),
}));
vi.mock("@/lib/api", () => ({ apiPut: vi.fn(() => Promise.resolve({})) }));
vi.mock("@/store/auth", () => ({ useAuth: () => ({ user: { role: "director" } }) }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/layout/AppLayout", () => ({ PageHeader: ({ title }: { title: string }) => createElement("h1", null, title) }));
vi.mock("@/components/ai/AiTrustBadge", () => ({ AiTrustBadge: () => createElement("div", null, "trust") }));

import { apiPut } from "@/lib/api";
import ApprovalsPage from "./ApprovalsPage";

afterEach(cleanup);

it("renders the auto-file proposal row with an İncele button", () => {
  render(<ApprovalsPage />);
  expect(screen.getByText("Belge Dosyalama (AI önerisi)")).toBeInTheDocument();
  expect(screen.getByText(/İncele/)).toBeInTheDocument();
});

it("review modal shows destination + confidence and approve sends project + fields", async () => {
  render(<ApprovalsPage />);
  fireEvent.click(screen.getByText(/İncele/));
  // Confidence + destination surfaced in the card.
  expect(screen.getByText("Güven %92")).toBeInTheDocument();
  expect(screen.getByText("Gider olarak önerildi")).toBeInTheDocument(); // modal badge (exact)

  // Approve without a project is blocked client-side; pick the project then approve.
  const select = screen.getAllByRole("combobox")[0]; // project picker is first
  fireEvent.change(select, { target: { value: "p1" } });
  fireEvent.click(screen.getByText("Onayla & Oluştur"));

  await waitFor(() =>
    expect(apiPut).toHaveBeenCalledWith(
      "/approvals/request/req1/approve",
      expect.objectContaining({ project_id: "p1", fields: expect.objectContaining({ amount_try: 10000 }) })
    )
  );
});
