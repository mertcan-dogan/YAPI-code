import { AskAgentDrawer } from "@/components/dashboard/AskAgentDrawer";
import type { AgentScope } from "@/types/agent";
import { Coins, FileText, LineChart, Receipt, ShieldCheck, type LucideIcon } from "lucide-react";
import { useState } from "react";

// CR-011-D §4.1 — the scoped-agent launcher (the "Beceriler" half of the CR-029
// "AI Beceriler & Otomasyonlar" slot). Each round launcher opens the SAME agent
// engine scoped to a domain (one engine, many scopes) in a SideDrawer, seeded
// with a domain-appropriate starter question. "Otomasyonlar" stays "yakında"
// until CR-012.
interface Skill {
  scope: AgentScope;
  label: string;
  icon: LucideIcon;
  starter: string;
}

const SKILLS: Skill[] = [
  { scope: "gider", label: "Gider", icon: Receipt, starter: "Bu yıl en yüksek gider kalemlerim neler?" },
  { scope: "gelir", label: "Gelir", icon: Coins, starter: "Açık alacaklarımın ve tahsilatlarımın durumu nedir?" },
  { scope: "finans", label: "Finans", icon: LineChart, starter: "Genel finansal durumum ve nakit akışım nasıl?" },
  { scope: "hakedis", label: "Hakediş", icon: FileText, starter: "Hakediş ve teminat (teminat kesintisi) durumum nedir?" },
  { scope: "belge", label: "Belge", icon: ShieldCheck, starter: "İncelemem gereken faturalar veya güvence bulguları var mı?" },
];

export function ScopedAgentDock() {
  const [active, setActive] = useState<Skill | null>(null);

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
            onClick={() => setActive(s)}
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

      <AskAgentDrawer
        question={active?.starter ?? null}
        scope={active?.scope ?? null}
        onClose={() => setActive(null)}
      />
    </div>
  );
}
