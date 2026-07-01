import { AgentAnswerBody } from "@/components/ai/AgentAnswerBody";
import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import { SideDrawer } from "@/components/SideDrawer";
import { streamAgent } from "@/lib/agentStream";
import type { AgentResponse, AgentScope } from "@/types/agent";
import { Send, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

// CR-011 follow-up (Item 1): the scoped-agent dock opens the agent scoped to a
// domain with an EMPTY composer — it does NOT auto-submit or auto-answer.
// Suggested-prompt chips are one-click shortcuts (an explicit user action), not
// auto-fired. The agent only proposes; nothing is written without approval.
const SCOPE_TITLES: Record<AgentScope, string> = {
  gider: "Gider Agent",
  gelir: "Gelir Agent",
  finans: "Finans Agent",
  hakedis: "Hakediş Agent",
  belge: "Belge Agent",
};

const SCOPE_SUGGESTIONS: Record<AgentScope, string[]> = {
  gider: [
    "Bu yıl en yüksek gider kalemlerim neler?",
    "Hangi tedarikçiye en çok ödedim?",
    "Bütçeyi aşan kategoriler hangileri?",
  ],
  gelir: [
    "Açık alacaklarım ne kadar?",
    "Vadesi geçmiş tahsilatlar hangileri?",
    "Tahsilat performansım nasıl?",
  ],
  finans: [
    "Genel nakit akışım nasıl?",
    "Önümüzdeki 30 günde nakit ihtiyacım ne?",
    "En riskli projem hangisi?",
  ],
  hakedis: [
    "Toplam teminat kesintim ne kadar?",
    "Hangi hakedişler henüz ödenmedi?",
    "Alt yüklenici hakedişlerinin durumu nedir?",
  ],
  belge: [
    "İncelemem gereken faturalar var mı?",
    "Açık güvence bulguları neler?",
    "Olası mükerrer faturalar var mı?",
  ],
};

interface Turn {
  id: number;
  question: string;
  res: AgentResponse | null;
  live: string;
  streaming: boolean;
  step: string;
  error: boolean;
}

let _seq = 0;

export function ScopedAgentDrawer({
  scope,
  open,
  onClose,
}: {
  scope: AgentScope | null;
  open: boolean;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = turns.some((t) => t.streaming);

  // Fresh composer each time the drawer opens / the domain changes — never carry
  // over a previous answer and never auto-ask.
  useEffect(() => {
    if (open) {
      setTurns([]);
      setInput("");
      inputRef.current?.focus?.();
    }
  }, [open, scope]);

  const patch = (id: number, p: Partial<Turn>) =>
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...p } : t)));

  const ask = (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    const id = ++_seq;
    setTurns((ts) => [
      ...ts,
      { id, question: q, res: null, live: "", streaming: true, step: "Soru anlaşılıyor…", error: false },
    ]);
    streamAgent(
      { messages: [{ role: "user", content: q }], project_id: null, scope },
      {
        onDelta: (t) => setTurns((ts) => ts.map((x) => (x.id === id ? { ...x, live: x.live + t } : x))),
        onStep: (label) => patch(id, { live: "", step: label || "Veriler inceleniyor…" }),
        onFinal: (r) => patch(id, { res: r, streaming: false }),
        onError: () => patch(id, { error: true, streaming: false }),
      }
    );
  };

  const suggestions = scope ? SCOPE_SUGGESTIONS[scope] : [];

  return (
    <SideDrawer open={open} title={scope ? SCOPE_TITLES[scope] : "Yapı Agent"} onClose={onClose}>
      <AiTrustBadge compact />

      {/* Composer — always present, focused, empty on open. */}
      <form
        className="mt-3"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <div className="flex items-end gap-2 rounded-control border border-border bg-surface px-3 py-1.5 focus-within:border-brand">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={scope ? `${SCOPE_TITLES[scope]}'a sorun…` : "Yapı Agent'a sorun…"}
            className="flex-1 bg-transparent py-1.5 text-sm outline-none"
          />
          <button
            type="submit"
            disabled={!input.trim() || busy}
            className="mb-0.5 flex h-7 w-7 items-center justify-center rounded-lg bg-brand text-white disabled:opacity-40"
            aria-label="Gönder"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </div>
      </form>

      {/* Suggested-prompt chips — only before the first question. */}
      {turns.length === 0 && (
        <div className="mt-3">
          <p className="text-xs text-text-muted">Örnek sorular:</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => ask(s)}
                className="focus-ring inline-flex items-center gap-1 rounded-full border border-border bg-bg px-2.5 py-1 text-xs text-text-primary transition hover:border-brand hover:bg-surface-hover"
              >
                <Sparkles className="h-3 w-3 shrink-0 text-brand" />
                <span>{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Answers. */}
      <div className="mt-2 space-y-3">
        {turns.map((t) => (
          <div key={t.id}>
            <div className="mb-1 rounded-control bg-bg px-3 py-2 text-sm text-text-secondary">“{t.question}”</div>
            <AgentAnswerBody
              res={t.res}
              liveText={t.live}
              streaming={t.streaming}
              step={t.step}
              error={t.error}
              question={t.question}
              onNavigate={(to) => {
                onClose();
                navigate(to);
              }}
            />
          </div>
        ))}
      </div>
    </SideDrawer>
  );
}
