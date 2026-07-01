// Reliability fix smoke test: a failed load renders a RETRYABLE error state
// instead of the "no records" empty state; an empty-but-successful load keeps the
// friendly empty state. useFetch is mocked to a controllable stub.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  fetch: { data: null as any, loading: false, error: null as string | null, refetch: vi.fn() },
}));

vi.mock("@/hooks/useFetch", () => ({ useFetch: () => h.fetch }));

import { IncomingWorkflowCard } from "./IncomingWorkflowCard";

const EMPTY_FEED = { faturalar: [], hakedisler: [], ek_isler: [] };

beforeEach(() => {
  h.fetch = { data: null, loading: false, error: null, refetch: vi.fn() };
});
afterEach(cleanup);

describe("IncomingWorkflowCard load-failure handling", () => {
  it("shows a retryable error state when the fetch fails", () => {
    h.fetch.error = "500";
    render(createElement(IncomingWorkflowCard));

    expect(screen.getByText(/Gelen belgeler yüklenemedi/)).toBeInTheDocument();
    expect(screen.queryByText(/gösterilecek kayıt yok/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Tekrar Dene/ }));
    expect(h.fetch.refetch).toHaveBeenCalledTimes(1);
  });

  it("shows the friendly empty state on an empty-but-successful load", () => {
    h.fetch.data = EMPTY_FEED;
    render(createElement(IncomingWorkflowCard));

    expect(screen.getByText(/gösterilecek kayıt yok/)).toBeInTheDocument();
    expect(screen.queryByText(/Gelen belgeler yüklenemedi/)).not.toBeInTheDocument();
  });
});
