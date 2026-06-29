import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// CR-011-E — component-level acceptance gap: the proposed-action REJECT flow.
// (CR-044.1 removed the analysis-export button + its tests.)
const { apiPut, toastSuccess, toastError, mockAuth } = vi.hoisted(() => ({
  apiPut: vi.fn(() => Promise.resolve({})),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  mockAuth: { user: { role: "director" } as { role: string } | null },
}));

vi.mock("@/store/toast", () => ({
  toast: { success: toastSuccess, error: toastError, info: vi.fn(), warning: vi.fn() },
}));
vi.mock("@/lib/api", () => ({ apiPut, apiPost: vi.fn(), baseURL: "" }));
vi.mock("@/store/auth", () => ({ useAuth: () => mockAuth }));

import { ProposedActionCard } from "@/components/ai/ProposedActionCard";

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  mockAuth.user = { role: "director" };
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
