// CR-019-C — MilestonesCard: summary card + manager (add/complete/reorder,
// grouped by stage, overdue highlighting). useFetch + api* are mocked.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  list: { data: [] as any[] | null, meta: null as any, loading: false, error: null as string | null, refetch: vi.fn() },
}));

vi.mock("@/hooks/useFetch", () => ({ useFetch: () => h.list }));
vi.mock("@/lib/api", () => ({
  apiPost: vi.fn(() => Promise.resolve({})),
  apiPut: vi.fn(() => Promise.resolve({})),
  apiDelete: vi.fn(() => Promise.resolve({})),
}));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { apiPost, apiPut } from "@/lib/api";
import { MilestonesCard, type MilestonesBlock } from "./MilestonesCard";

const BLOCK: MilestonesBlock = {
  schedule_progress_pct: "16.67",
  total: 3,
  done: 1,
  next_deadline: "2099-01-01",
  overdue_count: 1,
  by_stage: [],
};

const MILESTONES = [
  { id: "m1", project_id: "p1", title: "Temel", stage: "Kaba", planned_date: "2020-01-01", weight: "2", status: "pending", completed_date: null, sort_order: 0, notes: null },
  { id: "m2", project_id: "p1", title: "Kolonlar", stage: "Kaba", planned_date: "2099-01-01", weight: "3", status: "pending", completed_date: null, sort_order: 1, notes: null },
  { id: "m3", project_id: "p1", title: "Boya", stage: "İnce", planned_date: "2099-06-01", weight: "1", status: "done", completed_date: "2026-01-01", sort_order: 2, notes: null },
];

function open() {
  // Click the card header to open the manager modal.
  fireEvent.click(screen.getByText("Aşamalar & Kilometre Taşları"));
}

beforeEach(() => {
  h.list = { data: MILESTONES, meta: null, loading: false, error: null, refetch: vi.fn() };
});
afterEach(cleanup);

describe("MilestonesCard summary", () => {
  it("shows weighted progress, completed count, next deadline and overdue badge", () => {
    render(createElement(MilestonesCard, { projectId: "p1", block: BLOCK, canManage: true, onChanged: () => {} }));
    expect(screen.getByText("Aşamalar & Kilometre Taşları")).toBeInTheDocument();
    expect(screen.getByText("1 / 3 tamamlandı")).toBeInTheDocument();
    expect(screen.getByText(/Sıradaki:/)).toBeInTheDocument();
    expect(screen.getByText(/1 gecikmiş/)).toBeInTheDocument();
  });

  it("shows the empty hint when there are no milestones", () => {
    render(createElement(MilestonesCard, { projectId: "p1", block: { ...BLOCK, total: 0, done: 0, schedule_progress_pct: null, overdue_count: 0, next_deadline: null }, canManage: true, onChanged: () => {} }));
    expect(screen.getByText(/Henüz kilometre taşı eklenmedi/)).toBeInTheDocument();
  });
});

describe("MilestonesCard manager", () => {
  it("lists milestones grouped by stage with overdue rows highlighted", () => {
    render(createElement(MilestonesCard, { projectId: "p1", block: BLOCK, canManage: true, onChanged: () => {} }));
    open();
    // Stage group headers.
    expect(screen.getByText("Kaba")).toBeInTheDocument();
    expect(screen.getByText("İnce")).toBeInTheDocument();
    // The past-dated, not-done milestone is flagged overdue (card badge + the row).
    expect(screen.getAllByText(/gecikmiş/).length).toBeGreaterThan(1);
    expect(screen.getByText("Temel")).toBeInTheDocument();
  });

  it("adds a milestone via the form (POST)", () => {
    render(createElement(MilestonesCard, { projectId: "p1", block: BLOCK, canManage: true, onChanged: () => {} }));
    open();
    fireEvent.change(screen.getByPlaceholderText(/Temel betonu döküldü/), { target: { value: "Çatı" } });
    fireEvent.click(screen.getByText("Ekle"));
    expect(apiPost).toHaveBeenCalledWith("/projects/p1/milestones", expect.objectContaining({ title: "Çatı" }));
  });

  it("marks a milestone complete (PUT status=done)", () => {
    render(createElement(MilestonesCard, { projectId: "p1", block: BLOCK, canManage: true, onChanged: () => {} }));
    open();
    fireEvent.click(screen.getAllByLabelText("Tamamla")[0]); // first pending row = m1
    expect(apiPut).toHaveBeenCalledWith("/projects/p1/milestones/m1", { status: "done" });
  });

  it("reorders via sort_order (PUT reorder with swapped order)", () => {
    render(createElement(MilestonesCard, { projectId: "p1", block: BLOCK, canManage: true, onChanged: () => {} }));
    open();
    fireEvent.click(screen.getAllByLabelText("Aşağı taşı")[0]); // move m1 down → swap with m2
    expect(apiPut).toHaveBeenCalledWith("/projects/p1/milestones/reorder", {
      items: [
        { id: "m2", sort_order: 0 },
        { id: "m1", sort_order: 1 },
        { id: "m3", sort_order: 2 },
      ],
    });
  });

  it("hides the editor controls for non-managers", () => {
    render(createElement(MilestonesCard, { projectId: "p1", block: BLOCK, canManage: false, onChanged: () => {} }));
    open();
    expect(screen.queryByText("Ekle")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Tamamla")).not.toBeInTheDocument();
    // But the list is still visible (read-only).
    expect(screen.getByText("Temel")).toBeInTheDocument();
  });

  it("shows a retryable error when the list fails to load", () => {
    h.list = { data: null, meta: null, loading: false, error: "500", refetch: vi.fn() };
    render(createElement(MilestonesCard, { projectId: "p1", block: BLOCK, canManage: true, onChanged: () => {} }));
    open();
    expect(screen.getByText(/Kilometre taşları yüklenemedi/)).toBeInTheDocument();
  });
});
