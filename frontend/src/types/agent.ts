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
}
