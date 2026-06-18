import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AIAlert } from "@/types";

const { apiPostMock, toastErrorMock, toastSuccessMock } = vi.hoisted(() => ({
  apiPostMock: vi.fn(),
  toastErrorMock: vi.fn(),
  toastSuccessMock: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ apiPost: apiPostMock }));
vi.mock("@/store/toast", () => ({ toast: { error: toastErrorMock, success: toastSuccessMock } }));

import { FinansGuvence } from "./FinansGuvence";

function finding(over: Partial<AIAlert> = {}): AIAlert {
  return {
    id: "f1",
    project_id: "p1",
    alert_type: "duplicate_cost",
    severity: "high",
    title_tr: "Yinelenen kayıt",
    body_tr: "Aynı tutarda iki maliyet kaydı bulundu.",
    reasoning: "İki maliyet kaydı aynı tutarda — yinelenmiş olabilir. İncelemeniz önerilir.",
    recommended_action: "Yinelenen kaydı silin veya birleştirin.",
    is_actioned: false,
    created_at: "2026-06-18T09:00:00Z",
    feedback: null,
    source_type: "cost_entry",
    source_id: "c1",
    dedup_key: "duplicate_cost:a|b",
    ...over,
  };
}

function renderFG(props: Partial<React.ComponentProps<typeof FinansGuvence>> = {}) {
  const handlers = {
    findings: [finding()],
    onDismiss: vi.fn(),
    onFeedback: vi.fn(),
    onRefetch: vi.fn(),
    ...props,
  };
  render(
    <MemoryRouter>
      <FinansGuvence {...handlers} />
    </MemoryRouter>
  );
  return handlers;
}

afterEach(() => vi.clearAllMocks());

describe("FinansGuvence", () => {
  it("renders findings with reasoning and a deep-link to the record", () => {
    renderFG();
    expect(screen.getByText(/yinelenmiş olabilir/i)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Kaydı incele/i });
    expect(link).toHaveAttribute("href", "/projects/p1/dashboard?highlight=c1");
  });

  it("shows the empty state when there are no findings", () => {
    renderFG({ findings: [] });
    expect(screen.getByText(/Tebrikler — bulgu yok\./i)).toBeInTheDocument();
  });

  it("'Şimdi tara' calls the scan endpoint and shows the summary banner", async () => {
    apiPostMock.mockResolvedValue({
      scanned: { cost_entries: 10, client_invoices: 5 },
      found: { duplicate_cost: 1 },
      total_found: 1,
      created: 1,
    });
    const { onRefetch } = renderFG({ findings: [] });

    fireEvent.click(screen.getByRole("button", { name: /Şimdi tara/i }));

    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith("/ai/assurance/scan"));
    expect(onRefetch).toHaveBeenCalled();
    expect(await screen.findByText(/15 kayıt tarandı/)).toBeInTheDocument();
    expect(screen.getByText(/1 bulgu/)).toBeInTheDocument();
  });

  it("degrades to a toast (no crash) when the scan fails", async () => {
    apiPostMock.mockRejectedValue(new Error("network"));
    renderFG({ findings: [] });
    fireEvent.click(screen.getByRole("button", { name: /Şimdi tara/i }));
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalled());
  });

  it("dismiss and feedback call the handlers with the right ids", () => {
    const { onDismiss, onFeedback } = renderFG();
    fireEvent.click(screen.getByLabelText("Kapat"));
    expect(onDismiss).toHaveBeenCalledWith("f1");
    fireEvent.click(screen.getByLabelText("Yararlı"));
    expect(onFeedback).toHaveBeenCalledWith("f1", "useful");
  });
});
