import type { AgentScope } from "@/types/agent";
import { Banknote, FileSearch, FileText, Receipt, Sparkles, TrendingUp, type LucideIcon } from "lucide-react";

// CR-038 §B5 — premade construction-finance agents = the agent's EXISTING scopes,
// packaged. No backend: each preset just sets the `scope` already accepted by
// /ai/agent end-to-end (verified). Six agents, one scope each, 1:1 with the
// backend SCOPE_TITLES (gider · gelir · finans · hakediş · belge) plus a general
// one (scope: null → the full toolset). Defined as data so they can later become
// data-driven user agents without a UI rewrite.
export interface AgentPreset {
  id: string;
  label: string;
  scope: AgentScope | null;
  icon: LucideIcon;
  description: string;
  // Optional Turkish framing (reserved — a future CR may seed the composer with it).
  preamble?: string;
}

export const AGENT_PRESETS: AgentPreset[] = [
  { id: "gider", label: "Gider Analisti", scope: "gider", icon: Receipt, description: "Giderler, tedarikçiler, bütçe aşımları" },
  { id: "gelir", label: "Gelir Analisti", scope: "gelir", icon: TrendingUp, description: "Satışlar, gelir, tahsilatlar" },
  { id: "finans", label: "Nakit & Finans", scope: "finans", icon: Banknote, description: "Nakit akışı, vade, likidite" },
  { id: "hakedis", label: "Hakediş Uzmanı", scope: "hakedis", icon: FileText, description: "Hakedişler, ödemeler, teminat" },
  { id: "belge", label: "Belge & Anomali", scope: "belge", icon: FileSearch, description: "Belgeler, faturalar, anomaliler" },
  { id: "genel", label: "Genel Analist", scope: null, icon: Sparkles, description: "Tüm araçlara erişen genel ajan" },
];

// "Genel Analist" (scope: null) is the default lens — the full toolset.
export const DEFAULT_AGENT: AgentPreset = AGENT_PRESETS[AGENT_PRESETS.length - 1];

export const agentById = (id?: string | null): AgentPreset => AGENT_PRESETS.find((a) => a.id === id) ?? DEFAULT_AGENT;
export const agentByScope = (scope?: AgentScope | null): AgentPreset =>
  scope ? AGENT_PRESETS.find((a) => a.scope === scope) ?? DEFAULT_AGENT : DEFAULT_AGENT;
