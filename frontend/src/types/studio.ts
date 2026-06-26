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
