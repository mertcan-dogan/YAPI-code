import { ScopedAgentDrawer } from "@/components/dashboard/ScopedAgentDrawer";
import type { AgentScope } from "@/types/agent";
import { Coins, FileText, LineChart, Receipt, ShieldCheck, type LucideIcon } from "lucide-react";
import { useState } from "react";

// CR-011-D §4.1 — the scoped-agent launcher (the "Beceriler" half of the CR-029
// "AI Beceriler & Otomasyonlar" slot). Each round launcher opens the SAME agent
// engine scoped to a domain (one engine, many scopes) in a SideDrawer.
// CR-011 follow-up (Item 1): opening a domain shows an EMPTY composer (with
// suggested-prompt chips) — it does NOT auto-submit/auto-answer. "Otomasyonlar"
// stays "yakında" until CR-012.
interface Skill {
  scope: AgentScope;
  label: string;
  icon: LucideIcon;
}

const SKILLS: Skill[] = [
  { scope: "gider", label: "Gider", icon: Receipt },
  { scope: "gelir", label: "Gelir", icon: Coins },
  { scope: "finans", label: "Finans", icon: LineChart },
  { scope: "hakedis", label: "Hakediş", icon: FileText },
  { scope: "belge", label: "Belge", icon: ShieldCheck },
];

export function ScopedAgentDock() {
  const [active, setActive] = useState<AgentScope | null>(null);

  return (
    <div className="px-3.5 py-3">
      <p className="mb-3 text-xs text-text-muted">
        Bir alan ajanı açın — sorularınız o alana odaklanır. Ajan yalnızca önerir; onaysız hiçbir
        şey yazmaz.
      </p>
      <div className="grid grid-cols-5 gap-1.5">
        {SKILLS.map((s) => (
          <button
            key={s.scope}
            onClick={() => setActive(s.scope)}
            aria-label={`${s.label} Agent`}
            className="focus-ring group flex flex-col items-center gap-1.5 rounded-control py-2 transition-colors hover:bg-surface-hover"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-surface-soft text-text-secondary transition-colors group-hover:border-brand group-hover:text-brand">
              <s.icon className="h-[18px] w-[18px]" />
            </span>
            <span className="text-[11px] font-medium text-text-secondary">{s.label}</span>
          </button>
        ))}
      </div>

      <ScopedAgentDrawer scope={active} open={active !== null} onClose={() => setActive(null)} />
    </div>
  );
}
