// CR-007 — AI agent response shapes (shared by AIAssistantPage + AgentChart).

export interface AgentChartSeries {
  key: string;
  label: string;
  type: "line" | "bar";
  color?: string;
}

export interface AgentChartSpec {
  chart_type: "line" | "bar" | "composed";
  title: string;
  x_key: string;
  series: AgentChartSeries[];
  data: Record<string, unknown>[];
  currency?: "TRY" | "EUR" | "USD" | null;
  source_note?: string;
}

export interface Citation {
  type: string;
  id: string;
  label: string;
  deep_link: string;
}

// CR-011-B — domain scope for the scoped-agent dock. null/undefined = genel.
export type AgentScope = "gider" | "gelir" | "finans" | "hakedis" | "belge";

// CR-011-C — a write the agent PROPOSED (a pending approval request). The UI
// shows it as an Onayla/Reddet card; nothing is ever written without approval.
export interface ProposedAction {
  // CR-039: the FE discriminates on `kind`. Approval kinds (agent_reminder /
  // agent_flag_invoice / agent_task, + the dormant agent_create_*) carry
  // request_id/status/deep_link and route through /approvals. The authoring DRAFT
  // kinds "draft_report" / "draft_dashboard" carry NONE of those — the card renders
  // Oluştur/Düzenle/İptal and the user creates their own artifact (no approval).
  request_id?: string;
  kind: string;
  kind_label: string;
  description?: string;
  amount_try?: string | null;
  project_id?: string | null;
  status?: string; // "pending" for approval kinds; absent for drafts
  deep_link?: string; // "/approvals" for approval kinds; absent for drafts
  // CR-035/CR-039 (additive): the authoring kinds carry the proposed artifact so
  // the card can render a spec summary + a live preview.
  // report (draft_report / agent_create_report)    → title + spec (a CR-032 StudioSpec).
  // dashboard (draft_dashboard / agent_create_dashboard) → title + widgets[] (+ date_range/comparison/filters).
  title?: string;
  spec?: any;
  widgets?: any[];
  date_range?: any;
  comparison?: any;
  filters?: any;
  // CR-039 — the user-chosen create payload for a draft.
  visibility?: string;
  labels?: string[] | null;
  // CR-056 (additive) — advisory STRUCTURAL findings the compile step detected
  // (duplicate / mislabel). The FE merges in its data-aware findings, renders a
  // critique summary + inline badges + option buttons, and the user's click trims/
  // retitles the in-memory draft. Never auto-applied; the plan is unchanged here.
  critique?: import("../lib/critique").Finding[];
  // CR-044 (additive) — "draft_skill": a reusable file-recipe the agent compiled.
  // It carries the free-form `instruction`, the dashboard-shaped `plan` (the engine
  // runs this — the LLM never writes figures), and the output `format`. Title is the
  // skill name (reuses `title` above). The user saves it via "Beceri olarak kaydet".
  instruction?: string;
  plan?: import("./skill").SkillPlan;
  format?: import("./skill").SkillFormat;
  // CR-044 (additive) — "run_result": NOT a proposal, a download card. Emitted when
  // a skill runs (in chat or from Uygulamalar). Carries the signed `download_url` to
  // the generated private file + the run/skill identity for the outputs panel.
  run_id?: string;
  file_name?: string;
  download_url?: string;
  skill_id?: string;
  skill_name?: string;
}

// CR-038 §G (reserved — declared, NOT built): the conversation/message model is
// kept open so CR-039's attachments + agent-generated artifacts persist without a
// breaking change. These types are intentionally unused by CR-038's rendering.
export interface AgentAttachment {
  id: string;
  name: string;
  mime: string;
  size: number;
  kind: "image" | "excel" | "pdf" | "other";
  url?: string | null;
}

export interface AgentArtifact {
  id: string;
  kind: string; // "report" | "dashboard" | "file" | "image" | …
  title: string;
  payload?: unknown;
  deep_link?: string | null;
}

export interface AgentResponse {
  answer_markdown: string;
  charts: AgentChartSpec[];
  citations: Citation[];
  tools_used: string[];
  generated_at: string;
  notes?: string;
  // CR-024-A (additive): link to the logged query + per-tool row counts, used by
  // the explainability panel and the feedback control.
  query_log_id?: string | null;
  row_counts?: Record<string, number>;
  // CR-011-C (additive): pending approval proposals (empty for read-only answers).
  proposed_actions?: ProposedAction[];
  // CR-011 rich steps (additive, in-session only): per-tool aggregate summaries
  // (totals/counts — never raw rows) shown in the step detail, and the turn's
  // total token usage shown as a subtle per-chat counter.
  tool_summaries?: Record<string, Record<string, unknown>>;
  usage?: { input_tokens: number; output_tokens: number };
}
