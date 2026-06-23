// Silent-load-failure guard: a failed /projects load must surface a clear Turkish
// error + retry where the project dropdown would be — never an empty dropdown that
// reads as "no projects". useFetch is mocked so we can drive the error/loading state.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  projects: { data: null as any, meta: null as any, loading: false, error: null as string | null, refetch: () => {} },
}));

vi.mock("@/hooks/useFetch", () => ({ useFetch: () => h.projects }));
vi.mock("@/lib/api", () => ({ api: { get: vi.fn(() => Promise.resolve({ data: new Blob() })) } }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/layout/AppLayout", () => ({ PageHeader: ({ title }: { title: string }) => createElement("h1", null, title) }));

import ReportsPage from "./ReportsPage";

beforeEach(() => {
  h.projects = { data: [{ id: "p1", name: "Test Projesi" }] as any, meta: null, loading: false, error: null, refetch: () => {} };
});
afterEach(cleanup);

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
    // The dropdown placeholder is NOT shown; a clear error + retry is.
    expect(screen.queryByText("Proje seçin...")).not.toBeInTheDocument();
    expect(screen.getByText("Projeler yüklenemedi.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Tekrar Dene"));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows a disabled loading placeholder (not the error state) while the projects are loading", () => {
    h.projects = { data: null, meta: null, loading: true, error: null, refetch: () => {} };
    render(createElement(ReportsPage));
    expect(screen.getByText("Projeler yükleniyor…")).toBeInTheDocument();
    // The dropdown is present but disabled while loading; the error is NOT shown.
    expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(true);
    expect(screen.queryByText("Projeler yüklenemedi.")).not.toBeInTheDocument();
  });

  it("prefers the loading placeholder over the error state when a load is in flight (error gated on !loading)", () => {
    // A stale error from a prior attempt must not pre-empt an in-flight retry.
    h.projects = { data: null, meta: null, loading: true, error: "500", refetch: () => {} };
    render(createElement(ReportsPage));
    expect(screen.getByText("Projeler yükleniyor…")).toBeInTheDocument();
    expect(screen.queryByText("Projeler yüklenemedi.")).not.toBeInTheDocument();
  });
});
