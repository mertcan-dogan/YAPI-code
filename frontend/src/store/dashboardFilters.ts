import { create } from "zustand";

// CR-029 fix #1: the dashboard date-range now lives in the (global) top header, so
// the header control and the dashboard data fetch share this small store.
export type DateRange = "all" | "this_month" | "last_3_months" | "this_year";

interface DashboardFiltersState {
  range: DateRange;
  setRange: (r: DateRange) => void;
}

export const useDashboardFilters = create<DashboardFiltersState>((set) => ({
  range: "all",
  setRange: (range) => set({ range }),
}));

export const RANGE_LABELS: Record<DateRange, string> = {
  all: "Tüm Zamanlar",
  this_month: "Bu Ay",
  last_3_months: "Son 3 Ay",
  this_year: "Bu Yıl",
};
