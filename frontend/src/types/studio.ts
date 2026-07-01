// CR-033 Report Studio — frontend mirror of the FIXED backend contract
// (app/api/studio.py, app/services/studio/catalog.py, app/services/studio/engine.py).
// The spec we build in the editor is POSTed verbatim to /studio/run and saved as a
// report's `spec`. Keep these shapes aligned with the backend; do not invent fields.

export type Viz = "line" | "area" | "bar" | "kpi" | "table";
export type CatalogStatus = "available" | "coming_soon";
export type Visibility = "private" | "company";

// GET /studio/catalog → { dimensions, metrics }
export interface CatalogDimension {
  id: string;
  label: string;
  type: string; // "enum" | "date" | "currency" | "percent" | "number" | …
  group: string;
  description: string;
  status: CatalogStatus;
}
export interface CatalogMetric extends CatalogDimension {
  // windowed:true honours the date range; false = whole-project snapshot (CR-032).
  windowed: boolean;
}
export interface StudioCatalog {
  dimensions: CatalogDimension[];
  metrics: CatalogMetric[];
}

// --- the Spec (§2) ---------------------------------------------------------- #
export interface StudioFilter {
  field: string;
  op: "=" | "!=" | "in" | "not_in";
  value: unknown;
}
export interface DateWindow {
  preset?: string;
  from?: string;
  to?: string;
}
export interface StudioBasis {
  cost?: "actual" | "actual_plus_open";
  currency?: "try" | "usd";
  financing?: "excl" | "incl";
  vat?: "excl" | "incl";
}
export interface StudioChart {
  x?: string | null;
  y_left?: string[];
  y_right?: string[];
  // UI-only chart prefs (the engine ignores unknown chart keys; honoured client-side).
  legend?: boolean;
  cumulative?: boolean;
}
export interface StudioSpec {
  metrics: string[];
  dimensions: string[];
  viz: Viz;
  filters?: StudioFilter[];
  date_range?: DateWindow | null;
  comparison?: { preset?: string; from?: string; to?: string } | null;
  comparison_unit?: "pct" | "abs";
  basis?: StudioBasis;
  sort?: { by: string; dir: "asc" | "desc" };
  limit?: number;
  chart?: StudioChart;
}

// --- POST /studio/run → result (§2) ----------------------------------------- #
export interface RunColumn {
  id: string;
  label: string;
  kind: "dimension" | "metric";
  type: string;
}
export interface RunRow {
  dims: Record<string, string | null>;
  metrics: Record<string, number | null>;
  deltas: Record<string, number | null> | null;
}
export interface RunResult {
  columns: RunColumn[];
  rows: RunRow[];
  totals: {
    metrics: Record<string, number | null>;
    deltas: Record<string, number | null> | null;
  };
  meta: {
    row_count: number;
    basis: Required<StudioBasis>;
    date_range: { from: string | null; to: string | null };
    comparison: { from: string | null; to: string | null } | null;
    currency: "try" | "usd";
    truncated: boolean;
    unavailable: string[];
    usd_missing_count: number;
  };
  series?: {
    name: string;
    metric: string;
    points: { x: string; y: number | null }[];
    compare: { x: string; y: number | null }[] | null;
  }[];
}

// --- persistence (CR-033) --------------------------------------------------- #
export interface ReportListItem {
  id: string;
  title: string;
  owner_id: string;
  visibility: string;
  updated_at: string;
  labels: string[] | null;
  viz: string;
}
export interface ReportOut {
  id: string;
  title: string;
  spec: StudioSpec;
  visibility: string;
  labels: string[] | null;
  owner_id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  is_owner: boolean;
}
export interface ReportSaveBody {
  title: string;
  spec: StudioSpec;
  visibility: Visibility;
  labels: string[] | null;
}
export interface ReportPatchBody {
  title?: string;
  spec?: StudioSpec;
  visibility?: Visibility;
  labels?: string[] | null;
}

// --- panolar / dashboards (CR-034) ----------------------------------------- #
// A pano is a saved canvas of widgets on a react-grid-layout grid plus
// dashboard-global date_range/comparison/filters. Mirrors the FIXED backend
// contract (app/schemas/dashboard.py + app/api/studio.py). One widget carries
// EXACTLY ONE payload matching its type: kpi/chart/table → `spec`, report →
// `report_id`, text → `content` (the backend's WidgetSpec envelope invariant).
export type WidgetType = "kpi" | "chart" | "table" | "text" | "report";

export interface WidgetLayout {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Widget {
  id: string; // client-generated, unique within the dashboard
  type: WidgetType;
  title: string;
  layout: WidgetLayout;
  section?: string | null;
  spec?: StudioSpec; // kpi | chart | table
  report_id?: string; // report
  content?: string; // text
}

export interface DashboardListItem {
  id: string;
  title: string;
  owner_id: string;
  visibility: string;
  updated_at: string;
  labels: string[] | null;
  widget_count: number;
}

export interface Dashboard {
  id: string;
  title: string;
  widgets: Widget[];
  date_range: DateWindow | null;
  comparison: { preset?: string; from?: string; to?: string } | null;
  filters: StudioFilter[] | null;
  visibility: string;
  labels: string[] | null;
  owner_id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  is_owner: boolean;
}

export interface DashboardSaveBody {
  title: string;
  widgets: Widget[];
  date_range?: DateWindow | null;
  comparison?: { preset?: string; from?: string; to?: string } | null;
  filters?: StudioFilter[] | null;
  visibility: Visibility;
  labels?: string[] | null;
}

export interface DashboardPatchBody {
  title?: string;
  widgets?: Widget[];
  date_range?: DateWindow | null;
  comparison?: { preset?: string; from?: string; to?: string } | null;
  filters?: StudioFilter[] | null;
  visibility?: Visibility;
  labels?: string[] | null;
}

// POST /studio/dashboards/{id}/run → { [widget_id]: RunResult | {unavailable:true} }
// (text widgets are absent from the dict — the FE renders their `content`).
export type WidgetRunResult = RunResult | { unavailable: true };
export type DashboardRunResult = Record<string, WidgetRunResult>;
