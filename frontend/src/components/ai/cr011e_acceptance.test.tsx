import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentResponse } from "@/types/agent";

// CR-011-E — component-level acceptance gaps: proposed-action REJECT flow + the
// analysis export button (PDF/Excel) posting to the export endpoint.
const { apiPut, apiPostExport, toastSuccess, toastError, mockAuth } = vi.hoisted(() => ({
  apiPut: vi.fn(() => Promise.resolve({})),
  apiPostExport: vi.fn((..._args: any[]) => Promise.resolve({ data: new Blob(["x"]) })),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  mockAuth: { user: { role: "director" } as { role: string } | null },
}));

vi.mock("@/store/toast", () => ({
  toast: { success: toastSuccess, error: toastError, info: vi.fn(), warning: vi.fn() },
}));
vi.mock("@/lib/api", () => ({ apiPut, apiPost: vi.fn(), api: { post: apiPostExport }, baseURL: "" }));
vi.mock("@/store/auth", () => ({ useAuth: () => mockAuth }));

import { AnalysisExportButton } from "@/components/ai/AnalysisExportButton";
import { ProposedActionCard } from "@/components/ai/ProposedActionCard";

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  mockAuth.user = { role: "director" };
  // jsdom lacks object-URL helpers used by the download.
  (URL as any).createObjectURL = vi.fn(() => "blob:fake");
  (URL as any).revokeObjectURL = vi.fn();
});
afterEach(() => vi.clearAllMocks());

const ACTION = {
  request_id: "r5",
  kind: "agent_flag_invoice",
  kind_label: "İnceleme İşareti (AI önerisi)",
  description: "Fatura HK-1 incelensin",
  status: "pending",
  deep_link: "/approvals",
};

describe("ProposedActionCard reject (CR-011-E)", () => {
  it("director rejects with a reason -> posts to the approvals reject endpoint", async () => {
    wrap(<ProposedActionCard action={ACTION} />);
    // Open the reason form.
    fireEvent.click(screen.getByText("Reddet"));
    const reason = screen.getByPlaceholderText("Red nedeni");
    fireEvent.change(reason, { target: { value: "Hatalı tutar" } });
    // Submit (the form's Reddet button).
    fireEvent.click(screen.getByText("Reddet"));
    await waitFor(() =>
      expect(apiPut).toHaveBeenCalledWith("/approvals/request/r5/reject", { reason: "Hatalı tutar" })
    );
    expect(await screen.findByText(/Reddedildi/)).toBeInTheDocument();
  });

  it("requires a reason before rejecting", () => {
    wrap(<ProposedActionCard action={ACTION} />);
    fireEvent.click(screen.getByText("Reddet"));
    // Submit button is disabled while the reason is empty → no POST.
    fireEvent.click(screen.getByText("Reddet"));
    expect(apiPut).not.toHaveBeenCalled();
  });
});

const RES: AgentResponse = {
  answer_markdown: "Analiz",
  charts: [],
  citations: [],
  tools_used: [],
  generated_at: "2026-06-19T08:00:00Z",
  proposed_actions: [],
};

describe("AnalysisExportButton (CR-011-E)", () => {
  it("exports to PDF via the export endpoint", async () => {
    wrap(<AnalysisExportButton res={RES} question="soru" />);
    fireEvent.click(screen.getByText("Dışa aktar"));
    fireEvent.click(screen.getByText("PDF"));
    await waitFor(() => expect(apiPostExport).toHaveBeenCalled());
    const [url, body, cfg] = apiPostExport.mock.calls[0];
    expect(url).toBe("/ai/agent/export");
    expect(body).toMatchObject({ answer_markdown: "Analiz", question: "soru" });
    expect(cfg).toMatchObject({ params: { fmt: "pdf" }, responseType: "blob" });
  });

  it("exports to Excel via the export endpoint", async () => {
    wrap(<AnalysisExportButton res={RES} question={null} />);
    fireEvent.click(screen.getByText("Dışa aktar"));
    fireEvent.click(screen.getByText("Excel (.xlsx)"));
    await waitFor(() => expect(apiPostExport).toHaveBeenCalled());
    expect(apiPostExport.mock.calls[0][2]).toMatchObject({ params: { fmt: "excel" } });
  });
});
