// CR-044 — Beceriler (Skills): frontend mirror of the FIXED backend contract
// (app/api/skills.py, app/schemas/skill.py). A skill = a saved, named "deliverable
// recipe": a free-form Turkish `instruction` + a `plan` (dashboard-shaped JSONB the
// agent compiles from the instruction) + an output `format`. Running a skill
// generates a real Excel/PDF from LIVE data (the figures come from the engine at
// run time — never the LLM). Keep these shapes aligned with the backend; do not
// invent fields.
import type { Visibility, Widget } from "./studio";

export type SkillFormat = "xlsx" | "pdf";
export type SkillRunStatus = "ok" | "error";

// CR-044.1 — the latest successful run embedded on Skill responses (for "Son
// çalıştırma" + an immediate re-download İndir). run_id re-signs via
// POST /skills/runs/{run_id}/download.
export interface SkillRunSummary {
  run_id: string;
  run_at: string;
  file_name: string | null;
  status: SkillRunStatus;
}

// The compiled, runnable plan = a dashboard-shaped spec (a set of CR-032 widget
// specs + the output format). The agent builds it exactly as it drafts a pano.
export interface SkillPlan {
  format: SkillFormat;
  title: string;
  widgets: Widget[];
  date_range?: import("./studio").DateWindow | null;
}

// GET /skills → list item (lean; the full plan/instruction load on detail).
export interface SkillListItem {
  id: string;
  name: string;
  format: SkillFormat;
  visibility: string;
  owner_id: string;
  updated_at: string;
  labels: string[] | null;
  last_run_at: string | null; // null until the skill has been run at least once
  last_run: SkillRunSummary | null; // CR-044.1 — latest ok run (for İndir on load)
}

// GET /skills/{id} → full skill.
export interface SkillOut {
  id: string;
  name: string;
  instruction: string;
  plan: SkillPlan;
  format: SkillFormat;
  visibility: string;
  labels: string[] | null;
  owner_id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  is_owner: boolean;
  last_run: SkillRunSummary | null; // CR-044.1
}

// POST /skills body (the user's save action — owner = CurrentUser).
export interface SkillCreateBody {
  name: string;
  instruction: string;
  plan: SkillPlan;
  format: SkillFormat;
  visibility: Visibility;
  labels?: string[] | null;
}

// PUT /skills/{id} body (partial).
export interface SkillPatchBody {
  name?: string;
  instruction?: string;
  plan?: SkillPlan;
  format?: SkillFormat;
  visibility?: Visibility;
  labels?: string[] | null;
}

// GET /skills/{id}/runs → run history item.
export interface SkillRunOut {
  id: string;
  skill_id: string;
  status: SkillRunStatus;
  file_name: string;
  format: SkillFormat;
  run_at: string;
  error: string | null;
  run_by: string | null;
}

// POST /skills/{id}/run → a fresh run + a short-lived signed URL to the file.
export interface SkillRunResult {
  run_id: string;
  file_name: string;
  format: SkillFormat;
  download_url: string;
}

// POST /skills/runs/{run_id}/download → re-sign for re-download.
export interface SkillDownloadResult {
  download_url: string;
  file_name: string;
  format: SkillFormat;
}
