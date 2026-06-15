// CR-009-C smoke test for the drag-drop Çalışma Alanım.
// react-grid-layout is mocked to a controllable stub so we can assert OUR page
// contract: it renders pinned items, a (desktop) layout change debounce-PUTs to
// /workspace/layout, and below lg the grid is read-only (no drag, no persist).
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { setMatchMedia } from "@/test/setup";

const h = vi.hoisted(() => ({
  fetch: { data: [] as any[], loading: false, error: null as string | null, refetch: () => {} },
  grid: { props: null as any },
}));

vi.mock("@/hooks/useFetch", () => ({ useFetch: () => h.fetch }));
vi.mock("@/lib/api", () => ({
  apiPut: vi.fn(() => Promise.resolve({})),
  apiDelete: vi.fn(() => Promise.resolve({})),
}));
// Capture the grid props; render children so cards still mount.
vi.mock("react-grid-layout", () => ({
  WidthProvider: (C: any) => C,
  Responsive: (props: any) => {
    h.grid.props = props;
    return createElement("div", { "data-testid": "grid" }, props.children);
  },
}));
// Stub heavy leaf components so the smoke test stays focused + fast.
vi.mock("@/components/charts/AgentChart", () => ({ AgentChart: () => createElement("div", { "data-testid": "chart" }) }));
vi.mock("@/components/MarkdownText", () => ({ MarkdownText: ({ text }: { text: string }) => createElement("div", null, text) }));
vi.mock("@/components/layout/AppLayout", () => ({ PageHeader: ({ title }: { title: string }) => createElement("h1", null, title) }));
vi.mock("@/components/EmptyState", () => ({
  EmptyState: ({ message }: { message: string }) => createElement("div", null, message),
  LoadError: () => createElement("div", null, "hata"),
}));

import { apiPut } from "@/lib/api";
import WorkspacePage from "./WorkspacePage";

const ITEM = {
  id: "i1",
  title: "Bozkurt Analizi",
  item_type: "analysis",
  payload: { answer_markdown: "Toplam 1.500 ₺", citations: [] },
  layout: { x: 0, y: 0, w: 6, h: 3 },
  pinned_at: "2026-06-15T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  h.fetch = { data: [], loading: false, error: null, refetch: () => {} };
  h.grid.props = null;
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("WorkspacePage (drag-drop board)", () => {
  it("renders pinned items in the grid", () => {
    setMatchMedia(true); // desktop
    h.fetch.data = [ITEM];
    render(createElement(WorkspacePage));
    expect(screen.getByTestId("grid")).toBeInTheDocument();
    expect(screen.getByText("Bozkurt Analizi")).toBeInTheDocument();
    expect(screen.getByText(/tarihinde sabitlendi/)).toBeInTheDocument();
  });

  it("shows the empty state when there are no items", () => {
    setMatchMedia(true);
    h.fetch.data = [];
    render(createElement(WorkspacePage));
    expect(screen.getByText(/Henüz bir şey sabitlemediniz/)).toBeInTheDocument();
  });

  it("debounce-persists a desktop layout change to /workspace/layout", () => {
    setMatchMedia(true); // desktop → draggable + persists
    h.fetch.data = [ITEM];
    render(createElement(WorkspacePage));

    expect(h.grid.props.isDraggable).toBe(true);
    expect(h.grid.props.isResizable).toBe(true);

    // Simulate a drag/resize: rgl calls onLayoutChange with the new layout.
    h.grid.props.onLayoutChange([{ i: "i1", x: 6, y: 2, w: 4, h: 4 }]);
    expect(apiPut).not.toHaveBeenCalled(); // debounced
    vi.advanceTimersByTime(700);

    expect(apiPut).toHaveBeenCalledWith("/workspace/layout", {
      items: [{ id: "i1", x: 6, y: 2, w: 4, h: 4 }],
    });
  });

  it("is read-only below lg (no drag/resize, no persist)", () => {
    setMatchMedia(false); // mobile
    h.fetch.data = [ITEM];
    render(createElement(WorkspacePage));

    expect(h.grid.props.isDraggable).toBe(false);
    expect(h.grid.props.isResizable).toBe(false);

    // A layout change on mobile must NOT overwrite the saved desktop layout.
    h.grid.props.onLayoutChange([{ i: "i1", x: 0, y: 0, w: 1, h: 3 }]);
    vi.advanceTimersByTime(700);
    expect(apiPut).not.toHaveBeenCalled();
  });
});
