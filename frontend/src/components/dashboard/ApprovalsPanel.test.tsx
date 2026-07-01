// Reliability fix smoke test: a failed load must render a RETRYABLE error state
// (not the "no pending approvals" empty state), while an empty-but-successful
// load keeps the friendly empty state. useFetch is mocked to a controllable stub.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  fetch: { data: null as any, loading: false, error: null as string | null, refetch: vi.fn() },
}));

vi.mock("@/hooks/useFetch", () => ({ useFetch: () => h.fetch }));

import { ApprovalsPanel } from "./ApprovalsPanel";

beforeEach(() => {
  h.fetch = { data: null, loading: false, error: null, refetch: vi.fn() };
});
afterEach(cleanup);

describe("ApprovalsPanel load-failure handling", () => {
  it("shows a retryable error state when the fetch fails", () => {
    h.fetch.error = "Network error";
    render(createElement(ApprovalsPanel, { onGoToApprovals: () => {} }));

    // Error, not the empty state.
    expect(screen.getByText(/Onaylar yüklenemedi/)).toBeInTheDocument();
    expect(screen.queryByText(/Onay bekleyen işlem yok/)).not.toBeInTheDocument();

    // "Tekrar Dene" re-runs the fetch.
    fireEvent.click(screen.getByRole("button", { name: /Tekrar Dene/ }));
    expect(h.fetch.refetch).toHaveBeenCalledTimes(1);
  });

  it("shows the friendly empty state on an empty-but-successful load", () => {
    h.fetch.data = [];
    render(createElement(ApprovalsPanel, { onGoToApprovals: () => {} }));

    expect(screen.getByText(/Onay bekleyen işlem yok/)).toBeInTheDocument();
    expect(screen.queryByText(/Onaylar yüklenemedi/)).not.toBeInTheDocument();
  });
});
