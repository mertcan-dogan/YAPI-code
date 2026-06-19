import { AgentAnswerBody } from "@/components/ai/AgentAnswerBody";
import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import { SideDrawer } from "@/components/SideDrawer";
import { AIDisclaimer } from "@/components/ui";
import { streamAgent } from "@/lib/agentStream";
import type { AgentResponse } from "@/types/agent";
import { ChevronRight, Send, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

// CR-011-D §4.1 — unify the rail onto the CITED agent (POST /ai/agent): real
// token streaming + a real-time step indicator, plus the CR-024 treatment
// (trust badge + citations + "AI nasıl çalıştı?" + feedback) and CR-011-C
// proposed-action cards. Replaces the legacy uncited POST /ai/assistant.
interface Turn {
  id: number;
  question: string;
  res: AgentResponse | null;
  live: string;
  streaming: boolean;
  step: string;
  error: boolean;
}

interface RailProps {
  onGoToTasks: () => void;
}

let _turnSeq = 0;

function RailContent({ onClose, hideHeader, onGoToTasks }: RailProps & { onClose?: () => void; hideHeader?: boolean }) {
  const navigate = useNavigate();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const busy = turns.some((t) => t.streaming);

  useEffect(() => {
    // Optional-call: jsdom (tests) doesn't implement Element.scrollTo.
    scrollRef.current?.scrollTo?.({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  const patch = (id: number, p: Partial<Turn>) =>
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...p } : t)));

  const ask = (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    const id = ++_turnSeq;
    setTurns((ts) => [
      ...ts,
      { id, question: q, res: null, live: "", streaming: true, step: "Soru anlaşılıyor…", error: false },
    ]);
    streamAgent(
      { messages: [{ role: "user", content: q }], project_id: null },
      {
        onDelta: (t) => setTurns((ts) => ts.map((x) => (x.id === id ? { ...x, live: x.live + t } : x))),
        onStep: (label) => patch(id, { live: "", step: label || "Veriler inceleniyor…" }),
        onFinal: (r) => patch(id, { res: r, streaming: false }),
        onError: () => patch(id, { error: true, streaming: false }),
      }
    );
  };

  return (
    <div className="flex h-full flex-col">
      {!hideHeader && (
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand-2 text-white">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold text-primary">Yapı AI</span>
          </div>
          {onClose && (
            <button onClick={onClose} className="text-text-secondary hover:text-primary" aria-label="Yapı AI panelini kapat">
              <ChevronRight className="h-4 w-4" />
            </button>
          )}
        </div>
      )}

      {/* CR-024-B / CR-011-D: always-visible trust badge (now "önerir, siz onaylarsınız"). */}
      <div className="border-b border-border px-4 py-2">
        <AiTrustBadge compact />
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-brand to-brand-2 text-white shadow-sm">
              <Sparkles className="h-6 w-6" />
            </span>
            <p className="text-sm font-semibold text-primary">Yapı AI'ya sorun</p>
            <p className="mt-1 max-w-[240px] text-xs text-text-secondary">
              Projeleriniz, marjlar, hakedişler ve nakit akışı hakkında sorun — yanıtlar şirket
              verilerinize dayanır ve kaynak gösterilir.
            </p>
          </div>
        ) : (
          <>
            {turns.map((t) => (
              <div key={t.id} className="space-y-1.5">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand px-3 py-2 text-[13px] text-white">
                    {t.question}
                  </div>
                </div>
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand-2 text-white">
                    <Sparkles className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 flex-1 rounded-2xl rounded-tl-sm bg-bg px-3 py-2">
                    <AgentAnswerBody
                      res={t.res}
                      liveText={t.live}
                      streaming={t.streaming}
                      step={t.step}
                      error={t.error}
                      question={t.question}
                      onNavigate={(to) => navigate(to)}
                    />
                  </div>
                </div>
              </div>
            ))}
            <AIDisclaimer short />
          </>
        )}
      </div>

      <div className="border-t border-border p-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
        >
          <div className="flex items-end gap-2 rounded-xl border border-border bg-surface px-3 py-1.5 focus-within:border-brand">
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Yapı AI'ya bir şey sorun…" className="flex-1 bg-transparent py-1.5 text-sm outline-none" />
            <button type="submit" disabled={!input.trim() || busy} className="mb-0.5 flex h-7 w-7 items-center justify-center rounded-lg bg-brand text-white disabled:opacity-40" aria-label="Gönder">
              <Send className="h-3.5 w-3.5" />
            </button>
          </div>
        </form>
        <button onClick={onGoToTasks} className="mt-2 w-full text-center text-xs font-medium text-brand hover:underline">
          Görevlerime git →
        </button>
      </div>

      <div className="border-t border-border bg-bg/50 p-3">
        <button
          onClick={() => navigate("/ai-assistant")}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-border py-2 text-xs font-medium text-brand transition-colors hover:border-brand hover:bg-navy-50"
        >
          Daha detaylı ve kompleks görevler için Yapı Agent'a gidin →
        </button>
      </div>
    </div>
  );
}

/**
 * Responsive wrapper for the Yapı AI rail:
 *  - xl+: a fixed right column, collapsible to a slim reopen tab.
 *  - below xl: a floating toggle that opens the rail in a SideDrawer.
 */
export function YapiAIRail(props: RailProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <>
      {collapsed ? (
        <button
          onClick={() => setCollapsed(false)}
          className="sticky top-6 hidden h-fit shrink-0 items-center gap-2 self-start rounded-l-xl border border-r-0 border-border bg-surface px-2 py-3 text-brand shadow-sm xl:flex"
          aria-label="Yapı AI panelini aç"
        >
          <Sparkles className="h-4 w-4" />
        </button>
      ) : (
        <aside className="sticky top-6 hidden h-[calc(100vh-7rem)] w-[268px] shrink-0 flex-col self-start overflow-hidden rounded-xl border border-border bg-surface shadow-sm xl:flex">
          <RailContent {...props} onClose={() => setCollapsed(true)} />
        </aside>
      )}

      <button
        onClick={() => setDrawerOpen(true)}
        className="fixed bottom-20 right-4 z-30 flex items-center gap-2 rounded-full bg-gradient-to-br from-brand to-brand-2 px-4 py-3 text-sm font-medium text-white shadow-lg xl:hidden"
        aria-label="Yapı AI"
      >
        <Sparkles className="h-4 w-4" /> Yapı AI
      </button>
      <div className="xl:hidden">
        <SideDrawer open={drawerOpen} title="Yapı AI" onClose={() => setDrawerOpen(false)}>
          <RailContent {...props} hideHeader />
        </SideDrawer>
      </div>
    </>
  );
}
