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
  request_id: string;
  kind: string;
  kind_label: string;
  description: string;
  amount_try?: string | null;
  project_id?: string | null;
  status: string; // "pending"
  deep_link: string; // "/approvals"
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
}
